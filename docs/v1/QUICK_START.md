# Run Parity on Windows

**Free local chat is the default. No OpenAI key, API credits, paid account, Node.js, or public hosting is needed to present the demo.**

## On this laptop

The workspace copy has already been set up and tested. Double-click **Launch_Parity.cmd** in the outputs folder. On its first launch, it creates a separate presentation database using the cached models, preserving the verification runs and your original installation. Later launches retain your presentation data.

Keep the launcher window open. It waits for the portal, MiniLM, and local answer model, then opens the dashboard with a one-use connection link. If opening a second browser, paste the reusable **Parity access token** printed in that window into Connect workspace. These tokens are local access tokens, not OpenAI API keys.

## From the ZIP or on another Windows computer

1. Extract `Parity_Windows_Demo.zip` into a new writable folder, such as `Documents\ParityDemo`. Do not merge it into the original MVP installation.
2. Open its **Parity** folder and double-click **setup.bat** once. Internet is needed for dependency, model, and Chromium downloads. The local chat model is approximately 1.1 GB; allow several GB for the complete installation and download caches.
3. Double-click **start.bat**. No frontend build step is required; the React application is already bundled.
4. In **Demo Lab**, create a fresh demonstration and run the numbered steps. Follow `PRESENTATION_WALKTHROUGH.md`.

Tested on **Windows x64, Python 3.14.7, a laptop with approximately 16 GB RAM**, using CPU inference. Setup requires Python 3.14; it checks the environment before installing the Windows-tested dependency lock. Loading both models may take tens of seconds. Close memory-heavy applications if startup is slow.

PowerShell equivalents from the extracted Parity folder:

```powershell
.\setup.bat
.\start.bat
```

After setup, the direct Python launch command is:

```powershell
.\.venv\Scripts\python.exe run.py
```

Dashboard: `http://127.0.0.1:8000` · Mock portal: `http://127.0.0.1:8080/en/circulars/`

## Data and configuration

`data/` contains the SQLite databases, immutable content artifacts, conversations, and logs. `.cache/` contains the downloaded models, Chromium, and local model runtime. The source ZIP includes neither directory. The original recovered installation and its data have not been modified.

Optionally copy `.env.example` to `.env` and edit the settings. Do not copy the example over an existing `.env`. The free default is `PARITY_CHAT_PROVIDER=local`. An OpenAI key already present in `.env` is unused in local mode. Optional OpenAI mode requires `PARITY_CHAT_PROVIDER=openai`, a funded key, and a supported model; it sends selected evidence to OpenAI. Keep `.env` private.

Normal model loading uses the cached MiniLM revision without downloading. Crawling public websites still needs an internet connection; the fixture portal and local chat can run offline after setup. The launcher binds all services to loopback only. Default ports are 8000, 8080, and 8091; if a port is occupied it reports the conflict without stopping the other program. Change `PARITY_PORT`, `DEMO_ORIGIN`, and `PARITY_LOCAL_CHAT_PORT` in `.env` if needed.

## Troubleshooting

- **Missing Python/dependencies/model/browser:** run setup.bat and read the first failed command. Setup is safe to rerun and reuses verified downloads.
- **Port occupied:** close the previous Parity launcher with Ctrl+C, or choose unused ports. Do not run two launchers against the same database.
- **No answer model:** inspect Diagnostics and the logs folder printed by the launcher: `data/logs/` for start.bat, or `data/presentation/logs/` for the workspace launcher. Check `local-chat.log` there. Evidence search still works. Local answers are short, exact evidence excerpts selected by Qwen; they are not a general-purpose chatbot.
- **No documents:** run a source crawl. New sources use manual sync until scheduling is enabled. For a JavaScript site, select browser rendering, set a reliable ready selector, and explicitly list any required external script/API origins.
- **Source partial/failed:** open Sources → Crawl history → the run. Failed rendering or extraction retains the previous complete version and shows the failure. Some sites intentionally block automation or need unsupported authentication.
- **Need to stop:** press Ctrl+C in the launcher. It stops only services that it started. If a service exits unexpectedly, the launcher reports its log and stops the others.

## CLI and MCP

Run these commands from the Parity folder. If you use the workspace's **Launch_Parity.cmd**, first select its presentation database in the same PowerShell window:

```powershell
$env:PARITY_DATA_DIR = (Resolve-Path .\data\presentation).Path
```

The folder exists after your first presentation launch. If you extracted the ZIP and use **start.bat**, omit that setting to use the default `data/` database.

```powershell
.\.venv\Scripts\python.exe cli.py status
.\.venv\Scripts\python.exe cli.py search "honours registration deadline"
.\.venv\Scripts\python.exe cli.py history PAGE_ID
.\.venv\Scripts\python.exe cli.py diff PAGE_ID 1 2
```

Point an MCP client's stdio configuration at this installation's **absolute** `.venv\Scripts\python.exe`, with arguments `-m parity.mcp_server` and `cwd` set to the Parity folder. For the workspace presentation database, also set the client's `PARITY_DATA_DIR` environment variable to the absolute path of `work\Parity\data\presentation`; otherwise it uses the default `data/` database. The five tools remain `search_docs`, `get_page`, `get_page_history`, `diff_versions`, and `list_recent_changes`. Standalone MCP uses the selected database and cached MiniLM. Diagnostics launches a real MCP subprocess with an authenticated local API bridge, sharing the active application's database and already-loaded semantic model to reduce memory use.

## Development

The Python API serves `frontend/dist`. Node is needed only when changing the frontend:

```powershell
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe -m pytest tests -q
```

Restart the launcher after Python changes. Reload the browser after rebuilding frontend assets. API docs are available at `/docs`. See `VERIFICATION_REPORT.md` for tested behavior and scope limits.
