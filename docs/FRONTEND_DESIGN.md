# Frontend design

The October 2026 refresh takes visual direction from [Agno](https://www.agno.com/): light surfaces, charcoal type, coral actions, fine dividers and restrained typography. Parity keeps its own identity and workflows. No Agno code, branding or product claims are included.

## Shared foundation

`frontend/src/theme.css` owns the palette and final application-wide component treatment. Inter Variable and JetBrains Mono are already installed locally and bundled by Vite; the interface needs no font CDN or new dependency. The existing structural styles in `styles.css`, `details.css`, `monitoring.css` and `automation.css` use the shared color tokens. `theme.css` loads last in `main.tsx`.

- Light backgrounds and neutral borders apply to all four navigation screens, source setup, calculation setup, evidence, history, notifications and connection dialogs.
- Coral marks actions, selected navigation and keyboard focus. Green, amber and red retain their meaning for verified, warning and failed states; color accompanies visible text.
- Native buttons, inputs and existing modal focus management remain in use. Keyboard shortcuts still work without displaying numbers on navigation buttons.
- Motion is limited to interaction feedback and is suppressed by reduced-motion preferences.

## Dashboard ledger

`dashboard.css` displays source groups with a linked source title and real check scheduling metadata. Fields are flat, full-width name/value rows. Single-source calculations appear alongside on wide screens and below on narrow screens. Cross-source results remain in their existing section. Numeric values use tabular monospaced type, and names remain larger than values.

Each row is a keyboard-operable button opening the existing details and immutable evidence. Failed/stale field warnings remain visible. Budget results retain contextual emphasis. No field card grid, trend chart, range selector or arrangement interface is rendered.

The refresh changes presentation only: observations, extraction rules, schedules, calculation formulas, historical evidence and retrieval contracts are not migrated or rewritten.

## Verify changes

Run `npm ci` and `npm run build` in `frontend/`. From the repository root, run the PostgreSQL fixture rehearsals with the configured development database:

```sh
.venv/bin/python scripts/browser_acceptance.py
.venv/bin/python scripts/automation_browser_acceptance.py
```

These scripts create isolated disposable databases and use synthetic sources. They cover automatic setup, persisted scheduling, scalar/zero/table/list values, SSE and polling, evidence/history navigation, source removal/restoration, calculations, alerts, clarification and narrow/keyboard layouts. They do not send webhooks to real destinations or require paid APIs. Inspect all four screens and dialogs visually as well; automated functional checks do not replace visual review.
