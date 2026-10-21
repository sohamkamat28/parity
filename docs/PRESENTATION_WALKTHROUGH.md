# Parity 2.0 presentation walkthrough

Use the current verification report to describe what has been demonstrated. Keep the launcher visible on the device. Do not present a development checkpoint as an independently certified production release.

## Before the walkthrough

- Run setup and launch the PostgreSQL profile. Through `GET /api/runtime`, inspect database, monitoring, rendering, embedding, indexing and chat separately. A missing model can coexist with working monitoring.
- Use a public page you are allowed to fetch, or the clearly labelled synthetic fixtures below. Never use personal installation data for a demonstration.
- For a repeatable complete rehearsal, run `python scripts/browser_acceptance.py`; use `--with-models` to include native free chat. The script owns a disposable database and stops its owned services when finished. Reports go to `docs/verification/`; screenshots/data remain ignored under `outputs/runtime/`.

## 1. Set up reviewed monitoring

Open Sources → Start monitoring. Enter a public URL and a clear name, then describe specific fields. Show the detected candidates and their actual values. Review the raw text, normalized unit, reporting period and location. Show that zero remains zero, and that a missing selector must be repaired or removed before activation.

Choose Check every beside the instructions (seconds, minutes, hours or days), then click Start automatically. Show the dashboard without editing selectors, fields, rendering or widget types. Explain that Parity validates the values internally and shows compact values, tables and dated update lists based on their types. Repeat with AI unavailable to demonstrate deterministic detection. For optional customization, use Preview extraction or edit saved rules; latest-period selection remains explicit. New sources use one page, zero link depth and a 15-minute default schedule, which is editable before starting; existing schedules are preserved.

## 2. Read the dashboard

Use the dashboard search to find a source, field or calculation. Clear it to show all sources. Click the source name to explain its schedule and last/next check; click a field metric for verification/change timestamps.

Start with the clean dashboard: each panel has a source name, website link and refresh icon. Shared metric strips show labels above prominent values with fine vertical dividers. Source calculations follow below the tracked information. On narrow screens, strips use two columns. Click a metric for its evidence, tables or announcements. Use **View history** for collected observations and **Calculation history** inside calculated evidence for earlier formula evaluations. Show that search finds source, field and calculated-result names without selectors. For synthetic fixtures, clearly identify the values as test data. Graphs, range controls, aggregate strips and dashboard arrangement remain absent.

## 3. Observe an automatic update

Change a controlled fixture and wait for the next scheduled check. Do not ask chat and do not click Check now. Show the dashboard change and stored evidence. Then change an unrelated footer: verification advances without a field-change event.

The automated browser rehearsal demonstrates this using the synthetic `/en/metrics` fixture. It also blocks SSE to verify polling fallback and closes the browser tab to prove worker monitoring continues. The fixture runs only inside the isolated acceptance database, outside the application launcher.

## 4. Show failure and recovery

Explain a controlled HTTP or missing-field failure. The previous valid value and its verification time remain visible with a warning; a failed attempt is not a new measurement. Open attention/repair controls. Restore the source or revise a reviewed rule, then show recovery and the retained history.

An announcement disappearing from a limited listing means “no longer listed,” not confirmed deletion. Document availability confirmations and structured list membership are distinct histories.

## 5. Investigate with local chat

Ask a specific question about a monitored value or a current document. Open its citation. For a comparable numeric change, explain that the server calculates the difference/percentage using immutable operands with matching units and periods. Zero-denominator percentages are undefined.

Select a historical time and ask again; the request performs fresh historical retrieval. Show that an older document cannot be substituted as current while the newest version awaits indexing. Explain the Search index updating message.

Default chat is free and local: Qwen selects supporting evidence and the server constructs the cited answer. Optional OpenAI configuration is separate and is not needed for the walkthrough. Use an explicit source selection to compare answers from different websites.

## 6. Explain operating boundaries and preservation

Show the native services and persistent PostgreSQL volume. Monitoring continues while those services run, including with the browser closed. It stops if the laptop sleeps/shuts down or the services stop. GitHub provides source/CI; it does not run ongoing monitoring.

Show backup verification output and the explicit migration command with a source installation path. Explain that the original SQLite file is retained and that restore requires empty destinations. Avoid showing `.env`, access tokens or raw launch logs.

## 7. Present measured results accurately

Use the exact tables in `docs/VERIFICATION_REPORT.md` and `docs/verification/benchmark.json`. State the device, corpus, real vector counts, embedding reuse, one/five clients and measured ingestion scope. Distinguish first-client measurements from untested OS/database-cold cache behavior. Approximation remains opt-in; one synthetic corpus does not establish general capacity or retrieval quality.

Conclude the demonstration by showing remaining untested Windows deployment checks and the pull request/source ZIP, rather than claiming unmeasured capacity or continuous cloud monitoring.

## Remove and restore

From Sources, remove a disposable source using the confirmation. Show that it disappears from the dashboard and current retrieval. Open Show → Removed sources; inspect retained documents/history and restore it. Explain that monitoring remains paused until explicitly resumed. The automated browser rehearsal performs this with isolated synthetic data.

## Calculations that answer a practical question

Use two supplier sources or a dated metal-rate page with actual accessible values. Supply your own required quantities and budget, so the demonstration answers a question the source page does not answer for that order. State whether prices are per gram, ten grams, kilogram or item. Publication sessions and dates must agree. Do not describe AM/PM rates as continuously updating ticks.

1. Enter instructions including quantities and the budget; show any field/unit clarification. Activate the validated plan.
2. Show total cost and remaining amount beside the source inputs; click the total metric for the supplied budget and calculation evidence.
3. Open **How this was calculated** and trace quantities, formula revision and exact source captures.
4. Change a supplied quantity in the visual editor. Show the new result and retained earlier formula evidence.
5. Show a real threshold alert and acknowledgement. Use controlled fixtures for predictable failure/recovery; identify them as fixtures.
6. Ask Parity about the calculated result and inspect its calculation citation.

Calculations and scheduled checks continue with local models stopped. Webhooks require a destination you configured; no public recipient is needed for the classroom demonstration. Never present simulated price changes as live publisher updates.
