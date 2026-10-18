# Parity 2.0 operating guide

## What runs on your device

PostgreSQL/pgvector runs in Docker with a persistent named volume. Native Python runs one API, one scheduler, two capture workers and one indexing worker. Capture workers and interactive previews share one Chromium slot. One authenticated loopback MiniLM service handles query and indexing embeddings; the free Qwen answer server runs with one generation slot. Static monitoring does not require either model or Chromium.

GitHub stores source and runs finite automated checks. GitHub Pages cannot host the database or Python workers, and Actions are not the monitoring server. Keep the launcher running; closing the browser is safe. Sleeping/shutting down the device or stopping services stops checks. Parity reports collected observations, not measurements taken between checks.

## Obtain the development branch

The source repository is `yajask-maker/parity`. This device's GitHub account lacks write permission there; the review branch is pushed to its fork:

```sh
git clone https://github.com/yajask-maker/parity.git
cd parity
git remote add parity-dev https://github.com/sohamkamat28/parity.git
git fetch parity-dev development/parity-v2-device-integration
git switch -c development/parity-v2-device-integration --track parity-dev/development/parity-v2-device-integration
```

If already cloned, first check `git status` and preserve your changes. Do not replace an existing data directory or `.env`.

## Windows setup

1. Install Python 3.14 x64 and Docker Desktop for Windows. Follow [Docker's Windows/WSL requirements](https://docs.docker.com/desktop/setup/install/windows-install/): supported Windows, virtualization enabled and a supported WSL 2 installation/backend. Complete any requested restart and select Linux containers. Parity does not install WSL, enable virtualization or request administrator changes.
2. Open Docker Desktop and verify `docker info` succeeds. If port 5432 is occupied, set a different `PARITY_DB_PORT` in the ignored `.env` before first setup. Do not change a volume's generated database password without explicitly changing the database role too.
3. Run `setup.bat`. It creates `.venv`, installs the locked dependencies, starts/checks PostgreSQL, installs matching Chromium and downloads hash-verified llama.cpp/Qwen assets and the pinned MiniLM revision.
4. Run `start.bat`. Use its one-time connection link or reusable access token. Keep the window open. Ctrl+C stops its owned application processes; the database volume persists.

Monitoring-only setup: `setup.bat -WithoutModels`, then `start.bat --without-models`. Add `-WithoutBrowser` for static HTML only. Install omitted capabilities later by rerunning normal setup.

SQLite compatibility: `setup.bat -Profile sqlite`, then `start.bat --profile sqlite`. An explicit SQLite `DATABASE_URL` is also a deliberate profile selection. There is no automatic PostgreSQL-to-SQLite fallback.

Windows CI exercises Python, SQLite, Chromium, protocol and backup behavior. It does not verify a real Windows desktop's Docker/WSL installation or native local-model setup; see the verification report.

## macOS/Linux development

On macOS arm64 with Python 3.14 and Docker Desktop:

```sh
python3.14 -m venv .venv
.venv/bin/python scripts/setup.py
.venv/bin/python run.py --no-browser
```

`uv venv --python 3.14` can create the environment; if it omits pip, use `uv pip install --python .venv/bin/python -r requirements-lock.txt -r requirements-postgres.txt` first. A normal `venv` includes pip.

Linux static/browser development uses the same Python entry points, but requires Playwright system dependencies (`python -m playwright install --with-deps chromium`). Bundled local-chat downloads support Windows x64 and macOS arm64. Other systems must provide a native `llama-server` via PATH or `PARITY_LLAMA_SERVER`, plus the verified Qwen GGUF in the cache. That native Linux chat setup is untested here.

If chat reports that its service is stopped, inspect `local-chat.log` in the configured data directory. On macOS, an empty log together with a DiagnosticReports entry containing `CODESIGNING` / `Taskgated Invalid Signature` can follow an older setup overwriting an executable in place. Run `.venv/bin/python scripts/setup_local_chat.py`, then restart `.venv/bin/python run.py`. Setup now installs runtime files by atomic replacement and verifies the executable starts. No Gatekeeper setting changes are needed. Monitoring and evidence search remain available while chat is stopped.

## Configuration and readiness

Copy `.env.example` only when `.env` does not already exist. Relevant settings:

| Setting | Purpose |
| --- | --- |
| `PARITY_DATA_DIR` | Database/artifacts/logs directory; default `data` |
| `PARITY_CACHE_DIR` | Model/browser cache directory; default `.cache` |
| `DATABASE_URL` | Explicit native PostgreSQL connection, or explicit SQLite URL |
| `PARITY_DB_PORT` / `PARITY_DB_PASSWORD` | Generated local Docker connection; preserve across restarts |
| `PARITY_PORT`, `PARITY_LOCAL_CHAT_PORT`, `PARITY_EMBEDDING_PORT` | Loopback service ports |
| `PARITY_PROFILE` | `postgresql` by default, or explicit `sqlite` |
| `PARITY_OFFLINE` | Normal startup uses installed model assets; setup allows downloads |
| `PARITY_ANN_ENABLED` | Default `0`: exact eligible retrieval; optional ANN must be evaluated on your corpus |

Relative data/cache paths resolve against the repository directory, not your terminal's working directory. Absolute paths can point outside the repository. Keep `.env`, data, captures, model assets, dependencies and access tokens out of Git. Optional paid OpenAI support remains configurable; normal operation and CI do not require credentials.

`/health/live` reports the API process; `/health/ready` checks the database. Settings → System status separately reports monitoring workers, Chromium, indexing, the embedding service and chat. A downloaded model is not proof that its service is running. If embedding/chat fails, static monitoring continues and indexing retries independently. Logs live under `PARITY_DATA_DIR/logs` and can contain launch access tokens; do not publish them.

## Set up a monitor

Use **Start monitoring → Website → What to track → Start automatically**. The source name is optional. Parity finds matching fields in HTML, tries Chromium when no usable match is found, validates extracted values against a stored capture, and opens the populated dashboard. Numeric values become cards, tables remain tables, and announcements become linked update lists. No selector or widget configuration is required. If the page cannot be fetched or a requested value cannot be identified, setup reports the problem without starting an empty monitor.

Choose **Preview extraction** instead when you want to inspect or customize fields and scope before starting. Every enabled field still requires successful validation. CSS selectors and manual rules are under Advanced settings.

New monitors default to this page, one document, zero link depth, 15 minutes and an immediate baseline check. Existing source schedules remain intact. Wider scopes display candidate included/excluded links and explicit depth/document limits; the preview is a bounded sample, not an exhaustive site map. Structured rules apply to their reviewed page; other in-scope documents remain available for document search. Add separate reviewed monitors for additional pages.

Automatic label/value detection works when local AI is unavailable; the model is a fallback for descriptions without a direct label match. Advanced settings contain CSS rules, rendering and allowed resource origins. A manual rule can select scalar text or attributes, a table, a table cell bound to a row label/header, or a stable-link list. Numeric units and explicit date formats are editable. For a table-cell field, explicitly choose a fixed reporting period or follow the latest period and specify whether the newest column is first or last. Ambiguous duplicate row labels/headers and merged cells require repair. Structured PDF field mapping is deferred; PDF document extraction/search/citations remain supported.

Zero is a value. Empty/missing/invalid fields are different states. An unchanged valid extraction advances verification. A failed extraction retains the previous verified value and warning. New periods are distinct from same-period revisions. Reordered announcements retain identity; an item no longer present in a limited list is not a confirmed deletion.

## Dashboard, history and chat

Dashboard offers all-source and source views, paginated monitors, scalar cards, table cell changes, announcement links, persisted pin/order/hide preferences, and failed/stale/extraction-repair attention. Last checked, last verified, last changed and next check have separate meanings. View history opens collected observations and comparable numeric plots. View evidence opens an immutable capture and location.

Changes & History lists tracked field changes, document changes and versions. Ask Parity performs fresh retrieval per turn and retains conversations/citation snapshots. Current search excludes old document versions as soon as a newer capture is published, including while the new version awaits indexing. The API reports **Search index updating**; structured values remain independently available. Historical search uses recorded availability intervals.

Local chat selects evidence; the server constructs monitored values and supported comparable differences/percentage changes. Operands must share a unit and reporting period. Percentage change from zero is undefined. Calculation citations link both immutable captures. Evidence content is treated as untrusted; it cannot issue instructions to the application.

Demo Lab lives under Settings → Demo & Testing. Demo/benchmark sources are excluded from normal dashboards and default retrieval. Include test sources explicitly to inspect their monitoring; explicit source IDs allow testing chat/search. All demonstration numbers are synthetic.

## Backup and restore

Stop application workers before operational transfer or restore. Backups use a consistent database snapshot and include all referenced captures, version artifacts and portal state. Hashes/counts are verified. The tools never overwrite an existing backup file or populated restore destination.

Set `DATABASE_URL` locally to the source connection; the command names the environment variable rather than embedding credentials in shell history:

```sh
python scripts/backup_data.py create --data /path/to/source-data --archive /path/to/new-backup.zip
python scripts/backup_data.py verify --archive /path/to/new-backup.zip
```

For restore, set `PARITY_RESTORE_URL` to an **empty** PostgreSQL database and choose an empty capture directory:

```sh
python scripts/backup_data.py restore --url-env PARITY_RESTORE_URL --data /path/to/empty-restored-data --archive /path/to/new-backup.zip
```

Use PowerShell environment assignment and Windows paths on Windows. Restore preserves evidence IDs/history/chats/citations, verifies table and file hashes, rebuilds a legacy search projection if needed, repairs event sequences and clears obsolete worker ownership. Durable work resumes; process leases are intentionally not restored as live ownership.

## Explicit SQLite-to-PostgreSQL migration

No existing installation is discovered or imported automatically. Provide a SQLite DB path, data directory or installation directory. Set `PARITY_TARGET_URL` locally to an empty PostgreSQL database, then:

```sh
python scripts/migrate_data.py --source /path/to/old-installation --target-url-env PARITY_TARGET_URL --target-data /path/to/new-empty-data --backup /path/to/before-migration.zip
```

The tool backs up first, retains the original SQLite file and verifies counts/hashes after copy. Point the application at the new URL and data directory only after reviewing success. Preserve the old installation and backup until independently satisfied. Never use a personal installation as a test fixture.

## Reproduce verification and package

```sh
python scripts/test.py --postgres
python scripts/browser_acceptance.py
python scripts/browser_acceptance.py --with-models
python scripts/public_acceptance.py
python scripts/run_benchmark.py
npm --prefix frontend ci
npm --prefix frontend run build
python scripts/package_release.py --version 2.0.0-dev.20261018
```

PostgreSQL tests use a dedicated server and unique disposable databases; the selected role needs CREATE DATABASE. Model/browser caches must already be installed for the optional checks. Benchmark reports separate ingestion scope, actual vector counts, known-target quality, exact/ANN comparisons, one/five clients, query plans and memory scope. First-client runs do not flush OS/database caches and are not true cold-cache claims.

The ZIP is written to `outputs/` with a SHA-256 manifest and exact Git revision. It contains tracked source, documentation and the prebuilt frontend, and excludes runtime data/caches/secrets. See [the verification report](VERIFICATION_REPORT.md) before making deployment or capacity claims.

## CLI and MCP compatibility

The existing CLI commands and five MCP tools retain their names and arguments. The native deployment runs separate capture/index workers; a completed crawl can have pending semantic indexing. A standalone `cli.py worker` performs scheduled capture work; run `python -m parity.worker --role index` separately if using that compatibility entry point outside the launcher.

For a desktop MCP client, prefer the authenticated API bridge so it shares the running application's MiniLM service. Configure the command as your native `.venv` Python with arguments `-m parity.mcp_server`, the repository as working directory, and environment values `PARITY_MCP_API_URL=http://127.0.0.1:8000` plus `PARITY_ADMIN_TOKEN` from the current local launcher. Keep the token in the client's local private configuration. The tools are `search_docs`, `get_page`, `get_page_history`, `diff_versions` and `list_recent_changes`. Standalone direct-database mode is retained for compatibility and explicit offline/test use.
