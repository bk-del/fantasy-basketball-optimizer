# Manual fixture operations

Actual NBA distributions can now feed an explicitly hypothetical fixture league via
`fantasy nba run --fixture`; see [real-data pipeline](REAL_DATA_PIPELINE.md).

Stage 08 is an offline local workflow awaiting owner validation of actual output.
It is not production-ready: authorized Yahoo rules, comparable game forecasts and
historical ownership/availability remain unverified. A valid token alone does not
enable live run. All recommendations remain read-only; the owner makes transactions.

## Run and inspect

Use the project checkout in the WSL2 Linux filesystem, or a native Ubuntu shell.
Install the tools listed in README, then recreate the locked environment:

```bash
uv sync --locked --group dev
uv run fantasy status --fixture
uv run fantasy run --fixture
uv run fantasy run --fixture
uv run fantasy run --fixture --dry-run
```

Default state: `data/operations-fixture.duckdb`, `data/fixture-runs/` and optional
`models/fixture-registry.json`, all ignored by Git. `--database`, `--output` and
`--registry` override these paths. This database is separate from Stage 02's coarse
fixture (`fantasy sync --fixture` uses `data/fixture.duckdb`). Do not mix those
fixture sources in one database; source validation refuses unrelated watermarks.

Run takes a nonblocking exclusive advisory lock beside the canonical database
path, synchronizes four synthetic resource batches, validates their content
watermarks, selects point-in-time counts, infers weekly summaries using the active
model, simulates/optimizes independent handmade game forecasts, and atomically saves
a content-addressed result. Model status/run never initialize or modify a registry.
Training is only `fantasy train --fixture`; there is no retraining on run. Without
an initialized registry, run uses provisional recency, seed 42 and 256 weekly draws.
`--seed`, `--screening-samples`, `--finalist-samples`, `--backend python|cpp` configure
simulation explicitly. The active model's weekly draw budget is preserved.

The weekly history contains four fictional players and the game decision fixture
eight players with 24 handmade games, position restrictions, protected roster value,
a waiver candidate, acquisition limits and remaining-game caps. These representative
situations are a small matchup/pool subset, not a complete real 14-team league.
Game dates are shifted once from the Stage 05 fixture to August 24's weekly origin;
counts are not manufactured from weekly totals. Output explicitly separates the
weekly active-model summaries from the game's independent model version. No
unsupported weekly-to-game adapter or active-model effect on game predictions is
claimed. Full joint weekly draws are omitted from run summaries because the game
fixture does not consume them; `fantasy forecast --fixture` retains that contract.

Review `optimization.recommended_action`, ranked before/after probabilities and
Monte Carlo SE, paired gain SE, category deltas, roster-value cost, filtered actions,
`freshness`, model/feature versions, rules verification and source limitations.
Default recommendation is the synthetic `ADD:target/DROP:streamer`; it is not live
advice. Owner should validate these outputs and constraints before live deployment.

## Cache and fixture changes

Results live at `OUTPUT/RUN_HASH.json`, with derived weekly/decision cache envelopes
under `OUTPUT/cache/`. These are reproducible derived artifacts; DuckDB remains the
snapshot store. Cache keys include point-in-time input hashes, code and feature/model
versions, active model/config/seed and native binary/NumPy version where relevant.
Weekly inputs and game/transaction inputs are keyed independently. A transaction
refreshes the decision; a weekly-stat revision refreshes weekly forecasts. Neither
requires recomputing its unrelated component at an identical as-of/configuration.
Changing the as-of, seed or relevant versions invalidates the affected cache.
Checksum mismatch/corrupt derived cache causes recomputation; a corrupt result is
repaired atomically. Cache-hit/changed-row diagnostics can differ between identical
runs; persisted results, recommendation and seeds remain identical.

```bash
uv run fantasy run --fixture --database /tmp/change.duckdb --output /tmp/change-runs --as-of 2026-08-24T00:10:00Z
uv run fantasy run --fixture --database /tmp/change.duckdb --output /tmp/change-runs --scenario transaction --as-of 2026-08-24T00:10:00Z
```

`new_stats` adds an explicitly synthetic two-attempt correction; `transaction`
exhausts acquisition capacity and produces HOLD; `unknown_settings` marks the cap
unknown and fails closed; `partial_ingestion` exercises a refused availability fetch.
Use separate paths for independent scenarios, or progress baseline to one later
change. Returning to older baseline state in the same database is refused, preserving
newer snapshots. Fixture observation/ingestion clocks are synthetic and deterministic,
not real acquisition times or evidence of historical Yahoo support. Stage 02 sync
continues to record actual local ingestion times.

