# Calculations, rules and alerts

Parity can turn monitored fields into results specific to your work: material costs, supplier comparisons, totals, ratios, budget balances and threshold alerts. Calculations run locally while Parity's services run. They continue with the browser closed and with AI and embedding services stopped.

## Start from instructions

When adding a source, describe both the fields and the outcome. For example:

> Calculate the material cost of 20 grams of 916 gold, 10 grams of 750 gold and 500 grams of silver. Compare with my ₹5 lakh budget and alert me when it exceeds the budget.

Parity previews the page, selects actual extracted fields, and compiles a calculation. It asks for missing quantities, an ambiguous field/date/session, or a price denominator. For example, `INR/10g` means the source price is for ten grams, while `INR/kg` means per kilogram. The calculation cannot start using an assumed denominator. Review AM and PM fields carefully and use a consistent publication date/session. A publication date is different from the time Parity checked the website.

A validated, complete request starts monitoring and its calculation together. An unresolved calculation never silently starts only the source. The saved formula and its inputs remain available for inspection.

Use **Dashboard → Create calculation** to combine already monitored sources. Simple totals, ratios, historical percentage changes and numeric thresholds have deterministic instruction templates. A configured local model can propose additional plans. Every proposal passes the same field, expression and unit checks. Arbitrary natural language is not guaranteed to compile. Requests involving unsupported clauses ask for clarification rather than dropping those clauses.

Choose **Choose fields and build visually** to select source fields, supply quantities or budgets, construct operations and set alert conditions. This is also available without models. No CSS or programming is required. Responsive dated tables with labelled cells can bind to the latest dated row and an explicit AM/PM session; ambiguous date formats require review. Use stable table row choices and exact detected numeric column headers. An ambiguous or missing cell blocks the calculation.

## Operations and displays

- Add, subtract, multiply, divide, total, minimum, maximum, observation average, ratio and percentage change.
- Convert compatible units, such as grams and kilograms. Different currencies require an explicit monitored exchange-rate input with a unit such as `INR/USD`; Parity does not infer an exchange rate.
- Percent values use `%`. Convert them to fractions explicitly before multiplication. Subtracting two percentages produces percentage points (`pp`).
- Aggregate selected structured-table rows/columns, and count repeating-list items by their stable identities.
- Compare with the previous comparable observation or baseline; compute collected-observation window averages/minima/maxima up to 30 days. These are sample averages, not continuous time-weighted averages. Missing checks are never interpolated. A window exceeding 10,000 observations, or a calculation exceeding 50,000 supplied historical samples, requires a shorter range or fewer inputs.
- Use comparisons, AND/OR/NOT and conditional numeric values. Outputs can refer to earlier outputs in the same automation; cycles and references between separate automations are rejected.

Single-source calculations appear as name/value tiles beside their source’s tracked fields. Cross-source results appear under **Calculations & automations**. Click a calculation tile to inspect its immutable formula and inputs; the same dialog provides **Calculation history**, pause/resume, edit and archive. Search the dashboard by source, field or calculation name. The server searches metadata before pagination and keeps the full source context. Graphs, trend ranges and arrangement controls remain removed. All enabled fields and outputs are shown; existing layout API records remain retained for compatibility. Budget context and compatible ranked comparisons remain in calculation evidence.

Select a calculated value tile (accessible name: **How this was calculated**) to inspect the immutable revision, observations, supplied quantities, units and capture links. **Calculation history** within that dialog opens paginated evaluations and their evidence on demand. Editing a quantity, budget or formula creates a new revision. Earlier results remain resolvable; retained stale results open their last successful evidence. New unacknowledged alerts expose a notification icon; **Alerts & deliveries** opens the retained notification records.

## Freshness and repairs

Every required source must be enabled, unpaused, present and successfully verified within its checking interval. The latest extraction attempt must be valid. When a dependency is missing, fails, changes its mapping or becomes overdue, Parity retains the last result with a warning and suppresses condition notifications. It also marks results pending when a newer source observation awaits calculation; chat cannot use that older result as current.

Changed source definitions require repair and a validated calculation revision. A renamed field with the same extraction definition remains compatible. Source unit changes require review. Reporting periods and sessions must align unless **Allow calculations across different reporting periods** is explicitly selected. Choosing that option does not manufacture missing data.

A restored source stays paused until resumed. Calculations depending on it remain blocked until valid current inputs return. Monitoring and calculation workers have separate readiness entries.

## Rules and notification connections

Rules support thresholds, compound conditions, sustained durations, cooldowns and optional recovery notifications. Default behavior:

