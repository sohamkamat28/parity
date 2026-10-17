# Parity

Website monitoring, captured evidence, version history and local AI chat.

**Current snapshot: Parity 2.0 development, 17 October 2026.** The source and compiled frontend are included. Integration and acceptance testing are still in progress; this is not a completed production release.

## Repository structure

| Path | Contents |
| --- | --- |
| `parity/` | FastAPI service, monitoring rules, immutable observations, durable workers, retrieval and chat |
| `frontend/src/` | React and TypeScript dashboard and source setup |
| `frontend/dist/` | Prebuilt frontend, served by the Python application |
| `mock_portal/` | Controlled website fixtures for testing |
| `scripts/` | Model setup, validation, migration and backup utilities |
| `tests/` | Lifecycle, monitoring, worker and chat tests |
| `docs/` | Current status and historical operating documentation |
| `archive/v1/` | Previously delivered Windows demo source, kept separate from 2.0 |

## Windows development setup

Install Python 3.14 and Docker Desktop with its WSL 2 backend. Start Docker Desktop, then run in the repository directory:

```powershell
.\setup.bat
.\start.bat
```

Setup downloads dependencies, Chromium and local model assets. PostgreSQL with pgvector is the default application profile. Node is needed only when rebuilding the frontend.

Explicit SQLite compatibility profile:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Profile sqlite
.\start.bat --profile sqlite
```

Monitoring-only development startup (without answer and embedding models):

```powershell
.\start.bat --profile sqlite --without-models
```

These are current implementation entry points; full 2.0 Windows/Docker acceptance remains pending. See [implementation status](docs/IMPLEMENTATION_STATUS.md) before presenting this snapshot.

## Frontend development

```powershell
cd frontend
npm ci
npm run build
```

## Data and credentials

No API key is required for the default local chat model. Optional OpenAI configuration belongs in your ignored local `.env` file. Databases, captures, personal installation data, downloaded models, browsers, dependencies and credentials are excluded from this repository. No user data has been migrated by this upload.

Monitoring runs while the Python services are running, even when the browser tab is closed. This release targets a single local user and public websites.
