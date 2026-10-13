# Historical NBA forecasting benchmark

Completed 2026-10-12 local project date. This is the authorized historical
integration/Stage 02–03 extension. Existing weekly forecasting, joint sampling,
empirical-Bayes prior and residual calibration are reused. No advanced model,
live Yahoo activation, optimizer change or model promotion occurred.

## Data flow and actual schema

Pinned snapshot `llimllib/nba_data@62df92a05f16b57498851167b8289cf9ec316aea`,
already downloaded under ignored `data/nba_data/raw/`. Four seasonal Parquet
files supply this adapter; nothing was downloaded again. Existing `nba.duckdb`
views remain usable. Combined exports and season-total tables are never read.

`playerlog_2025/2026` contains string `gameId`, integer `personId` and `teamId`,
text `minutes`, and integer box-score counts. `gamelog_2025/2026` uses different
column names: `game_id`, `team_id`, `game_date` (ISO date label as text),
`season_year`. Join by **game and team IDs**, with duplicate/unmatched joins
rejected. Names, positions and season-total exports never determine identity
or features. Raw files remain the game-level source of truth.

| Season ending | Regular-season games | Player-game rows | Unique NBA players | Missing date joins / duplicate player-games |
|---|---:|---:|---:|---:|
| 2025 | 1,230 | 32,516 | 577 | 0 / 0 |
| 2026 | 1,230 | 32,179 | 591 | 0 / 0 |

Both seasons have 2,460 unique team-game records. Every selected source row
passes the same nonnegative-count, makes/attempts and points arithmetic checks
as the existing forecaster. Games use the regular-season `002` prefix. Older
2010–2024 partitions remain excluded because their player logs are sparse and
duplicated. Cardinality and successful joins establish local coverage, not
independent official-source verification.

The conversion path is:

1. Verify source SHA-256 values against the existing manifest; query Parquet
   through bounded DuckDB views (`1GB` memory limit, two query threads).
2. Build validated `GameObservation` with stable NBA player/team/game IDs,
   season, actual date label, all eleven raw 9-CAT counts, original minutes text,
   publication time where known, and actual source retrieval/ingestion time.
3. Sum actual games into disjoint seven-day `Window` inputs, grouped by
   `(season, NBA player ID, Monday date)`. No missing player-week is generated.
   A zero-stat/DNP source row stays zero; blank minutes remain uninterpreted.
   Trades retain the player key and all game/team IDs. Partial season-edge
   weeks are excluded. This yields **20,987 observed player-week windows**.
4. Cache derived windows/provenance in content-addressed Parquet under
   `data/nba_data/features/`, invalidated by source/configuration/code changes.
   No second raw-game database or historical download is created.
5. `forecast_historical` selects the requested season and origin-known windows,
   then calls the existing `forecast`. Output remains the existing weekly
   joint-count contract, with historical source/policy and game-provenance hash.
   Benchmarking reuses `known_windows`, `interval_calibration`, `metrics`, and
   the existing registry's one-use holdout reservation in isolated research state.

`IdentityMap` accepts only stable Yahoo keys, positive NBA IDs, explicit season,
evidence and observation/ingestion timestamps. Conflicting or ambiguous bindings
fail. Yahoo inference resolves the mapping at the cutoff before selecting NBA
history; unverified links fail rather than guessing by name. No verified real
Yahoo-to-NBA entries were supplied, so none were fabricated. The JSON format is
version 1 with `links` containing `yahoo_player_key`, `nba_player_id`, `season`,
`observed_at`, `ingested_at`, and `evidence`; evidence must establish the exact
identifiers. NBA-only research does not require Yahoo identity or league access.

## Time contract and limitations

The source manifest records actual retrieval at
`2026-10-13T02:04:28.124793+00:00`. **No historical first-publication timestamps
are known for these rows.** Date labels are not exact tip-off/completion times.

The adapter defaults to **strict** availability: unknown publication falls back
to actual retrieval, and local ingestion also gates access. Consequently these
snapshot rows are unavailable to strict forecasts before retrieval. It does
not falsely backdate local ingestion.

This benchmark explicitly selects **retrospective_next_day**: absent publication
is assumed available at noon UTC the day after the game date, with virtual
research ingestion at that boundary. Seven-day windows run Monday noon UTC to
the next Monday noon, using NBA calendar-date labels. Actual retrieval is kept
separately in source provenance. A known later publication delays the window;
end/observation/virtual-ingestion must all be at or before origin T. An entire
weekly total is withheld until its final constituent is available. Target
outcomes are separate from feature inputs, and available by evaluation end.

