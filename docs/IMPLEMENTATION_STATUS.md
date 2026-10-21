# Parity 2.0 implementation status

Updated 21 October 2026. This is a tested development candidate, with remaining platform/measurement limits recorded explicitly.

## Dashboard metric strips — 21 October 2026

The dashboard now follows the latest reference: source-grouped connected metric strips, muted labels above prominent values, smaller unit labels and vertical dividers. Calculations follow the extracted metrics in the same visual style. Narrow screens use two columns within each shared strip. Individual bento cards and the earlier ledger layout are superseded. Existing source controls, immutable evidence/history, search and updates are retained.

Change badges use the backend's comparable observation pair; no prior value means no percentage, stale results suppress badges, percentage-point differences stay distinct, and previous-zero comparisons use absolute changes. Budget state is labeled against the supplied budget rather than presented as a historical percentage.

## Application theme refresh — 21 October 2026

The application now uses an Agno-inspired light visual language: white surfaces, charcoal text, coral actions, consistent typography and restrained dividers. The dashboard uses flat source-grouped field and calculation ledgers instead of individual cards. Sources, changes/history, chat, setup, calculation, notification and evidence dialogs share the same tokens. Existing source schedules, identifiers, observations and formulas are unchanged; no schema migration or new frontend dependency is required.

The production build and both PostgreSQL browser acceptance rehearsals pass, including automatic setup, schedule persistence, zero/table/list values, SSE/polling, failure recovery, source removal/restoration, calculated evidence, alerts and narrow keyboard layouts. All four screens and the setup/evidence dialogs were reviewed visually. See [the frontend design guide](FRONTEND_DESIGN.md). The earlier tile layout below is superseded.

## Earlier dashboard wireframe implementation — 21 October 2026

The latest dashboard follows the supplied sketch: full-width server-backed search, source name/link and icon refresh, a three-column field tile grid alongside two-column calculations at desktop width, and two-column/stacked grids on narrow screens. Source schedules/management, field history/evidence and calculation controls are accessed by clicking the relevant name or tile. Healthy-state badges, repeated metadata, totals and the old source dropdown no longer crowd the overview. Actionable notifications remain visible; retained alerts/deliveries open separately. Search runs against metadata before bounded pagination and accepts literal queries up to 200 characters. No schema migration, model calls or changed extraction rules are required. The combined suite passed **332 tests with 4 intentional skips**, and both updated PostgreSQL browser acceptance flows passed with models stopped.

## Dashboard simplification — 21 October 2026

The dashboard now uses compact source-grouped field rows with calculations alongside on wide screens and stacked on narrow screens. Graphs, graph-range controls and dashboard arrangement are removed, including field-history graphs and calculated-result graphs. The frontend no longer requests series or layout preferences. Observation and calculation histories remain available on demand with immutable evidence, while backend series/layout contracts remain compatible. Shared calculation status and management controls appear once per automation; acknowledged alerts start collapsed. No database migration or monitor changes are required.

## Calculation automation follow-up — 21 October 2026

General cross-source calculations, a visual builder, deterministic instruction templates and validated local-model proposals are implemented. Quantities, dimensional units/price denominators, table/list aggregates, compatible history, formula revisions and immutable input evidence feed calculated dashboard values, trends, budget comparisons and ranked inputs. Missing details require clarification; unsupported instruction clauses are not silently omitted.

Schema 5 adds durable evaluation and notification queues, lease/generation fencing, current-value eligibility, conditional/sustained rules, cooldowns, in-app alert acknowledgement/recovery and explicitly configured public-HTTPS webhooks. Paused/failed/removed/overdue dependencies block notifications and fresh answers. Private connections stay outside database backups; restores disable pending outbound deliveries. Source setup and calculations activate atomically. Existing REST, CLI and all five MCP contracts remain covered.

The final local combined suite passed **330 tests with 4 intentional profile skips**. Production build, dependency checks, browser acceptance with models stopped and enabled, and actual free Qwen calculation citations passed. The real IBJA page passed a disposable PostgreSQL rehearsal after explicit PM-session and price-denominator choices, reusing one capture. The local schema-4-to-5 upgrade verified all 30 original data-table hashes, 1,419 capture/artifact hashes and the legacy auxiliary SQLite logical contents. See [the automation guide](AUTOMATIONS.md) and [latest verification](VERIFICATION_REPORT.md#automatic-calculations-rules-and-alerts--21-october-2026).

The finite synthetic automation benchmark processed 240 evaluations for 20 automations, with measured throughput and dashboard/series query counts in [automation-benchmark.json](verification/automation-benchmark.json). It does not establish sustained deployment capacity. A fresh physical Windows Docker/native-model/GUI installation and a real external webhook receiver remain untested; deterministic delivery and Windows CI checks are separate.

## Earlier implemented monitoring checkpoint


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
