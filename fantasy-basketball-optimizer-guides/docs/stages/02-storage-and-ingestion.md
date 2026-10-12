# Stage 02 — Data schema, snapshots and incremental ingestion

**Goal:** reliable, lightweight, point-in-time Yahoo-derived data storage.

## Implement

- Implement a versioned migration system for DuckDB, using entities in `docs/DATA_CONTRACTS.md` adjusted to verified Yahoo fields.
- Build idempotent ingest for league settings, players, rosters, availability, matchup totals and available statistical windows. Store only actual observed granularity (never fabricate player-game records).
- Preserve `observed_at`, `ingested_at`, relevant event dates, source identifiers and ingestion watermarks. Store roster/availability snapshots **when changed**; keep enough detail for future backtests.
- Upsert appropriately, track fetch failures without corrupting data; use transactions. Minimize redundant raw payload storage and redact credentials.
- Add small fixtures for two runs (unchanged, then changed roster/player), duplicates and partial-failure retry.
- `fantasy sync --fixture` works without Yahoo credentials; optionally real `fantasy sync` if approved.

## Acceptance criteria

- Repeating identical input changes no substantive rows and does not multiply snapshots.
- Backtest query "state known as of T" never pulls later observations.
- Database migrations and recovery paths are tested. Basic local DB size and sync duration are logged without unfounded promises.
- Update `STATUS.md` with schema version and next actions.
