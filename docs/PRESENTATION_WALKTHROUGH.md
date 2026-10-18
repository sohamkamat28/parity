# Parity 2.0 presentation walkthrough

Use the current verification report, not v1 reports, to describe what has been demonstrated. Keep the launcher visible on the device. Do not present a development checkpoint as an independently certified production release.

## Before the walkthrough

- Run setup and launch the PostgreSQL profile. In Settings → System status, inspect database, monitoring, rendering, embedding, indexing and chat separately. A missing model can coexist with working monitoring.
- Use a public page you are allowed to fetch, or the clearly labelled synthetic fixtures below. Never use personal installation data for a demonstration.
- For a repeatable complete rehearsal, run `python scripts/browser_acceptance.py`; use `--with-models` to include native free chat. The script owns a disposable database and stops its owned services when finished. Reports go to `docs/verification/`; screenshots/data remain ignored under `outputs/runtime/`.

## 1. Set up reviewed monitoring

Open Sources → Start monitoring. Enter a public URL and a clear name, then describe specific fields. Show the detected candidates and their actual values. Review the raw text, normalized unit, reporting period and location. Show that zero remains zero, and that a missing selector must be repaired or removed before activation.

Demonstrate manual selection with AI unavailable. If using a table cell, explicitly select fixed/latest period and the newest-column position. Show Advanced settings only when explaining rendering, selectors or resource permissions. At Scope & schedule, explain the default: this page, one document, zero link depth, 15 minutes and an immediate baseline. Existing source schedules are preserved.

## 2. Read the dashboard

Select All sources or one source. Explain Last checked, Last verified, Last changed and Next check separately. Pin a value, reorder/hide a widget, then reload to show that layout persists.

For synthetic financial-style values, explicitly say they are test data. Show the unit and reporting period, the previous comparable value, table cell highlights and linked announcements. Open View evidence to inspect the immutable capture and extraction location. Open View history to inspect collected observations and a numeric chart; do not imply observations exist between checks.

## 3. Observe an automatic update

Change a controlled fixture and wait for the next scheduled check. Do not ask chat and do not click Check now. Show the dashboard change and stored evidence. Then change an unrelated footer: verification advances without a field-change event.

The automated browser rehearsal demonstrates this using the synthetic `/en/metrics` fixture. It also blocks SSE to verify polling fallback and closes the browser tab to prove worker monitoring continues. Test sources remain excluded from normal views until explicitly included.

## 4. Show failure and recovery

Explain a controlled HTTP or missing-field failure. The previous valid value and its verification time remain visible with a warning; a failed attempt is not a new measurement. Open attention/repair controls. Restore the source or revise a reviewed rule, then show recovery and the retained history.

An announcement disappearing from a limited listing means “no longer listed,” not confirmed deletion. Document availability confirmations and structured list membership are distinct histories.

## 5. Investigate with local chat

Ask a specific question about a monitored value or a current document. Open its citation. For a comparable numeric change, explain that the server calculates the difference/percentage using immutable operands with matching units and periods. Zero-denominator percentages are undefined.

Select a historical time and ask again; the request performs fresh historical retrieval. Show that an older document cannot be substituted as current while the newest version awaits indexing. Explain the Search index updating message.

Default chat is free and local: Qwen selects supporting evidence and the server constructs the cited answer. Optional OpenAI configuration is separate and is not needed for the walkthrough. Demonstration sources require explicit source selection for retrieval tests.

## 6. Explain operating boundaries and preservation

Show the native services and persistent PostgreSQL volume. Monitoring continues while those services run, including with the browser closed. It stops if the laptop sleeps/shuts down or the services stop. GitHub provides source/CI; it does not run ongoing monitoring.

Show backup verification output and the explicit migration command with a source installation path. Explain that the original SQLite file is retained and that restore requires empty destinations. Avoid showing `.env`, access tokens or raw launch logs.

## 7. Present measured results accurately

Use the exact tables in `docs/VERIFICATION_REPORT.md` and `docs/verification/benchmark.json`. State the device, corpus, real vector counts, embedding reuse, one/five clients and measured ingestion scope. Distinguish first-client measurements from untested OS/database-cold cache behavior. Approximation remains opt-in; one synthetic corpus does not establish general capacity or retrieval quality.

Conclude the demonstration by showing remaining untested Windows deployment checks and the pull request/source ZIP, rather than claiming unmeasured capacity or continuous cloud monitoring.
