"""Start Parity, its fixture portal, and the optional free local answer model.

Only processes created by this invocation are stopped. Run setup.bat once to
install dependencies and cache models before launching.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser


class LaunchError(RuntimeError):
    pass


def ensure_ports_available(ports):
    """Fail before starting anything; never take over an unrelated server."""
    seen = set()
    for name, port in ports:
        if not 1 <= port <= 65535:
            raise LaunchError(f"The {name} port must be between 1 and 65535.")
        if port in seen:
            raise LaunchError(f"Port {port} is assigned to more than one Parity service.")
        seen.add(port)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as error:
                raise LaunchError(f"Port {port} ({name}) is occupied. Stop its existing server or "
                    "choose another port in .env. No existing process was stopped.") from error


def portal_port(origin):
    try:
        parsed = urllib.parse.urlsplit(origin)
        if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost")
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or parsed.username or parsed.password):
            raise ValueError
        return parsed.port or 80
    except ValueError as error:
        raise LaunchError("DEMO_ORIGIN must be a loopback HTTP origin, such as http://127.0.0.1:8080.") from error


class OwnedProcesses:
    """A Windows Job Object also owns grandchildren such as browser workers."""
    def __init__(self, logs):
        self.logs = logs
        self.children = []
        self._job = None
        self._kernel = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            kernel.CreateJobObjectW.restype = wintypes.HANDLE
            kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            kernel.AssignProcessToJobObject.restype = wintypes.BOOL
            kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.TerminateJobObject.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            self._job = kernel.CreateJobObjectW(None, None)
            self._kernel = kernel

    def start(self, name, command, cwd, env):
        path = self.logs / (name + ".log")
        log = path.open("ab", buffering=0)
        log.write(("\n--- Parity launch " + time.strftime("%Y-%m-%d %H:%M:%S") + " ---\n").encode())
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                start_new_session=os.name != "nt")
        except BaseException:
            log.close()
            raise
        assigned = bool(self._job and self._kernel.AssignProcessToJobObject(self._job, child._handle))
        self.children.append((name, child, log, path, assigned))
        return child

    def check(self):
        for name, child, _, path, _ in self.children:
            code = child.poll()
            if code is not None:
                raise LaunchError(f"{name} exited with code {code}. See {path} for details.")

    def close(self):
        if self._job:
            self._kernel.TerminateJobObject(self._job, 0)
        for _, child, _, _, assigned in reversed(self.children):
            if child.poll() is not None:
                continue
            try:
                if os.name == "nt" and not assigned:
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW, timeout=10, check=False)
                elif os.name != "nt":
                    import signal
                    os.killpg(child.pid, signal.SIGTERM)
            except (OSError, subprocess.TimeoutExpired):
                child.terminate()
        for _, child, log, _, _ in self.children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            finally:
                log.close()
        if self._job:
            self._kernel.CloseHandle(self._job)
            self._job = None


def read_json(opener, url, timeout=2):
    try:
        with opener.open(url, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.load(error)
        except (ValueError, OSError):
            return error.code, {}
    except (OSError, ValueError):
        return None, {}


def wait_ready(owned, checks, timeout, opener):
    pending = dict(checks)
    deadline = time.monotonic() + timeout
    next_update = 0
    while pending:
        owned.check()
        for name, url in list(pending.items()):
            code, _ = read_json(opener, url)
            if code == 200:
                print(f"  {name}: ready", flush=True)
                del pending[name]
        if not pending:
            return
        if time.monotonic() >= deadline:
            raise LaunchError("Startup timed out waiting for " + ", ".join(pending)
                + f". Check logs in {owned.logs}; rerun setup.bat if assets are missing.")
        if time.monotonic() >= next_update:
            print("  Waiting for " + ", ".join(pending) + "...", flush=True)
            next_update = time.monotonic() + 10
        time.sleep(.4)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true", help="Print the connection link without opening a browser")
    parser.add_argument("--startup-timeout", type=int, default=300, help="Seconds to wait for cached models and servers (default: 300)")
    args = parser.parse_args(argv)
    if not 10 <= args.startup_timeout <= 1800:
        parser.error("--startup-timeout must be between 10 and 1800 seconds")
    root = Path(__file__).resolve().parent
    owned = None
    try:
        try:
            from parity import config
            from parity.browser import browser_status
        except ModuleNotFoundError as error:
            raise LaunchError("Python dependencies are missing. Run setup.bat, then start.bat.") from error
        except ValueError as error:
            raise LaunchError("Check numeric port settings in .env.") from error
        provider = config.CHAT_PROVIDER.lower().strip()
        if provider not in ("local", "openai"):
            raise LaunchError("PARITY_CHAT_PROVIDER must be local or openai.")
        demo_port = portal_port(config.DEMO_ORIGIN)
        ports = [("Parity", config.API_PORT), ("fixture portal", demo_port)]
        if provider == "local":
            ports.append(("local chat", config.LOCAL_CHAT_PORT))
        ensure_ports_available(ports)
        if not (root / "frontend" / "dist" / "index.html").is_file():
            raise LaunchError("The bundled frontend is missing. Extract a complete Parity release.")
        if browser_status()["status"] != "installed":
            raise LaunchError("Matching Chromium is missing. Run setup.bat to install browser support.")
        local_command = None
        if provider == "local":
            runtime = root / ".cache" / "local-chat" / "runtime" / "llama-server.exe"
            model = root / ".cache" / "local-chat" / (config.LOCAL_CHAT_MODEL + ".gguf")
            if not runtime.is_file() or not model.is_file():
                raise LaunchError("The free local answer model is missing. Run setup.bat to install it.")
            local_command = [str(runtime), "--model", str(model), "--host", "127.0.0.1",
                "--port", str(config.LOCAL_CHAT_PORT), "--ctx-size", "4096",
                "--threads", "4", "--parallel", "1", "--n-gpu-layers", "0",
                "--alias", config.LOCAL_CHAT_MODEL]
        env = os.environ.copy()
        token = env.get("PARITY_ADMIN_TOKEN", "").strip() or secrets.token_urlsafe(24)
        env["PARITY_ADMIN_TOKEN"] = token
        env["DEMO_ADMIN_TOKEN"] = env.get("DEMO_ADMIN_TOKEN", "").strip() or secrets.token_urlsafe(24)
        env["PARITY_BOOTSTRAP_TOKEN"] = secrets.token_urlsafe(32)
        env["PARITY_CHAT_PROVIDER"] = provider
        env["PARITY_LOCAL_CHAT_TOKEN"] = secrets.token_urlsafe(32)
        if local_command:local_command.extend(["--api-key",env["PARITY_LOCAL_CHAT_TOKEN"]])
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONUTF8"] = "1"
        logs = config.DATA / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        owned = OwnedProcesses(logs)
        checks = {}
        print("Starting Parity. Loading cached models may take a moment.", flush=True)
        if local_command:
            owned.start("local-chat", local_command, root, env)
            checks["Local answer model"] = f"http://127.0.0.1:{config.LOCAL_CHAT_PORT}/health"
        for name, app, port in [("portal", "mock_portal.app:app", demo_port),
                                ("parity", "parity.api:app", config.API_PORT)]:
            owned.start(name, [sys.executable, "-m", "uvicorn", app, "--host", "127.0.0.1",
                "--port", str(port), "--no-access-log"], root, env)
        base = f"http://127.0.0.1:{config.API_PORT}"
        checks["Fixture portal"] = f"http://127.0.0.1:{demo_port}/health/ready"
        checks["Database + embedding model"] = base + "/health/ready"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        wait_ready(owned, checks, args.startup_timeout, opener)
        print("  JavaScript browser: installed", flush=True)
        if provider == "openai":
            configured = bool(env.get("OPENAI_API_KEY", "").strip())
            print("  OpenAI chat: " + ("configured; test the connection in Diagnostics" if configured
                else "not configured; add OPENAI_API_KEY to .env or use PARITY_CHAT_PROVIDER=local"), flush=True)
        link = base + "/#token=" + urllib.parse.quote(env["PARITY_BOOTSTRAP_TOKEN"], safe="")
        print("\nPARITY: " + base, flush=True)
        print("Connect automatically (one use): " + link, flush=True)
        print("Parity access token (reusable during this launch): " + token, flush=True)
        print(f"Fixture portal: http://127.0.0.1:{demo_port}/en/circulars/", flush=True)
        print("Logs: " + str(logs), flush=True)
        print("Keep this window open. Ctrl+C stops Parity and its owned services.\n", flush=True)
        if not args.no_browser:
            try:
                webbrowser.open(link)
            except Exception:
                print("Open the connection link above in your browser.", flush=True)
        while True:
            owned.check()
            time.sleep(.5)
    except KeyboardInterrupt:
        print("\nStopping Parity...", flush=True)
        return 0
    except (LaunchError, OSError) as error:
        print("\nParity could not start: " + str(error), file=sys.stderr, flush=True)
        return 1
    finally:
        if owned is not None:
            owned.close()


if __name__ == "__main__":
    raise SystemExit(main())