Thus the replay is chronologically correct **under the declared availability
assumption**, not proof of historically published box scores. Corrections made
before the snapshot cannot be reconstructed; snapshot labels may include later
revisions. Injury, ownership, waiver, lineup, transaction and publication history
cannot be recovered. This is forecasting research, not historical fantasy
transaction replay or a live-quality claim.

Each model uses only the current season's history and contemporaneous peers;
no prior-season totals are carried across the offseason. Same NBA ID survives
trades and seasons. This deliberately avoids an unvalidated carryover prior.
Season-to-date here means the equal-weight mean of **completed observed full
weekly windows in the current season**, matching the existing seven-day horizon;
it is not a full-season aggregate or a per-game average. Partial boundary weeks
and weeks with no player rows are outside this baseline and evaluation support.

## Frozen selection and chronological evaluation

Versioned [protocol](benchmarks/nba-protocol.json), seed **42**, **256** joint
samples per forecast. The cohort is the 24 smallest deterministic hash-ranked
NBA IDs with at least four known 2024–25 windows and positive training PTS at
2025-01-06 noon UTC. Cohort selection uses no later-season membership or outcome.
Eighteen of those players contribute usable final cases. This small reproducible
cohort bounds peer fitting/sampling cost; it is not a league-wide claim.

| Window | Dates, noon UTC | Role | Usable cases/model |
|---|---|---|---:|
| Initial history | Before 2025-01-06 | Cohort, normalization scales | Origin-known only |
| Development validation | 2025-01-06 to 2025-02-17 | Select half-life | 111 |
| Calibration | 2025-02-17 to 2025-03-24 | Fit fixed marginal residual widths | 89 |
| Final evaluation | 2026-01-05 to 2026-04-13 | Frozen comparisons on later season | 188 |

All boundaries were saved before evaluation. Histories expand at each weekly
origin; previous evaluation games may become history at later origins, while
half-life and calibration parameters remain frozen. Minimum four own observed
windows and an adjacent previous week are required. Fourteen final origins
contribute 11–16 players each. Targets without sufficient/adjacent history or
observable rows are excluded; results are conditional on that support, not on
predicting participation or missing weeks. All four models have exactly the
same 188 target identities and thresholds.

Selection minimizes the mean of per-category MAE divided by an origin-known
initial-training mean (floor one count), equally across all eleven counts.
Tie-break: shortest half-life. No final-period outcomes set scales, select a
half-life, or fit calibration.

| Candidate half-life (days) | Development normalized MAE |
|---:|---:|
| 7 | 0.620956 |
| 14 | 0.596201 |
| 28 | 0.590922 |
| 56 | 0.592099 |
| 112 | 0.593871 |

**Selected half-life: 28 days.** The configured selected candidate and fixed
28-day incumbent therefore give identical predictions/metrics. All candidate
per-stat development MAEs are retained in the JSON; only the selected candidate
is evaluated in the final period. Production's existing 28-day default remains;
no candidate is registered or promoted in the production model registry.
The isolated research registry reserves the final period before opening it.
Later executions return the saved frozen report; changed code/data/protocol
cannot retune against that consumed period. Retain the registry and frozen
artifacts; deleting them defeats this local audit guard.

## Final-period actual results

MAE is in **counts per seven-day player-window**, including observed zero rows.
These are analytic expected-count errors, not Monte Carlo sampled-mean errors.

| Category | Season-to-date MAE | Fixed 28d MAE | Selected 28d MAE | Shrinkage MAE |
|---|---:|---:|---:|---:|
| PTS | 14.1870 | 13.4050 | 13.4050 | 14.0016 |
| REB | 4.4753 | 4.2450 | 4.2450 | 4.3600 |
| AST | 3.8512 | 3.7280 | 3.7280 | 3.7765 |
| STL | 1.5099 | 1.4715 | 1.4715 | 1.4864 |
| BLK | 1.0341 | 1.0549 | 1.0549 | 1.0625 |
| 3PM | 2.2303 | 2.1347 | 2.1347 | 2.1512 |
| TO | 2.1179 | 2.0810 | 2.0810 | 2.0915 |
| FGM | 5.1924 | 4.8607 | 4.8607 | 5.0649 |
| FGA | 10.2060 | 9.5481 | 9.5481 | 9.8943 |
| FTM | 3.2700 | 3.2532 | 3.2532 | 3.3446 |
| FTA | 3.9760 | 3.9584 | 3.9584 | 4.0436 |

