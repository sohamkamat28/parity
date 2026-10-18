# Parity 2.0 verification report

Verified on 18 October 2026 from the current development branch. Upstream was fetched again and remained at `a344436cd8e7a292a080f3ba3a2b38da6e6eba00`. This report concerns v2; historical v1 reports are not acceptance evidence.

## Result

The monitoring-to-dashboard flow works on this device with native Python services and PostgreSQL/pgvector in Docker. It also works with answer and embedding services stopped. Free native Qwen chat and shared MiniLM were exercised separately. Source, prebuilt frontend, Windows setup/launchers, Docker configuration, transfer tools, reproducible tests/benchmarks and packaging are included. The full native macOS setup entry point completed, and a separate empty development database is configured locally.

The signed-in account lacks push permission on `yajask-maker/parity`; the development branch is pushed to `sohamkamat28/parity` for an upstream pull request. No force push, merge, visibility change or repository setting change was performed.

## Device and configuration

- Apple M4, arm64, 10 logical CPUs, 16 GiB RAM, macOS 27.0.1; native Python 3.14.6.
- Node 26.8.1 / npm 11.19.0 for the local frontend build; Vite 7.3.7, React 19.2.0, TypeScript 5.9.3.
- Docker Desktop engine 29.6.2, PostgreSQL 16 with pgvector 0.8.1, persistent `parity2` volume, loopback port 55432 on this device.
- One API, one scheduler, two capture workers, one indexing worker, one Chromium reservation, one authenticated MiniLM service, one native llama.cpp b11642 Qwen 2.5 1.5B Q4_K_M generation slot.
- MiniLM revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`; downloaded model/browser assets remain outside Git. Detailed installed versions are in [device.json](verification/device.json).
- All acceptance/migration/benchmark databases were isolated synthetic databases. No previous installation or personal data was imported. Relative cache/data paths are resolved from the repository.

## Automated and integrated checks

| Check | Result / evidence |
| --- | --- |
| Full local deterministic suite, SQLite plus actual PostgreSQL | **107 passed, 3 intentional skips**; [JUnit record](verification/backend-junit.xml) |
| Intentional skips | PostgreSQL-only v3 migration, v1 migration and rank-fusion cases skip their SQLite variant; their PostgreSQL variants pass |
| Existing lifecycle/release/chat regressions | Pass, including Chromium and PDF lifecycle checks; positive demo retrieval now requires explicit IDs and asserts nonempty results |
| Worker independence and recovery | Capture succeeds without model readiness, indexing retries independently, persisted Retry-After does not block other origins, generation fencing and one browser slot pass |
| Actual process interruption | A capture subprocess exits after saving its response; another worker resumes it without duplicate document/check/monitor publication |
| Typed extraction | Zero vs missing, currency/units/dates, table row/header binding, explicit fixed/latest first/last columns, list reorder and no-longer-listed semantics pass |
| Field history | Unrelated page/formatting changes do not create field changes; failed extraction/HTTP attempts preserve prior verified values and recover; revisions remain frozen per job |
| Dashboard/API | Paginated lists, global database aggregates, comparable previous values, table change detail, stale attention, layout preferences and bounded widget refresh pass |
| Committed SSE | Event IDs, backlog/reset handling, restored-ahead cursor handling, snapshot watermark and browser polling fallback pass |
| Retrieval eligibility | Pending current versions exclude old passages; history intervals, availability and model signatures pass; PostgreSQL retrieves from the 50,000-chunk corpus without the SQLite cap |
| Hybrid quality regression | Generic dense candidates cannot receive lexical rank credit merely for sharing common query terms; known-target regression passes |
| All five MCP tools | Actual initialize/list/call protocol checks pass on SQLite and PostgreSQL, both direct and through the authenticated API bridge |
| Backup / restore | Populated captures, versions, observations, changes, chats/citation snapshots, projection and file hashes/counts survive; nonempty destinations are rejected |
| Migration | Populated v3 SQLite → PostgreSQL and legacy v1 vectors/history → PostgreSQL pass; original SQLite byte hash is retained and the legacy projection is rebuilt |
| Frontend | TypeScript/Vite production build passes; prebuilt assets included; npm audit reports zero vulnerabilities after the Vite 7 patch update |
| Python | Compile checks pass; installed dependency compatibility check passes; full pinned requirements install on this Mac after marking pywin32 Windows-only |
| GitHub CI | Windows and Ubuntu backend, PostgreSQL integration and frontend checks passed on `f6317d0`; final branch reruns include the PostgreSQL browser rehearsal. Follow the linked run recorded in the delivery status below |

[GitHub CI](https://github.com/sohamkamat28/parity/actions) uses no paid API credentials. Live public-site checks and model benchmarks remain separate from deterministic CI. Windows CI uses Python 3.14.8 and matching Chromium; it is distinct from testing Docker/WSL and downloaded answer-model setup on a Windows laptop.

## Actual browser acceptance

The headless browser operated the production frontend against the native launcher, two real capture workers and PostgreSQL. Both [models-stopped](verification/browser-no-models.json) and [models-enabled](verification/browser-models.json) rehearsals passed with no page JavaScript errors:

1. Four-step setup reviewed scalar, zero percentage, table and linked announcement fields and preserved the existing fixture schedule.
2. Scheduled changes appeared through SSE without asking chat or clicking Check now; original capture text remained unchanged and table cells were highlighted.
3. Footer-only changes advanced verification without field-change events. An open evidence dialog and pinned preference survived refreshes.
4. HTTP 403 retained the last valid value with attention; the next successful check recovered.
5. Blocking SSE exercised polling fallback. Announcement additions appeared automatically.
6. The 390px viewport had no document-level horizontal overflow; navigation focus/keyboard behavior and reduced motion were exercised. Desktop and narrow screenshots remain in the report's ignored runtime paths.
7. Closing the tab did not stop scheduled capture. Persisted layout survived.
8. Native free Qwen selected immutable evidence while shared MiniLM was available. Comparable differences/percentages are assembled server-side with both immutable operand captures; zero-denominator percentages are undefined.

Current dashboard events refresh affected loaded monitor widgets; periodic snapshots reconcile pagination/new monitors and handle stream gaps. Screen filters, evidence selection and chat drafts remain in component state across updates.

## Optional public pages

All three checks passed through the validated native fetcher with models unused: a GBP scalar and stable-link list from Books to Scrape, and a table from the W3Schools HTML table example. Reviewed activation and immutable evidence were verified. See [public-pages.json](verification/public-pages.json) for exact URLs, selectors and normalized samples. These are observations from this run, not a promise of continued site accessibility.

## Measured retrieval and ingestion

Reproducible deterministic corpora use 10 chunks per document, explicit shared text for embedding reuse, 20 known-project queries per warm scenario, and real MiniLM vectors through one authenticated shared process. The SQL benchmark counts distinct stored vectors, not just cache entries. It records one and five concurrent clients, exact/ANN results, model startup, first-client latency and query plans. Full data: [benchmark.json](verification/benchmark.json); command: `python scripts/run_benchmark.py`.

| Chunks | Documents | Distinct vectors | Reused embeddings | Ingestion chunks/s | Exact warm p95 ms, 1 / 5 clients | ANN requested warm p95 ms, 1 / 5 | ANN top-10 overlap vs exact |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 100 | 901 | 99 | 416.1 | 41 / 91 | 43 / 93 | 1.000 |
| 10,000 | 1,000 | 9,001 | 999 | 408.3 | 127 / 179 | 125 / 176 | 0.995 |
| 50,000 | 5,000 | 45,001 | 4,999 | 316.2 | 803 / 1531 | 476 / 1176 | 1.000 |

All final known-target document hit@10 values were **1.0**. This is a small synthetic identifier-query workload, not a general relevance evaluation. Actual HNSW plans were observed at 10,000 and 50,000 chunks; PostgreSQL chose an exact scan for the 1,000-chunk ANN-requested case. ANN stays disabled by default. [pgvector's filtering/indexing guidance](https://github.com/pgvector/pgvector#filtering) informed exact eligible retrieval for source/history filters and the eligible fallback after ANN candidate exhaustion.

The benchmark measures batched embedding plus cache/chunk/projection insertion and HNSW maintenance. It excludes HTTP/browser capture, document extraction and per-job worker orchestration; it is not an end-to-end crawling capacity claim. Incremental worker embedding reuse and interrupted publication are covered by separate regression tests.

New shared-model process startup was **4.08 seconds**. First-client retrieval was **41 / 137 / 1,173 ms** for 1k / 10k / 50k. This starts a fresh client after ingestion; the OS/database caches were **not** flushed. True OS/database-cold-cache latency remains untested.

At 50k, PostgreSQL database size was approximately **339 MiB**, the benchmark harness process peak RSS approximately **127 MiB**, and the largest child process peak across shared embeddings/benchmark was approximately **558 MiB** (a maximum, not their sum). A separate post-run Docker sample was 157.7 MiB and is not a database peak measurement. These figures exclude the local answer server and do not establish total deployment memory or larger-corpus capacity.

## Failures found and resolved

- Old default-demo and schema-v2 assertions were reconciled with explicit demo exclusion and schema v3, while strengthening positive/history retrieval assertions against empty results.
- ISO dates were being classified as numbers; discovery now classifies dates first. Table fingerprints now ignore irrelevant formatting and bind normalized cells to stable labels/headers.
- Setup scope/latest-period controls and tracked-history routing were disconnected. They now map to the actual backend contracts; failed redirected captures warn the monitor for the original requested page.
- PostgreSQL reindexing could delete chunks still referenced by its projection; dependent projection rows are replaced transactionally. Synchronous compatibility publication also populates the projection.
- Initial benchmark rank fusion rewarded generic dense candidates as lexical hits. Corrected candidate membership and rank fusion restored known-target quality; final timings above replace preliminary faster measurements from the defective ranker.
- Windows CI exposed unclosed SQLite snapshot handles during backup cleanup. Connections now close explicitly and snapshot reads do not leave pooled file handles open. The corrected Windows run passes.
- CI installed Chromium into a different cache than tests inspected; matching paths now exercise the browser tests rather than skipping them.

## Untested / remaining operating checks

- Fresh Windows desktop Docker/WSL installation, native full-model setup and complete Windows PostgreSQL/GUI deployment need a Windows device rehearsal. Windows CI is evidence for its automated Python/SQLite/Chromium paths only.
- Native Linux answer-model runtime setup, Windows ARM64, authenticated sites, multi-user/public hosting and automatic structured PDF mapping are outside the verified configuration.
- True cold OS/database caches, total deployment peak memory, sustained long-duration capture-worker throughput at the three corpus sizes, diverse human-labelled relevance datasets and capacity beyond 50,000 chunks were not measured. No results are extrapolated to those cases.
- The app updates while its services run; no monitoring after device/service shutdown is claimed.

## Delivery status

Settings/sample removal follow-up (2026-10-18): the application now has four navigation screens. Removed the Settings page, Demo & Testing/diagnostic components and CSS, sample-session REST endpoints and CLI seeding command, bundled portal, legacy static UI, archived v1 demo and dedicated demo-validation scripts. `run.py` no longer starts or reserves a portal port. Normal status, chat, search, source editing, history, monitoring, MCP and transfer interfaces remain available. Automated headless fixtures live only under `tests/support` and require explicit injected transports; source configuration cannot enable private-network access. Legacy schema metadata and backup handling remain solely for lossless restoration of existing evidence and records.

Verification after removal: **134 passed, 3 profile-specific skips** in the combined SQLite/PostgreSQL suite, production frontend/compile checks passed, and PostgreSQL browser acceptance passed both with models stopped and with native Qwen/MiniLM enabled. The browser check asserts removed endpoints return 404, Settings is absent, and exercises automatic setup, SSE/polling, HTTP failure/recovery, desktop/390px keyboard navigation, browser-selected extraction and immutable citations. Backup/restore includes populated legacy session metadata, chats and capture hashes. On the running installation, two retired sample sources were disabled; version, chat, capture and observation counts were unchanged. The app was restarted, all core services reported ready, no demo route appeared in OpenAPI and port 8080 was closed. Existing regular sources were preserved.

Interface cleanup follow-up (2026-10-18): removed the header actions (search/shortcut badge, update indicator and icon controls), wordmark icon, workspace summary card and sidebar evidence card. The production frontend build passed. Live browser inspection confirmed all marked elements were removed; isolated PostgreSQL browser acceptance passed automatic setup, scheduled SSE updates, polling without a status label, failure/recovery, 390px keyboard navigation and monitoring after tab closure.

Automatic setup follow-up (2026-10-18): entering a URL and monitoring instructions now supports **Start automatically**, which plans and validates extraction, activates the saved draft, and opens the generated dashboard. Discovery covers common sibling labels, inline labelled numbers, product prices and specification tables; numeric requests cannot activate a heading alone. Clear label matches work without AI, with local-model selection as a fallback. If HTML has no usable match, setup tries restricted Chromium capture; it does not grant additional resource origins. Cards, tables and update lists follow the validated field types. Optional preview/edit controls remain available.

Verification for this follow-up: **132 passed, 3 skipped** in the full SQLite/PostgreSQL suite; **19 launcher/chat tests passed** after the restart fix. Actual PostgreSQL browser acceptance passed with models stopped and with native Qwen/MiniLM enabled, covering automatic setup, scheduled SSE updates, failure/recovery, polling, keyboard/narrow layouts and immutable evidence. The model-enabled run also demonstrated automatic Chromium selection for a JavaScript-only price. A public Books to Scrape product page returned HTTP 200 and a valid automatically extracted price. These checks do not establish successful extraction from arbitrary sites or from the inaccessible Polymarket URL. The local app was restarted and all runtime services reported ready. Setup now handles POSIX restart sockets, and SIGTERM reaches the launcher's owned-service cleanup.

Extraction timeout follow-up (2026-10-18): all **84 applicable pinned Python dependencies** matched the installed environment; `pip check` passed. Runtime readiness reported PostgreSQL, scheduler/capture/index workers, shared embeddings and local chat ready, with Chromium installed. The supplied Polymarket event URL failed before extraction: both resolved IPv4 and IPv6 destinations timed out on direct connections, including the required robots.txt fetch. The same Parity fetcher retrieved `https://example.org/` with HTTP 200. This establishes a site/network reachability failure on this device; it does not establish the reason for the failure or successful Polymarket extraction. Fetch errors now explain the website/network boundary, and failed TLS connections close their sockets. Three focused timeout/cleanup regressions passed.