`--as-of` requires a timezone. Run refuses times before its known ownership/settings
snapshot or at/after its first game (no later observed totals exist). An active model
trained/selected later than the requested as-of is refused. Standalone forecast
supports earlier known weekly windows; full-fixture benchmark plus an earlier as-of
is refused. Standalone optimize supports its own January fixture origin until its
first game. Train/backtest's fixed registered split requires evaluation data known
by the supplied as-of; requesting an earlier boundary refuses before training or
holdout exposure. No present-day ownership reconstructs historical availability.

## Failures and recovery

A second sync/run on the same canonical database exits with an actionable lock
message. Process exit releases the lock, including interruption; the empty lock
file remains and must not be unlinked while another process may hold it. Cache
writes are atomic. Single-writer scope is per database; share that path for one
league workflow. Registry mutations also remain the Stage 07 manual single-writer
workflow: do not promote/train concurrently with a run.

Partial ingestion commits successful resources but saves no new recommendation
and does not serve a prior result as fresh. Retry the same complete snapshot after
resolving the source failure. A fresh `partial_ingestion` scenario can recover with
baseline (same fixture observation). Out-of-order or conflicting snapshots refuse
without erasing history. Existing results remain historical artifacts, not fallback
recommendations. Preserve backups rather than deleting a working real database.

Structured JSON events go to stderr: start, sync changes, cache corruption, completion
hits or partial failure. They whitelist counts/booleans/event names; no tokens, account
identifiers, paths, raw payloads or arbitrary exception details enter these events.
CLI errors avoid transport/credential details. The existing read-only Yahoo audit
client retries only transient 429/5xx failures, at most three attempts with bounded
backoff/Retry-After, and refuses revoked/expired authorization without retrying it.
Run does not make live requests; credentials/partial verified data cannot bypass
its gate. Missing native backend reports `--backend python` as the fallback.

Run dry-run executes in disposable temporary storage, reads the selected registry,
and changes none of the configured DB/output/model paths. It reports `saved=false`
and no artifact. `sync --dry-run --fixture` likewise evaluates a fresh temporary
Stage 02 database, not a preview of changes against an existing DB. Forecast dry-run
writes no model artifact. Optimizer is already read-only. No dry-run submits actions.

## WSL2 to native Ubuntu

Stop manual jobs before copying state. On native Ubuntu install project-local Python
and the required C++ tools; copy/clone the same reviewed commit, delete any copied
`.venv` and rebuild it with `uv sync --locked --group dev`. Do not reuse WSL binaries
or caches across hosts. Run required lint/types/tests/CMake/CTest and a separate
fixture database first. Copy the closed DuckDB (and WAL, if present) and model registry
separately, preserving their relationship and holdout audit. Copy secrets through a
private channel separately from repository/model exports; restore restrictive owner
permissions. Never put secrets in shell arguments, logs, Git or shared backups.
Do not enable live operations until authorization and actual data contracts are
verified. Rollback/recovery is documented in [learning](LEARNING.md) and
[storage](STORAGE.md).

## Optional scheduling examples — disabled

Prerequisites: owner has validated actual fixture output, a tested native Ubuntu
checkout/environment, explicit scheduling approval, a dedicated writable state path
and noninteractive execution. WSL systemd requires owner-enabled systemd support;
plain manual execution remains the baseline. No timer, cron entry or service is
installed or enabled by Stage 08. These examples run synthetic data only; a real
scheduled Yahoo workflow requires a future verified live adapter.

A oneshot service can use the same command unchanged (replace all example paths):

```ini
[Unit]
Description=Fantasy fixture report

[Service]
Type=oneshot
WorkingDirectory=/home/OWNER/projects/fantasy-basketball-optimizer
ExecStart=/home/OWNER/projects/fantasy-basketball-optimizer/.venv/bin/fantasy run --fixture
```

An optional paired timer:

```ini
[Unit]
Description=Daily fixture report timer

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true
Unit=fantasy-fixture.service

[Install]
WantedBy=timers.target
```

Or a user crontab example with an explicit working directory and absolute executable:

```cron
0 9 * * * cd /home/OWNER/projects/fantasy-basketball-optimizer && /home/OWNER/projects/fantasy-basketball-optimizer/.venv/bin/fantasy run --fixture >> /home/OWNER/fantasy-report.log 2>&1
```

Review local timezone, permissions, logs/retention and paths before opting in. A fixed
fixture report does not become current live advice merely because a timer runs it.