PTS MAE for 28-day decay is **5.51% lower** than season-to-date on these unseen
cases (13.4050 versus 14.1871). Ten of eleven count MAEs are lower; BLK is worse
(1.0549 versus 1.0341). Shrinkage does not beat recency on any of the eleven MAEs
in this cohort. These are measured descriptive differences, not statistical
significance or evidence of improved fantasy matchup decisions. No claim is
made about players absent from the evaluation support or another future season.

Raw central empirical 80% intervals retain the existing joint bootstrap and
shared exposure shock. Residual-calibrated marginal intervals use the earlier
89-case calibration period, via the existing fixed 80% quantile procedure;
they do not modify the joint sampler. Brier scores use the same event for every
model: `actual > floor(current-season origin-known own weekly mean)`. Five-bin
reliability counts/rates and probability Monte Carlo SE are saved in JSON.
The central 80% interval score is `width + 10*lower_miss + 10*upper_miss`;
lower values reward narrower intervals with fewer/milder misses. Coverage alone
is insufficient, especially for discrete low-count categories.

| Model | Category | Raw 80% coverage | Calibrated 80% coverage | Raw mean width | Raw interval score | Common-event Brier |
|---|---|---:|---:|---:|---:|---:|
| Season-to-date | PTS | 0.8245 | 0.7979 | 48.5479 | 62.8032 | 0.2327 |
| Season-to-date | REB | 0.8457 | 0.7766 | 14.0851 | 19.2979 | 0.2383 |
| Season-to-date | AST | 0.8564 | 0.8191 | 13.6330 | 17.7287 | 0.2386 |
| Season-to-date | STL | 0.9043 | 0.7500 | 4.9255 | 6.4149 | 0.2253 |
| Season-to-date | BLK | 0.9202 | 0.7500 | 3.0053 | 4.3883 | 0.2494 |
| Season-to-date | 3PM | 0.8351 | 0.8298 | 7.0213 | 10.3191 | 0.2504 |
| Season-to-date | TO | 0.8617 | 0.8032 | 7.1117 | 9.1862 | 0.2365 |
| Season-to-date | FGM | 0.8245 | 0.8191 | 17.3457 | 22.3457 | 0.2376 |
| Season-to-date | FGA | 0.8511 | 0.7979 | 36.1968 | 44.9734 | 0.2343 |
| Season-to-date | FTM | 0.8564 | 0.7926 | 10.6543 | 13.3670 | 0.2408 |
| Season-to-date | FTA | 0.8457 | 0.7819 | 12.6436 | 16.4734 | 0.2408 |
| 28-day decay | PTS | 0.7979 | 0.7819 | 45.1436 | 60.3032 | 0.2207 |
| 28-day decay | REB | 0.8351 | 0.7713 | 13.6011 | 18.5479 | 0.2278 |
| 28-day decay | AST | 0.8511 | 0.7872 | 13.0372 | 17.1862 | 0.2213 |
| 28-day decay | STL | 0.8511 | 0.7713 | 4.3883 | 6.7287 | 0.2364 |
| 28-day decay | BLK | 0.8936 | 0.7447 | 3.0532 | 4.5426 | 0.2511 |
| 28-day decay | 3PM | 0.8298 | 0.8138 | 6.6223 | 10.0798 | 0.2443 |
| 28-day decay | TO | 0.8404 | 0.7979 | 6.5904 | 9.3564 | 0.2418 |
| 28-day decay | FGM | 0.8404 | 0.7926 | 16.1649 | 21.3777 | 0.2206 |
| 28-day decay | FGA | 0.8298 | 0.8191 | 33.0532 | 42.9468 | 0.2209 |
| 28-day decay | FTM | 0.8457 | 0.8298 | 9.7766 | 13.5532 | 0.2533 |
| 28-day decay | FTA | 0.8511 | 0.7819 | 11.7926 | 16.3670 | 0.2510 |
| Bayesian shrinkage (28d) | PTS | 0.8617 | 0.8138 | 51.8245 | 62.1436 | 0.2287 |
| Bayesian shrinkage (28d) | REB | 0.8883 | 0.7872 | 15.4149 | 18.6064 | 0.2383 |
| Bayesian shrinkage (28d) | AST | 0.9096 | 0.8404 | 14.9415 | 17.1755 | 0.2199 |
| Bayesian shrinkage (28d) | STL | 0.8777 | 0.8085 | 4.7128 | 6.4681 | 0.2360 |
| Bayesian shrinkage (28d) | BLK | 0.9255 | 0.7713 | 3.2500 | 4.5798 | 0.2498 |
| Bayesian shrinkage (28d) | 3PM | 0.8777 | 0.8138 | 7.3032 | 9.7500 | 0.2389 |
| Bayesian shrinkage (28d) | TO | 0.8777 | 0.7766 | 7.3777 | 9.3989 | 0.2435 |
| Bayesian shrinkage (28d) | FGM | 0.8936 | 0.7660 | 18.4415 | 22.0053 | 0.2277 |
| Bayesian shrinkage (28d) | FGA | 0.8670 | 0.8298 | 37.4362 | 43.7660 | 0.2281 |
| Bayesian shrinkage (28d) | FTM | 0.8883 | 0.8191 | 10.9734 | 13.8457 | 0.2484 |
| Bayesian shrinkage (28d) | FTA | 0.8830 | 0.7979 | 13.2500 | 17.3457 | 0.2516 |

