# Parity 2.0 verification report

## Application theme refresh — 21 October 2026

- Production TypeScript/Vite build: passed, with bundled fonts and no added dependency.
- PostgreSQL monitoring browser rehearsal with models stopped: passed; [machine-readable results](verification/browser-no-models.json).
- PostgreSQL automation browser rehearsal with models stopped: passed; [machine-readable results](verification/automation-browser.json).
- Visual review: light theme across Dashboard, Sources, Changes & History, Ask Parity, source setup and calculation dialogs. Flat dashboard name/value rows replace the card grid. Existing histories, sources and calculations were preserved.
- The browser rehearsals use isolated disposable PostgreSQL databases, exercise keyboard/narrow/reduced-motion behavior, preserve open evidence during updates, and report zero chart-series requests and browser JavaScript errors.
- This presentation-only change does not migrate data or modify Python behavior. Earlier backend and platform results below remain dated evidence; a fresh physical Windows GUI/model/Docker installation was not repeated for this theme change.

See [frontend design](FRONTEND_DESIGN.md) for tokens and the layout contract.
The [theme review record](verification/frontend-theme.json) records the four-screen narrow review and measured foundation text contrast ratios.


Latest calculation follow-up verified on 21 October 2026; see the final section. Earlier sections below record the 18–19 October monitoring checkpoints from the development branch. Upstream was fetched again and remained at `a344436cd8e7a292a080f3ba3a2b38da6e6eba00`. This report concerns v2; historical v1 reports are not acceptance evidence.

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

The first removal CI run exposed a timing assumption in the existing Windows lease-heartbeat test. Its subsecond wall-clock deadline was replaced with explicit clock advancement and two required renewals by the real heartbeat thread, preserving the warmup-before-claim, ownership and cleanup assertions. The focused check passed locally; final cross-platform CI is recorded in the pull request.

Interface cleanup follow-up (2026-10-18): removed the header actions (search/shortcut badge, update indicator and icon controls), wordmark icon, workspace summary card and sidebar evidence card. The production frontend build passed. Live browser inspection confirmed all marked elements were removed; isolated PostgreSQL browser acceptance passed automatic setup, scheduled SSE updates, polling without a status label, failure/recovery, 390px keyboard navigation and monitoring after tab closure.

Automatic setup follow-up (2026-10-18): entering a URL and monitoring instructions now supports **Start automatically**, which plans and validates extraction, activates the saved draft, and opens the generated dashboard. Discovery covers common sibling labels, inline labelled numbers, product prices and specification tables; numeric requests cannot activate a heading alone. Clear label matches work without AI, with local-model selection as a fallback. If HTML has no usable match, setup tries restricted Chromium capture; it does not grant additional resource origins. Cards, tables and update lists follow the validated field types. Optional preview/edit controls remain available.

Verification for this follow-up: **132 passed, 3 skipped** in the full SQLite/PostgreSQL suite; **19 launcher/chat tests passed** after the restart fix. Actual PostgreSQL browser acceptance passed with models stopped and with native Qwen/MiniLM enabled, covering automatic setup, scheduled SSE updates, failure/recovery, polling, keyboard/narrow layouts and immutable evidence. The model-enabled run also demonstrated automatic Chromium selection for a JavaScript-only price. A public Books to Scrape product page returned HTTP 200 and a valid automatically extracted price. These checks do not establish successful extraction from arbitrary sites or from the inaccessible Polymarket URL. The local app was restarted and all runtime services reported ready. Setup now handles POSIX restart sockets, and SIGTERM reaches the launcher's owned-service cleanup.

Extraction timeout follow-up (2026-10-18): all **84 applicable pinned Python dependencies** matched the installed environment; `pip check` passed. Runtime readiness reported PostgreSQL, scheduler/capture/index workers, shared embeddings and local chat ready, with Chromium installed. The supplied Polymarket event URL failed before extraction: both resolved IPv4 and IPv6 destinations timed out on direct connections, including the required robots.txt fetch. The same Parity fetcher retrieved `https://example.org/` with HTTP 200. This establishes a site/network reachability failure on this device; it does not establish the reason for the failure or successful Polymarket extraction. Fetch errors now explain the website/network boundary, and failed TLS connections close their sockets. Three focused timeout/cleanup regressions passed.

