# Parity 2.0

Website monitoring, immutable evidence, version history and free local AI chat. Track reviewed fields on public HTML pages and inspect their changes without asking chat. PDF extraction, document search, REST, CLI and all five MCP tools remain available.

**Development candidate, 18 October 2026.** See the [verification report](docs/VERIFICATION_REPORT.md) for actual results and remaining Windows deployment checks. Historical reports in `archive/v1` and `docs/v1` do not verify this version.

## Fresh Windows installation

Install Python 3.14 and Docker Desktop with Linux containers and its WSL 2 backend. Open Docker Desktop and wait for the engine. In a fresh clone:

```powershell
git clone https://github.com/yajask-maker/parity.git
cd parity
# Check out the reviewed development branch/PR before setup.
.\setup.bat
.\start.bat
```

Setup uses pinned Python dependencies, verified llama.cpp/Qwen downloads, MiniLM and matching Chromium. No paid API key or Node installation is needed to use the bundled frontend. Follow [the operating guide](docs/OPERATING_GUIDE.md) for the exact development branch, Docker prerequisites, configuration, backup and migration commands.

A monitoring-only setup can omit models, and browser support can be omitted for static HTML:

```powershell
.\setup.bat -WithoutModels
.\start.bat --without-models
```

SQLite is an explicit compatibility profile: `setup.bat -Profile sqlite`, then `start.bat --profile sqlite`. PostgreSQL/pgvector is the default. Monitoring runs while the services run, even with the browser tab closed; it stops when the device or services stop.

## macOS development

Use Python 3.14 and Docker Desktop. This device was verified with Python 3.14.6 on an Apple M4 Mac.

```sh
python3.14 -m venv .venv
.venv/bin/python scripts/setup.py
.venv/bin/python run.py
```

The native local-chat download supports macOS arm64 and Windows x64. Linux and other architectures can supply `PARITY_LLAMA_SERVER` and the verified GGUF; that native configuration has not been exercised here.

## Verification and frontend build

```sh
.venv/bin/python scripts/test.py --postgres
.venv/bin/python scripts/browser_acceptance.py
.venv/bin/python scripts/browser_acceptance.py --with-models
npm --prefix frontend ci
npm --prefix frontend run build
```

Windows uses `.venv\Scripts\python.exe`. PostgreSQL tests create disposable `parity_test_*` databases through `PARITY_TEST_DATABASE_URL` or the locally configured PostgreSQL connection; use a dedicated development server with database-creation permission. Live-network checks and model benchmarks are optional and separate from deterministic CI.

## Files and data

- `parity/`: API, structured monitoring, durable workers, retrieval, chat and transfer tools.
- `frontend/src/` and `frontend/dist/`: editable React source and prebuilt application.
- `scripts/`: setup, validation, explicit migration, backup and packaging.
- `docs/`: [operating guide](docs/OPERATING_GUIDE.md), [presentation walkthrough](docs/PRESENTATION_WALKTHROUGH.md), [status](docs/IMPLEMENTATION_STATUS.md), verification results.
- `outputs/`: versioned local source ZIP and manifest after packaging.

Configuration belongs in an ignored `.env`. Data/cache directories are configurable and relative values resolve from the repository, regardless of the launch directory. No databases, captures, credentials or downloaded assets belong in Git. Setup does not import an old installation; SQLite-to-PostgreSQL transfer requires an explicit source path and creates a verified backup first.