Selected 28-day scores equal fixed 28-day scores in every row. Recency's raw PTS
coverage is **79.79%**; earlier-residual calibrated PTS coverage is **78.19%**.
Across its eleven categories, calibrated coverage ranges **74.47%–82.98%**;
calibration is not uniformly nominal. PTS Brier is 0.2327 season-to-date,
0.2207 recency and 0.2287 shrinkage. Mean probability Monte Carlo SE is recorded
per category; it describes finite draws, not model uncertainty. Player-weeks
repeat players and overlap calendar conditions, so naive independent-case
confidence intervals would overstate precision. No calibrated matchup-win
probability follows from these marginal diagnostics.

## Reproduction, costs and verification

Run from the repository root, using the already verified snapshot:

```bash
uv run --offline --no-sync python -m fantasy_optimizer.historical_benchmark
# Default strict adapter; historical origins before retrieval have no known rows:
uv run --offline --no-sync python - <<'PYCODE'
from pathlib import Path
from fantasy_optimizer.historical import load_history
rows, provenance = load_history(Path("data/nba_data"))
print(len(rows), provenance["availability_policy"])
PYCODE
```

The benchmark first run evaluates the registered final period once. A repeat
returns the saved report if code/data/protocol match; no repeat tuning is run.
The report stores exact replay inputs/outcomes/hashes, configuration, cohort,
source and code identities. Keep ignored `features/benchmark-registry.json`
and `benchmark-frozen.json` with the research snapshot. The benchmark's
`--data`, `--protocol` and `--output` flags support explicit reviewed paths.
[Full evidence](benchmarks/nba-real-data.json) includes all candidate development
metrics, calibration widths, final per-case replay and probabilistic diagnostics.

Measured benchmark invocation: **26.160 seconds**, **104.27 MiB peak process RSS**, seed 42, 24-player cohort. Includes cached local source verification/loading, selection/calibration/evaluation, excludes imports and final serialization. Concurrent engineering checks ran; this is a local measurement, not a 16 GB laptop hardware benchmark. The 1 GB DuckDB cap and measured small process footprint are compatible with the requested laptop budget for this bounded workload. Full-league repeated forecasts have not been benchmarked. JSON evidence is 2,143,958 bytes.

Verification: offline locked dependency sync, Ruff lint/format (38 files), mypy
(23 source files), 69 focused adapter/forecast/audit/storage/learning tests,
**203/203 unrestricted full Python tests**, Debug CMake configure/build,
**3/3 unrestricted CTest targets with full leak checks**, tracked C++ formatting,
and diff checks. No C++ changes require fresh clang-tidy. No local tests skipped.
The real-snapshot integration test explicitly skips only when this owner-authorized
ignored dataset is absent (for example a fresh CI checkout); the remaining
conversion and temporal tests use small verified/handmade rows offline.

The restricted full suite yielded **200 passes and three setup errors** at
`socket.socket` before application HTTP code. A plain Python socket constructor
independently reproduced `PermissionError: EPERM`; the unchanged unrestricted
suite passed all 203. Standard sandbox CTest had two LeakSanitizer ptrace failures
and native parity passed; unchanged unrestricted CTest passed 3/3. Neither
production code nor diagnostic settings were altered to suppress those failures.

Remaining limitations: no recovered publication/revision history, no verified
real Yahoo crosswalk entries, conditional weekly observation support, variable
weekly schedule/exposure, uninterpreted minutes/DNP participation semantics,
restricted peer cohort, season reset rather than carryover learning, and no
historic fantasy constraints/transactions or live-quality validation. The
existing exposure sampler and pooled peer prior remain heuristic. Integration
and benchmark acceptance are met within this disclosed research scope; stop
at owner review. Contextual forecasting, another stage, main merge and external
publication are not authorized.