- Evaluate after input updates and at least every 60 seconds; the scheduler also checks freshness and rule deadlines.
- Notify immediately when a condition is already true at activation.
- No sustained delay and a 15-minute cooldown.
- One notification per true episode. A valid false condition rearms the rule. An unknown/stale condition does not rearm it, and a stale gap resets a sustained-duration timer.
- Recovery notifications are disabled unless selected.

Persistent in-app alerts can be acknowledged and their evidence inspected. Acknowledgement does not change the underlying condition. Resolution and acknowledgement are recorded separately.

Within the calculation editor, **Manage webhook connections** lets you supply a public HTTPS URL, optional signing secret and explicit enabled state. Also select that connection on the intended rule. Saving a connection alone does not authorize every rule to use it. No destination is inferred from page content or model output. Email, trading, purchasing, arbitrary scripts and monitoring-control actions are outside this release.

A webhook POST contains alert and calculation identities, output values, formula revision and supporting input timestamps/capture identifiers. Raw page bodies are excluded. `Idempotency-Key` identifies the delivery. An optional secret produces `X-Parity-Signature: sha256=<HMAC of exact payload bytes>`.

Delivery validates public addresses on every attempt, preserves hostname TLS checks, rejects redirects and uses a bounded 10-second request budget. Transient failures have at most five attempts and bounded Retry-After handling. Permanent failures are recorded. Receivers must deduplicate the idempotency key: an ambiguous timeout can cause repeated remote delivery. Pausing/archiving an automation or invalidating its dependencies prevents a queued delivery; a POST already started cannot be retracted.

Connections live in the private ignored `DATA/private/automation-connections.json` file. APIs and logs omit URLs and secrets. Database backups exclude this file. Restored pending deliveries are disabled; reconnect destinations and explicitly enable a new action rather than replaying a backup's outbound queue. Existing alert and delivery history remains available.

## API and CLI

The authenticated mutation APIs are additive:

- `POST /api/automations/preview`: `{instructions, answers?, plan?, monitor_draft_id?}` → `{draft_id, status, questions, plan, preview, catalog, errors}`.
- `POST /api/automations`: `{draft_id}`; `GET /api/automations` supports source filtering, pagination and archived results.
- `GET/PATCH/DELETE /api/automations/{id}`: inspect, revise/pause/update parameters, or archive while retaining history.
- `GET /api/automations/{id}/history` and `GET /api/calculations/{evaluation_id}` resolve immutable results.
- `GET /api/automation-alerts`; `PATCH /api/automation-alerts/{id}` with `{acknowledged:true}`.
- `GET/POST/PATCH/DELETE /api/automation-connections`; `GET /api/automation-deliveries` lists delivery status without private connection details.
- `POST /api/dashboard/series`: extracted identities retain their existing form; calculated identities use `{kind:"calculated", automation_id, field_id}`. Combined requests have at most 50 fields and 200 actual points per field, over up to 30 days.

A plan has version 1, stable input bindings, named parameters, output expressions, rules, an interval and an explicit cross-period flag. Expressions are bounded JSON trees; generated code is never executed. Limits are 50 source inputs, 20 outputs, 20 rules, 100 supplied parameters, depth 20 and 1,000 expression nodes per plan.

CLI examples use the project's Python environment:

```sh
python cli.py automations
python cli.py automation-preview "Alert when Current Price exceeds INR 1000"
python cli.py automation-start DRAFT_ID
python cli.py automation-history AUTOMATION_ID
python cli.py automation-pause AUTOMATION_ID
python cli.py automation-pause AUTOMATION_ID --resume
python cli.py automation-parameters AUTOMATION_ID parameters.json
python cli.py automation-alerts
```

`automation-preview --plan plan.json` and `--answers answers.json` use the same validators as the UI. `parameters.json` maps existing parameter IDs to decimal values. Existing CLI commands and all five MCP contracts retain their behavior. Ask Parity can retrieve server-calculated values with formula and source-capture citations in current or historical mode.

## Upgrade and verification

Schema 5 is additive. Stop services and use `python scripts/database.py --upgrade` to create and verify a backup before applying it. No personal data is reset or imported. Fresh empty databases initialize directly.

```sh
python scripts/test.py --postgres
python scripts/automation_browser_acceptance.py
python scripts/automation_browser_acceptance.py --with-models
python scripts/benchmark_automations.py
```

The browser and benchmark scripts use disposable PostgreSQL databases and fixture websites. The optional model rehearsal uses locally installed MiniLM/Qwen; paid API keys are unnecessary. Results and limits are recorded in the verification report. A successful deterministic fixture does not guarantee access to every public website or reliable interpretation of every instruction.
