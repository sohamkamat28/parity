# Parity 2.0 implementation status

Updated 19 October 2026. This is a tested development candidate, with remaining platform/measurement limits recorded explicitly.

## Implemented and exercised

- Automatic URL/instructions setup with optional reviewed extraction and local-model assistance, typed values, explicit periods, baseline activation and immutable rule revisions.
- Independent capture and indexing pipelines, durable discovery/retries/leases, ownership fencing, real process interruption/recovery, idempotent publication and shared Chromium limits including previews.
- Source-grouped dashboard overviews with compact collected-data trends and expandable details, values/tables/lists, changed cells, comparable previous values, inline observed graphs with ranges, comparable deltas and evidence links, failed/stale/repair attention, persistent layout and immutable evidence.
- Editable automatic-setup schedules, reversible source removal/paused restore, explicit backed-up schema-4 upgrades, semantic HTML/JSON-LD discovery and bounded alternate-address connection attempts.
- Paginated operational/history APIs and accurate global aggregates. Committed SSE supports reconnect IDs, reset after gaps, affected-widget refresh and polling fallback while retaining view state.
- PostgreSQL hybrid retrieval, eligible exact filters, opt-in HNSW with eligible fallback, rebuildable projections and exclusion of old current versions while indexing is pending.
- Free native Qwen chat, one shared authenticated MiniLM process, retained conversations, immutable monitor/document citations and server-side comparable calculations.
- Normal REST/CLI commands and all five actual MCP protocol contracts, both direct and authenticated API bridge. Settings and sample-session features, their endpoints/commands, mock portal and archived demo sources have been removed.
- Verified populated backup/restore and explicit v1/v3 SQLite-to-PostgreSQL migrations; original SQLite hashes and referenced artifacts retained.
- Prebuilt frontend, Windows setup/launcher scripts, Docker prerequisites, configurable repository-relative data/cache paths and reproducible CI/testing/packaging commands.

## Verification

The local combined suite passed **165 tests**, with **4 intentional profile skips**: three existing PostgreSQL-only checks and the new row-lock race case skip on SQLite and pass on PostgreSQL. Production frontend build, dependency compatibility and compile checks pass. The complete macOS setup entry point also completed against a separate empty development database with verified cached model/runtime/browser assets. Browser rehearsals passed with models stopped and enabled, including automatic updates, polling fallback, failed-check recovery, narrow/keyboard navigation and monitoring after tab closure. Public scalar/list/table extraction passed on accessible pages.

Windows and Ubuntu backend, PostgreSQL integration and frontend checks passed on [the corrected CI run](https://github.com/sohamkamat28/parity/actions/runs/39095600869). Subsequent branch runs add the full PostgreSQL browser rehearsal and final integration checks; see [current CI runs](https://github.com/sohamkamat28/parity/actions).

Real MiniLM benchmark corpora at 1,000, 10,000 and 50,000 chunks include distinct vector counts, embedding reuse, quality against known targets and exact retrieval, query plans, one/five clients, latency and scoped memory/ingestion measurements. Final known-target hit@10 was 1.0 on this synthetic workload. HNSW remains opt-in. Earlier faster ranker measurements were superseded after fixing a quality bug.

Read [the complete verification report](VERIFICATION_REPORT.md), [operating guide](OPERATING_GUIDE.md) and [presentation walkthrough](PRESENTATION_WALKTHROUGH.md). Machine-readable results are in `docs/verification/`.

## Remaining checks and limits

A fresh Windows laptop's Docker/WSL and native full-model/PostgreSQL/GUI installation still requires a device rehearsal. Windows CI covers its automated native Python/SQLite/Chromium paths. True cold OS/database caches, total deployment peak memory, sustained full capture-worker throughput at scale, diverse relevance datasets and capacity beyond 50,000 chunks remain unmeasured. Native Linux local-chat setup is untested. These are not extrapolated from the Mac results.

Structured PDF field mapping, authenticated sites and multi-user/public hosting are outside this release. Existing PDF extraction/search/citations remain supported. Monitoring runs only while the services/device are running.

## Source and delivery

Upstream remains `yajask-maker/parity` at the inspected checkpoint. This device's account has read-only access there, so branch `development/parity-v2-device-integration` is pushed to [the fork](https://github.com/sohamkamat28/parity/tree/development/parity-v2-device-integration) for upstream review. Upstream review: [pull request #1](https://github.com/yajask-maker/parity/pull/1).

The versioned source ZIP and SHA-256 manifest are generated locally under `outputs/`; the ZIP includes the exact Git revision in `BUILD_INFO.json`, source, operating documentation, tests and prebuilt frontend, and excludes secrets, runtime data, captures, dependencies and downloaded assets.