Chat repair follow-up (2026-10-18): a repeated macOS runtime installation had overwritten the mapped `llama-server` executable in place. macOS terminated subsequent launches with `CODESIGNING / Taskgated Invalid Signature` before logging. Installing identical bytes on a fresh inode restored startup. Setup now replaces extracted runtime files atomically and probes `--version`; chat errors distinguish stopped, slow, loading, credential and invalid-response cases. On this Mac, setup was rerun while the repaired model was serving: the existing server remained healthy and the newly installed executable launched successfully. The running application's `/api/chat/test` returned HTTP 200/ready, and an isolated fixture question produced the correct deadline with an immutable citation using the actual local Qwen model. Follow-up deterministic suite: **86 passed, 3 PostgreSQL-only skips**, including **18 chat/startup tests**. No user source/chat records were changed by the verification. Windows runtime installation was not rerun for this follow-up.

Source and prebuilt assets are on `development/parity-v2-device-integration` in the fork, with [upstream pull request #1](https://github.com/yajask-maker/parity/pull/1). A versioned source ZIP and SHA-256 manifest are generated in `outputs/` from the final committed source; `BUILD_INFO.json` identifies that commit. Read [the operating guide](OPERATING_GUIDE.md) and [presentation walkthrough](PRESENTATION_WALKTHROUGH.md) before a demonstration. The final PR and CI links are recorded in `IMPLEMENTATION_STATUS.md`.


## Dashboard and reliability follow-up — 19 October 2026

Implemented inline numeric graphs (24 hours / 7 days / 30 days), actual timestamps, baseline points, failed/missed-check gaps, unit/period/revision separation, comparable server-calculated deltas, keyboard evidence links and an accessible observation table. Up to 200 observations remain complete; larger series use bounded time-bucket endpoints/extrema. Visible fields use batches of at most 50 and affected-series refresh after committed events. Open observation tables, evidence, filters and layout survive background updates. Tables and dated announcements retain their existing displays; missing publication dates use persisted first-observed times.

Automatic setup exposes a frequency value and unit before Start automatically (10 seconds–7 days, default 15 minutes). Source removal is reversible: it cancels queued/running captures, fences publication, hides active views and current retrieval, retains histories/citations and restores paused. Source/run/URL lock ordering is consistent; a PostgreSQL race test waits until removal actually overlaps a held claim transaction. Existing source configuration and favicon edits are preserved.

Schema 4 adds nullable `sources.removed_at`, a series index and a hashed-key first-observed lookup. Startup rejects older nonempty schemas with explicit upgrade guidance. `scripts/database.py --upgrade` verifies a new database/capture backup first. Older backups select and verify their original column sets, then reconstruct additive metadata. Populated v3 backup/restore and explicit upgrade pass on both database profiles. The local development upgrade verified all **29 original data tables** against their pre-upgrade hashes and all **30 referenced files** before restarting services. No original capture, observation, chat or citation was rewritten.

Discovery supports accessible labels, semantic HTML price/currency attributes and bounded JSON-LD Product/Offer entities. Entity/property bindings survive JSON array reordering and fail on missing/ambiguous mappings; distinct products need specific instructions even when their prices are equal. Preview/activation reuse one parsed capture. Connection attempts alternate validated IPv4/IPv6 candidates within a ten-second connection/TLS budget; hostname verification and private-network/browser restrictions remain enforced. Permanent access failures stop retrying; Retry-After remains persisted. Missing rendering support is distinct from missing fields, network errors and access blocks. Routine extraction does not call AI or embeddings.

Verification: the combined suite passed **165 tests with 4 intentional profile skips**. The skip cases pass on PostgreSQL; SQLite does not provide equivalent row-lock semantics. Compile checks, pinned dependency compatibility (`pip check`) and the production frontend build passed. PostgreSQL browser rehearsals passed with models stopped and with native Qwen/MiniLM enabled, including graphs, keyboard capture links, frequency persistence, SSE/polling, failure/recovery, tab-closed monitoring, 390px/reduced-motion navigation and remove/restore. The model run produced a cited free local answer. All five actual MCP protocol contracts remain covered by the backend suite. Final CI results are linked on upstream PR #1; the fresh Windows Docker/native-model/GUI device rehearsal remains unperformed.

The public Books to Scrape product URL produced a validated GBP price through static automatic extraction; an example.org text page also extracted successfully. These limited live checks supplement deterministic HTML, structured-data, JavaScript, table/list, HTTP and layout fixtures. They do not establish arbitrary-site coverage. Login-required sites, CAPTCHA/paywall bypass and automatic structured PDF mapping remain outside scope; existing PDF search/citations remain covered.

### Reproducible dashboard comparison

`python scripts/benchmark_dashboard.py` runs the same disposable PostgreSQL corpus against an archived baseline (`d5b6afb`) and the updated source: **40 fields × 500 observations = 20,000 observations**, no models/network. Machine: the documented Apple M4 / 16 GB macOS device, Python 3.14.6 and PostgreSQL/pgvector. Reports: `verification/dashboard-before.json` and `verification/dashboard-after.json`.

| Measurement | Baseline history requests | Batched series |
|---|---:|---:|
| Graph service calls | 40 | 1 |
| Graph SQL queries | 80 | 2 |
| Graph JSON bytes | 4,673,733 | 1,209,665 |
| Warm graph median, five repeats | 151.033 ms | 151.703 ms |
| First graph call | 167.362 ms | 159.349 ms |
| Warm dashboard snapshot median | 9.337 ms | 9.441 ms |
| Setup, one measured activation | 331.302 ms | 187.552 ms |
| Capture fetches during setup | 1 | 1 |

The measured improvement is fewer calls/queries and a smaller payload, with faster setup on this run. Graph server latency was essentially unchanged, slightly higher in the final warm sample; no latency improvement is claimed. The baseline returns its latest 200 rows per field; the new path samples the full requested seven days. First calls are not cold-cache benchmarks: OS/database caches were not flushed. HTTP transport, browser rendering and total deployment memory are excluded. Existing 1k/10k/50k retrieval benchmarks remain separate; these dashboard measurements do not establish crawling capacity.

During development, an old browser assertion became ambiguous because the same number appears in both the main value and the accessible table; the check now targets the main value explicitly and separately verifies the table. Focused regressions also corrected small series being sampled unnecessarily and preserved expanded observation tables through polling. These intermediate failures are resolved in the reported checks.

After the overnight device resume, the existing Screener source encountered a DNS resolution failure. Its previous verified values and immutable captures remain visible with stale warnings; this is an observed network/source failure, not successful fresh extraction. DNS errors now have a distinct actionable classification, and the attention action checks the source rather than asking for selector repair. Database, workers, browser installation, embeddings and local chat remain ready.

## Source-grouped overview follow-up — 19 October 2026

The dashboard now groups enabled fields by website, combining multiple monitors of the same source on the current bounded page. Source headers show the name/domain, field count, schedule, last/next check and monitoring state. Compact values, units, reporting periods, comparable deltas, real observation sparklines and table/list summaries are visible immediately. Field details expand below the compact fields to the full source-section width, retaining full graphs, accessible observation tables, highlighted cells, dated announcements, evidence, history and distinct check/verification/change times. Source warnings consolidate repeated failures. The interface uses plain states (Verified, Overdue, Waiting for check, Needs repair, Check failed) and retains existing pause/edit/source-management controls.

Pinning and reordering remain within each source; saved ordering for sources outside the current filter/page is retained. Hidden fields, source filters, ranges, open observation tables and evidence retain their update behavior. Large installations still use bounded monitor pagination: source counts identify sources shown, paginated groups identify fields shown, and the page explains when more fields are available. A source with many monitors can continue on another page.

Verification uses isolated PostgreSQL data: the browser rehearsal exercises two sources and multiple monitors under one source, compact/default versus expanded views, correct field membership, filters, pinning/hiding/ordering, keyboard details/evidence, history, SSE updates, polling, HTTP failure/recovery, source removal/restore, 390px layout and reduced motion. The local model-enabled rehearsal also produced a cited free Qwen answer. Production TypeScript/Vite builds pass. The final regression and CI records are linked on PR #1. Existing backend suites and scale benchmarks above are the prior integration results; no backend/database schema change or migration is part of this presentation follow-up. Normal monitoring continues on the existing installation, and unrelated favicon edits remain untouched.

## Automatic calculations, rules and alerts — 21 October 2026

The schema-5 calculation layer is implemented, including validated instruction plans, a visual field/formula builder, quantities and budgets, dimensional unit conversion and explicit price denominators, table/list aggregates, comparable historical functions, formula revisions, durable workers, conditional rules, in-app alerts and optional private webhook connections. Source and calculation activation share one transaction. Runtime calculations use Decimal and bounded JSON expression trees, with no AI/embedding calls or generated code execution. Separate automation and notification workers are supervised by the native launcher.

| Check | Actual result |
| --- | --- |
| Final combined SQLite/PostgreSQL backend suite | **330 passed, 4 intentional profile skips**; [JUnit record](verification/automation-backend-junit.xml). Existing lifecycle, release, PDF and all five actual MCP contracts remain included. |
| Build and dependencies | TypeScript/Vite production build, Python compile, `pip check`, whitespace checks and npm audit pass; npm reported zero vulnerabilities. |
| Automation browser acceptance, models stopped | Pass: natural-language threshold, clarification without partial activation, cross-source visual formulas and supplied inputs, zero, revision edits, immutable captures, keyboard graph points, accessible tables, failure/retained results/recovery, SSE/polling, 390px navigation and reduced motion. [Report](verification/automation-browser.json). |
| Automation browser acceptance, native models enabled | Pass, including an actual free Qwen answer with calculated-value and supporting capture citations. [Report](verification/automation-browser-models.json). |
| Existing complete monitoring browser rehearsal | Pass with native Qwen/MiniLM enabled: source-grouped overview, schedules, JS fallback, tab-closed monitoring, field history, PDF/search coverage from backend, removal/restoration and preserved selections/evidence/layout. [Report](verification/browser-models.json). |
| Live public page | IBJA fetched successfully in disposable PostgreSQL with models stopped. Ambiguous AM/PM choices and missing price denominators required explicit answers; all three inputs used the same published PM date. One capture supplied discovery, validation, baseline and the calculated order cost/budget balance. No user installation or external receiver was changed. [Actual inputs/results](verification/automation-public-preview.json). |
| Migration/backup/restore | Populated calculation histories, alerts and evidence survive backup/restore; queued deliveries restore disabled. An additive schema-4-to-5 rehearsal passes, and the explicit local upgrade created a verified backup. All 30 original data tables retained counts/hashes; all 1,419 referenced immutable captures/artifacts retained hashes. Existing auxiliary SQLite contents were compared logically because SQLite backup headers can differ. [Local upgrade record](verification/local-automation-upgrade.json). |
| Notification transport | Deterministic tests pass for public-address checks, DNS rebinding/private destinations, hostname TLS checks, redirect rejection, payload/response limits, secret redaction, HMAC signing, bounded retries/Retry-After, idempotency keys, expired claims, paused/removed/stale dependencies and restored delivery suppression. No real external webhook receiver was contacted. |

The public-page numbers are a recorded publication snapshot, not a claim of real-time market ticks. Its historical publication date remains visible in the calculation inputs. Responsive tables with labelled cells bind to the newest explicitly parsed dated row and its session; missing/duplicate dates or changed column labels fail validation. The instruction compiler requests clarification for richer unsupported clauses instead of quietly dropping fees, budgets or compound conditions. Arbitrary natural-language interpretation and arbitrary-site accessibility are not guaranteed.

The reproducible PostgreSQL fixture benchmark used one price field, 20 automations, 40 outputs, 12 alternating checks and 240 sequential durable evaluations with models stopped. It measured **124.76 evaluations/second** across capture publication and worker processing. Median capture-to-all-20-alerts latency was **162.13 ms**. Loading one or twenty automation summaries used **7 SQL statements** in both cases; warm medians were **5.97 ms** and **7.18 ms**, with response sizes 3,218 and 62,023 bytes. Twenty calculated series used **2 SQL statements**, **9.48 ms**, 81,225 bytes and 260 real plotted points. [Machine-readable workload/results](verification/automation-benchmark.json).

These are local synthetic measurements, not before/after speedup claims, live-network capacity, true cold-cache results or deployment-wide memory/throughput limits. Existing 1k/10k/50k retrieval benchmarks remain their separately scoped evidence; no larger capacity is inferred. GitHub CI runs the backend matrix, PostgreSQL integration, both deterministic browser flows and frontend build/audit without paid credentials. The current run is linked in the pull request. A fresh physical Windows Docker/WSL/native-model/GUI rehearsal remains unperformed.


## Dashboard simplification — 21 October 2026

Removed all frontend numeric/calculate/history graphs, trend ranges, dashboard arrangement controls and the unused chart component. Source groups now show compact value/period rows and an adjacent calculation list on wide screens, stacked on narrow screens. Each automation has one shared status and Manage menu. Details retain units, comparable changes, table cell highlights, dated announcements, exact timestamps and immutable evidence. Calculation history uses the existing paginated evaluation API on demand; acknowledged alerts start collapsed. Series/layout API contracts and stored layout records remain available, but the UI does not request them. No database migration or changes to saved monitor definitions/schedules were made. Unrelated favicon edits remain in the working tree.

Verification on this Mac:

- `npm --prefix frontend run build`: TypeScript and production build passed.
- `.venv/bin/python scripts/test.py --postgres`: **330 passed, 4 intentional profile skips**, 78.10 seconds. Existing lifecycle, search, PDF, migration, worker, calculations and actual five MCP contracts remain covered.
- `.venv/bin/python scripts/browser_acceptance.py`: passed on an isolated PostgreSQL database with models stopped. Automatic setup, zero/currency/table/list values, keyboard evidence/history, SSE, retained open evidence/details, failure/recovery, polling fallback, JavaScript rendering, multiple-source grouping, 390px navigation and remove/restore passed.
- `.venv/bin/python scripts/automation_browser_acceptance.py`: passed on isolated PostgreSQL with models stopped. Instruction clarification, visual building, cross-source zero values, parameter revisions, durable alerts/acknowledgement, nested immutable evidence, paginated calculation history, stale-value recovery, polling and 390px keyboard/reduced-motion checks passed.
- Both browser suites assert **zero `/api/dashboard/series` requests** and absence of charts and the removed arrangement controls. Browser assertions were updated to the approved controls and retained evidence/history behavior; backend series/layout tests were retained.
- Final visual inspection of the existing IBJA installation at desktop and 390px confirmed no charts, no horizontal overflow (383px document width within a 390px viewport), and no browser errors/warnings. A remaining old mobile calculation font/padding override was removed during visual review. Empty monitor pagination controls are omitted.

The broader model-enabled browser results above are earlier checks; local models were not required for these layout acceptance runs. No public-site content was changed, no artificial observations were added, and no external notifications were sent. This frontend change makes no new capacity or latency claim.


## Supplied dashboard wireframe — 21 October 2026

Implemented the supplied source-panel sketch in the existing dark frontend: full-width search, source name and real URL, icon-only Check now, a three-column field tile grid beside two-column calculated tiles on wide screens, and stacked two-column sections on narrow screens. Tiles show names and actual values; clicking opens details/evidence/history. Source schedules and management open from the source name, calculation actions from the calculation tile, and retained alerts/deliveries from Notifications. Healthy-state badges, totals, source dropdown, repeated timestamps/controls and the redundant desktop breadcrumb bar are absent from the overview. No graphs or arrangement controls were reintroduced. Obsolete row-layout CSS was removed.

Search is server-backed, bounded to 200 characters and applied before pagination. It includes source names/URLs, current field definitions and current calculation definitions, retaining the source context. Literal wildcard handling, blank/oversized/no-match queries, removed sources, aggregates and calculation/source association were checked on SQLite and PostgreSQL. Existing source_id/pagination APIs remain valid. Search makes no model or embedding calls and requires no database migration.

- Final TypeScript/Vite production build passed; Python compile and whitespace checks passed.
- `.venv/bin/python scripts/test.py --postgres`: **332 passed, 4 intentional skips**, 69.61 seconds.
- Both updated PostgreSQL browser suites passed with models stopped. They verify keyboard tile activation, nested capture/history dialogs, source/field/calculation search and clearing/no-match states, icon refresh, schedule access, zero values, table/list details, alerts/acknowledgement, formula editing, SSE/polling, stale recovery, source lifecycle and 390px navigation. Both recorded zero series requests and no page errors.
- The existing local installation was restarted without migration; database, monitoring, automation, notification, chat and embedding readiness all reported ready. Existing source fields/parameters/evidence were preserved. Manual search/no-match/recovery and desktop/narrow visual checks passed, with no browser errors/warnings. Narrow browser viewport width was 433 CSS pixels with a 426px document; the isolated browser suites separately exercise an exact 390px viewport. Temporary viewport overrides were reset.

Machine-readable results: [dashboard-wireframe.json](verification/dashboard-wireframe.json), [browser-no-models.json](verification/browser-no-models.json), [automation-browser.json](verification/automation-browser.json). Model-enabled historical acceptance results above remain distinguished from these model-independent runs. No new capacity or latency claim is made.