Chat repair follow-up (2026-10-18): a repeated macOS runtime installation had overwritten the mapped `llama-server` executable in place. macOS terminated subsequent launches with `CODESIGNING / Taskgated Invalid Signature` before logging. Installing identical bytes on a fresh inode restored startup. Setup now replaces extracted runtime files atomically and probes `--version`; chat errors distinguish stopped, slow, loading, credential and invalid-response cases. On this Mac, setup was rerun while the repaired model was serving: the existing server remained healthy and the newly installed executable launched successfully. The running application's `/api/chat/test` returned HTTP 200/ready, and an isolated fixture question produced the correct deadline with an immutable citation using the actual local Qwen model. Follow-up deterministic suite: **86 passed, 3 PostgreSQL-only skips**, including **18 chat/startup tests**. No user source/chat records were changed by the verification. Windows runtime installation was not rerun for this follow-up.

Source and prebuilt assets are on `development/parity-v2-device-integration` in the fork, with [upstream pull request #1](https://github.com/yajask-maker/parity/pull/1). A versioned source ZIP and SHA-256 manifest are generated in `outputs/` from the final committed source; `BUILD_INFO.json` identifies that commit. Read [the operating guide](OPERATING_GUIDE.md) and [presentation walkthrough](PRESENTATION_WALKTHROUGH.md) before a demonstration. The final PR and CI links are recorded in `IMPLEMENTATION_STATUS.md`.
