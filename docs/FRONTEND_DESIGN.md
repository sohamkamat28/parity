# Frontend design

The October 2026 refresh takes visual direction from [Agno](https://www.agno.com/): light surfaces, charcoal type, coral actions, fine dividers and restrained typography. Parity keeps its own identity and workflows. No Agno code, branding or product claims are included.

## Shared foundation

`frontend/src/theme.css` owns the palette and final application-wide component treatment. Inter Variable and JetBrains Mono are already installed locally and bundled by Vite; the interface needs no font CDN or new dependency. The existing structural styles in `styles.css`, `details.css`, `monitoring.css` and `automation.css` use the shared color tokens. `theme.css` loads last in `main.tsx`.

- Light backgrounds and neutral borders apply to all four navigation screens, source setup, calculation setup, evidence, history, notifications and connection dialogs.
- Coral marks actions, selected navigation and keyboard focus. Green, amber and red retain their meaning for verified, warning and failed states; color accompanies visible text.
- Native buttons, inputs and existing modal focus management remain in use. Keyboard shortcuts still work without displaying numbers on navigation buttons.
- Motion is limited to interaction feedback and is suppressed by reduced-motion preferences.

## Dashboard metric strips

`dashboard.css` displays source groups with a linked source title and real check scheduling metadata. `DashboardMetrics.tsx` balances metrics into connected white strips with up to five columns, shared outer edges and vertical separators. Muted labels sit above prominent tabular values; units remain smaller. Fields appear first and single-source calculations follow in their own strip. Narrow screens use two columns within the shared strip. Cross-source results remain in their existing section.

Each metric is a keyboard-operable button opening the existing details and immutable evidence. Failed/stale field warnings remain visible. Only server-provided comparable observation pairs produce change badges. Percentage fields show percentage-point differences, and previous-zero comparisons retain absolute differences. Baseline and stale inputs do not show comparison percentages. Direction alone is neutral; explicit budget conditions use verified/warning colors and are labeled against the supplied budget. No individual metric cards, trend chart, range selector or arrangement interface is rendered.

The refresh changes presentation only: observations, extraction rules, schedules, calculation formulas, historical evidence and retrieval contracts are not migrated or rewritten.

## Verify changes

Run `npm ci` and `npm run build` in `frontend/`. From the repository root, run the PostgreSQL fixture rehearsals with the configured development database:

```sh
.venv/bin/python scripts/browser_acceptance.py
.venv/bin/python scripts/automation_browser_acceptance.py
```

These scripts create isolated disposable databases and use synthetic sources. They cover automatic setup, persisted scheduling, scalar/zero/table/list values, SSE and polling, evidence/history navigation, source removal/restoration, calculations, alerts, clarification and narrow/keyboard layouts. They do not send webhooks to real destinations or require paid APIs. Inspect all four screens and dialogs visually as well; automated functional checks do not replace visual review.
