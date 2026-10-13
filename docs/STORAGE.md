# Stage 02 storage and ingestion

Stage 02 is fixture-only. DuckDB 1.4.5 is pinned in `pyproject.toml` and `uv.lock`.
The six handmade batches in `fixtures/ingestion.json` exercise internal proposed
contracts. They are not authenticated Yahoo samples. A live XML-to-record adapter
must be added only after verifying field identity, coverage and completeness.
There is no live `sync`, no forecast storage, and no generated player-game table.

## Schema version 1

`schema_migration` records the version and SHA-256 of migration SQL. Migrations
run in a transaction; failures roll back and can be retried. Reopening validates
version and checksum. Unknown future versions or changed migration history are
rejected, not overwritten. A future schema change adds a migration rather than
editing version 1. Keep a backup before a future production migration.

Six canonical snapshot tables contain only their entity's proposed fields:

| Table | Entity key | Payload |
|---|---|---|
| `league_snapshot` | League | Season, scoring type, exposed stat categories and roster positions |
| `player_snapshot` | Player | Display name, team, eligibility, nullable status |
| `roster_snapshot` | Fantasy team | Complete membership for that observation and coverage |
| `availability_snapshot` | League collection | Observed player statuses and explicit collection completeness |
| `matchup_snapshot` | League and scoring period | Teams, coverage and observed stat-ID totals |
| `stat_window_snapshot` | Player and coverage window | Stat IDs/values and actual aggregate coverage |

Each row retains source ID, league/entity keys, `observed_at`, `ingested_at`,
nullable `event_at` and `source_updated_at`, content hash, canonical JSON facts,
and a source watermark hash. Optional source/event timestamps stay null when
unknown. Coverage is preserved in JSON; a season/window cannot become a game.
The payload is a small versioned entity record, not a raw HTTP/XML archive.
Canonical envelope fields are validated; credential/transport metadata is
rejected. Failure logs store only fixed codes, not exception bodies.

## Incremental semantics

One source batch commits snapshots, its successful-fetch watermark, and an attempt
record atomically. Fetch failures leave that source's data and watermark intact;
other resources can succeed. A failed database transaction rolls back all its
rows and watermark, then records a failure outside the rolled-back transaction.
Consumers must inspect failures and freshness; a partially successful run does
not assert a coherent, complete league state.

Duplicate identical entities and record ordering do not change hashes. Conflicting
duplicates, changed content at the same observation time, and older observations
are rejected. Repeated identical input adds no entity snapshots. A newer unchanged
fetch advances `watermark`, but leaves original entity observation times intact.
Retries upsert the same attempt identity; failures are diagnostic records rather
than an unbounded raw-response history. `sync_attempt` and `watermark` are current
operational metadata, not historical backtest inputs.

A roster is stored as a membership collection, so a removed player and an empty
roster are explicit changes. Missing entries in incomplete player/availability
collections do not imply deletion or availability. Availability fixtures remain
`unknown`; they do not infer ownership or addability from an absence.

## Point-in-time queries

`Store.as_of(kind, T)` chooses the latest snapshot per source/league/entity with
both `observed_at <= T` **and** `ingested_at <= T`. The ingestion condition also
excludes observations obtained earlier but persisted late. Timezones are required
and normalized to UTC; database timestamps use `TIMESTAMPTZ`. Queries fetch
watermark epochs instead of requiring an extra Python timezone package.

The fixture clock is synthetic (baseline at 12:00 UTC, changed at 13:00 UTC on
2026-10-12). Normal CLI ingestion timestamps are actual local persistence times.
Tests explicitly simulate both clocks; fixtures do not recover historical Yahoo
ownership, injury status or availability. No genuine source publication timestamp
has been confirmed. Retain missingness rather than substituting observation time.

## Run and recover

```bash
uv sync --locked --group dev
uv run fantasy sync --fixture
uv run fantasy sync --fixture
uv run fantasy sync --fixture --scenario changed
```

Default output is ignored `data/fixture.duckdb`. A fresh baseline adds seven rows,
an identical repeat adds zero, and the changed fixture adds three. To restart a
scenario, use `--database data/another-fixture.duckdb`; replaying baseline over
changed state is rejected. Never point fixtures at a future production database.
Size/duration metrics are measurements of that local run, not performance promises.
For inspection, open DuckDB read-only after sync closes its connection. Do not run
multiple writer processes against the same file.

No raw snapshots or Parquet layer are needed for these tiny fixtures. The tests
cover migration rollback/reopen/incompatible versions, duplicate and conflicting
input, empty rosters, change-only snapshots, source failure/retry, transaction
rollback, late ingestion, as-of filtering, timestamps, and disabled live sync.

DuckDB's documented [transaction statements](https://duckdb.org/docs/stable/sql/statements/transactions)
and [Python client](https://duckdb.org/docs/stable/clients/python/overview) informed
the implementation; behavior is verified with the pinned local package.
