# Parity 1.0 — Windows demonstration verification

Verified on 15–16 October 2026 on this Windows x64 laptop with Python **3.14.7**, SQLite, CPU MiniLM and CPU Qwen. The completed release is the local demonstration specified in the implementation plan, with **free local cited chat** replacing the paid default at the user's request.

## Results

| Check | Actual result |
|---|---|
| Automated regression suite | **45 passed in 76.01 seconds**, including the original lifecycle coverage |
| React/TypeScript production build | Passed type checking and Vite build; compiled assets and fonts included |
| Complete Windows setup | Passed dependency installation, 384-dimensional MiniLM warm-up, matching Chromium installation, and verified local model/runtime setup; rerun also passed |
| Live acceptance scenarios | **14 of 14 passed**, using real MiniLM, real Chromium, local model inference, HTTP APIs and SQLite |
| MCP | Actual SDK stdio initialization, discovery and successful calls to **all five tools** |
| Public website checks | Successful static capture of `https://quotes.toscrape.com/` and browser capture of `https://quotes.toscrape.com/js/` |
| Existing database upgrade | Migrated a copy to schema v2 without changing existing table row counts; original installation untouched |
| Browser verification | Desktop 1440 × 1000 and narrow 390 × 844; evidence, citations, navigation, keyboard shortcuts, reduced motion and fresh demo creation exercised |
| Extracted release smoke check | ZIP extracted into a separate folder; FastAPI served the bundled HTML, JavaScript and CSS against a fresh database (lexical embedder for this packaging check) |
| Workspace convenience launcher | `Launch_Parity.cmd --no-browser` started all three services; real MiniLM ready, Chromium installed, local provider selected, and separate presentation database empty and ready |

The copied recovered database had **zero rows** in its core tables. Preservation of a populated pre-migration history was separately exercised by the synthetic upgrade regression test. This distinction matters: the copied database alone does not prove preservation of populated customer data.

## Measured live acceptance

Times below are observed scenario durations, not performance guarantees. Shared vector caches can legitimately reuse embeddings across fresh demonstration sources. Chat was retested after the final local output constraints; the consolidated results retain the independent lifecycle checks from the complete run.

| Scenario | Seconds | Observed behavior |
|---|---:|---|
| Runtime readiness | 0.01 | Database, MiniLM and worker ready; Chromium installed; local chat configured |
| Baseline with real MiniLM | 0.54 | Three original notices indexed and searchable |
| Original cited answer | 4.13 | Honours deadline **20 August 2026**, immutable v1 citation |
| Deadline and exact diff | 0.85 | v2 published with **28 August 2026** and NOC requirement; exact diff reports four added lines and one removed line |
| Follow-up cited answer | 6.06 | Fresh v2 evidence selected with revised deadline and NOC requirement |
| Historical retrieval and chat | 2.73 | As-of query returned original deadline with v1 citation |
| Footer-only mutation | 0.43 | No content version and no new embedding vectors |
| PDF publication and revision | 3.32 | Searchable PDF evidence with preserved versions |
| JavaScript JSON-only mutation | 11.85 | Unchanged HTML shell re-rendered; changed JSON produced a new searchable version |
| Missing, deletion and restoration | 8.43 | Initial missing observation removed the page from current retrieval while preserving history; three separate observations confirmed deletion; restoration retained the availability gap |
| Transient failure | 2.12 | Previous evidence retained; successful verification timestamp did not advance |
| Scheduled polling | 15.11 | Scheduler detected a fixture update without a manual crawl |
| Five-tool MCP protocol | 3.41 | All five tool calls validated over real stdio |
| Public static and rendered pages | 18.83 | Both sources completed successfully with one indexed document each |

The measured MCP protocol operation itself took 2,874 ms. Tool calls took: `search_docs` 159 ms, `get_page` 18 ms, `get_page_history` 21 ms, `diff_versions` 19 ms, and `list_recent_changes` 24 ms. Diagnostics uses an authenticated loopback bridge so the MCP subprocess shares the already-loaded semantic engine. Standalone MCP remains available.

## What the tests cover

Regression coverage includes lifecycle/versioning, current and historical retrieval, deletion/restoration intervals, selector/configuration signatures, migrations, source validation, browser request restrictions and capture failures, subprocess timeouts, citation validation, foreign evidence rejection, provider failures, local excerpt selection, follow-up context, startup configuration and occupied ports, CLI imports, and isolated repeatable demo sessions.

Browser capture is bounded to 45 seconds, 60 resource requests and 25 MiB. Network requests are fulfilled through the validated address-pinned fetcher, including redirect checks; direct network fallback is denied. Resources have a separate origin allowlist from document crawl scope. Service workers, WebSockets, popups, frames and downloads are blocked. Capture failure retains the prior complete evidence. These are tested implementation controls, not a formal security audit.

Browser inspection covered all six screens. The history panel showed side-by-side v1/v2 content and the exact diff; citation clicks opened the cited immutable version. Ctrl+K focused the command search, Alt+1–6 switched screens, Ctrl+Enter submitted a question, and Escape closed dialogs. The interface motion switch produced `animation-name: none` on graph links. OS reduced-motion CSS is included; changing the operating-system preference was not separately automated. Narrow navigation, chat layout and Demo Lab were inspected without horizontal document overflow. Desktop and narrow screenshots accompany this release.

The final narrow-screen baseline action returned three created documents and displayed its successful observed result. The Diagnostics controls also passed real protocol checks from the UI: five MCP tools passed, and the local answer model connection completed in 1,472 ms. No browser console errors were recorded in the final session.

## Chat and network boundaries

Default chat uses **Qwen2.5-1.5B-Instruct Q4_K_M** through pinned llama.cpp on this machine. The model chooses relevant evidence passages; the server returns their exact text and builds numbered immutable citation snapshots. This intentionally constrained answer format can quote more text than a larger conversational model and is not a general-purpose assistant. Semantic search remains usable when the answer provider fails.

The optional OpenAI Responses/structured-output integration remains implemented and has mocked provider/error coverage. A real request with the locally configured key returned **HTTP 429, `credit_balance_exhausted`**. Funded OpenAI answer generation therefore **did not pass live acceptance** and is not required for the free release. No API credits were purchased. The API key is excluded from delivery.

The two successful public pages demonstrate actual internet capture; they do not establish universal website compatibility. Authentication, hostile anti-bot systems, OCR, customer accounts, institutional integrations, public hosting, PostgreSQL runtime and production-scale performance are outside this verified release.

## Reproduction and packaging

Use `setup.bat`, then `start.bat`. The frontend is prebuilt; Node is needed only for development. See `QUICK_START.md` and `PRESENTATION_WALKTHROUGH.md`. The workspace convenience launcher uses a separate persistent presentation database; the original installation and verification data are preserved.

Run the automated suite with `.venv\Scripts\python.exe -m pytest tests -q`. The included `scripts/verify_live.py` exercises the live service with configured local test access tokens and creates new namespaced fixture sessions. Its public-page checks require internet access. Sanitized measured results and the final test/build output are included under `verification/`.

The source archive includes Python code, React/TypeScript source, prebuilt frontend, dependency locks, tests, Windows scripts, documentation and license notices. It excludes `.env`, personal databases, logs, virtual environments, node_modules, model/browser caches and credentials. Runtime downloads are pinned and verified during setup. Screenshots show synthetic verification data; new presentations start in their own namespace.
