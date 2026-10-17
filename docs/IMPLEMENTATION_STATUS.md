# Parity 2.0 — current implementation snapshot

Snapshot date: 17 October 2026.

## Implemented source present

- Version 3 schema registration for monitors, captures, observations, jobs and retrieval projection.
- Typed structured extraction, preview, monitor activation and observation history.
- Durable URL jobs, renewable ownership, retries and independent indexing.
- Shared authenticated loopback embedding service and PostgreSQL retrieval projection.
- Dashboard, source setup, history, retained chat and Settings frontend.
- Docker configuration, launcher changes and migration/backup tool source.

Presence of implementation is not a claim that every acceptance requirement has passed.

## Checks performed for this snapshot

- React/TypeScript production build: passed; compiled assets included.
- Python compile check: passed for the files present when checked.
- Existing lifecycle/release/chat suite: 33 passed, 10 skipped, 2 failed.
- Worker implementation tests: 7 passed in the worker development run.

The two existing-suite failures concern an old test expecting implicit inclusion of demo sources and an old schema-version assertion expecting version 2 rather than 3. They are recorded rather than concealed; the regression suite still needs reconciliation with the new contracts and a complete rerun.

## Still pending

- Docker Desktop installation and actual PostgreSQL integration verification.
- Complete integrated monitoring and frontend browser acceptance.
- Migration and backup/restore rehearsal on PostgreSQL.
- Current 1,000 / 10,000 / 50,000 chunk performance and retrieval-quality benchmarks.
- Final end-to-end verification, remaining integration fixes and release packaging.

Historical reports under `docs/v1` and `archive/v1` apply only to the earlier demo. They do not verify Parity 2.0.
