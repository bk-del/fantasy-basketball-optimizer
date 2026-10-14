# Historical NBA forecasting benchmark

The original 24-player reference below is preserved from `42a5f83`. Current full-population results, actual inference, fixture decisions and exact reproduction commands are in the [completed integration milestone](#full-population-integration-milestone--completed-2026-10-12). Use its archived-code command for the original benchmark.

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

> The sections above preserve the original 24-player reference at `42a5f83`.
> The milestone below supersedes its population, connection and cost limitations.
> Original selection/evidence files remain unchanged; original replay uses that
> commit's code, rather than the modified source hash in this checkout.

## Full-population integration milestone — completed 2026-10-12

[Protocol](benchmarks/nba-population-protocol.json),
[all model and segment metrics](benchmarks/nba-population.json),
[CPU kernel measurements](benchmarks/nba-performance.json), and
[actual forecast/complete fixture decision evidence](benchmarks/nba-end-to-end.json).
The [pipeline audit](REAL_DATA_PIPELINE.md) records the original connections before
changes and the final contracts. No source download, new model architecture or
optimizer objective change occurred.

The 24-player restriction affected the old benchmark's development, calibration,
evaluation and peer pool only. It never restricted the historical adapter.
This milestone fits **64,695 valid player-games, 697 distinct NBA IDs, two complete
regular seasons (2024–25 and 2025–26)**; observed weekly data contain **20,987** full
player-windows. Older sparse/duplicate partitions remain quarantined. All available
valid rows in the verified source enter current fitting; no arbitrarily selected
cohort, current-roster filter, positive-points or consecutive-week requirement.
Reserves, rookies with recorded history, zero rows and departed players remain.

Historical eligibility requires **one own origin-known observation in the target
season**, so first-ever games without history are outside evaluation support.
The existing Bayesian prior supports limited history; no new unidentified player
or observation is invented. At each prediction origin priors use only then-known
other players with equal mass per player. Season-to-date resets to the target
season; recency and shrinkage use all earlier known seasons. This tests the actual
configurations; it cannot isolate a causal benefit from adding observations.
Historical availability remains explicitly `retrospective_next_day`, with actual
retrieval retained. Snapshot revisions and first-publication history cannot be
reconstructed. Current inference uses strict actual-retrieval gating.

### Chronological selection and support

The original Jan–Apr 2026 evaluation had already been examined. A fresh primary
period in the previously unscored end of 2024–25 was declared before opening its
outcomes; the larger 2026 period is a **replication, not an untouched holdout**.
The code/data/protocol freeze and one-use registry were saved before evaluation.
Expanding histories can include earlier held-out outcomes once known at later
origins; configuration and calibration remain frozen throughout.

| Period (noon UTC boundaries) | Per-game cases/model | Observed-week cases/model | Purpose |
|---|---:|---:|---|
| Before 2025-01-06 | 13,838 observations / 525 IDs | 4,338 observations / 523 IDs | Initial scales, all eligible priors |
| 2025-01-06–2025-02-17 | 7,395 | 2,599 | Development selection |
| 2025-02-17–2025-03-24 | 6,598 | 2,194 | Fixed marginal calibration |
| 2025-03-24–2025-04-14 | 4,170 / 497 IDs | 1,356 / 496 IDs | Fresh primary holdout |
| 2026-01-05–2026-04-13 | 18,150 / 564 IDs | 6,087 / 562 IDs | Disclosed replication |

Selection compares season-to-date and the existing recency/Bayesian estimators at
7/14/28/56/112-day half-lives, minimizing equally weighted normalized **all-eleven-
count** development MAE. Scales use pre-development counts, floor one. Selected
**per-game recency 14d**, **observed-week recency 28d**. Calibration and final
outcomes never choose parameters; no post-holdout tuning occurred. Production
uses the selected per-game configuration. Observed-week forecasts validate a
separate aggregate horizon; they are not future seven-day forecasts with invented
exposure. Each model has the same evaluation targets/outcome hashes and common
origin-known probability thresholds. Replays and hashes were independently checked.

### Primary held-out accuracy and calibration

MAE is analytic expected-count error, in counts per indicated horizon. The selected
recency estimator reduces all eleven count MAEs relative to season-to-date on this
primary period. Shooting ratios below worsen: **this is not universal 9-CAT
superiority, calibrated live odds, or proof that more training data improves accuracy**.
Bayesian shrinkage remains supported but did not win the declared selection metric.

#### Conditional recorded player-game

| Count | Season-to-date MAE | Selected recency MAE | Bayesian MAE |
|---|---:|---:|---:|
| PTS | 5.1024 | 4.7689 | 4.9054 |
| REB | 2.1204 | 1.9874 | 2.0310 |
| AST | 1.3671 | 1.2934 | 1.3326 |
| STL | 0.6319 | 0.6170 | 0.6281 |
| BLK | 0.4299 | 0.4124 | 0.4235 |
| 3PM | 0.8425 | 0.8178 | 0.8449 |
| TO | 0.8375 | 0.8018 | 0.8207 |
| FGM | 1.9362 | 1.8192 | 1.8680 |
| FGA | 3.5292 | 3.1812 | 3.2899 |
| FTM | 1.1228 | 1.0953 | 1.1264 |
| FTA | 1.3989 | 1.3591 | 1.4024 |

Selected recency diagnostics, nominal central 80% intervals:

| Count | Bias | Raw coverage | Residual coverage | Raw width | Common-event Brier |
|---|---:|---:|---:|---:|---:|
| PTS | -0.3597 | 0.8101 | 0.7729 | 13.0173 | 0.2339 |
| REB | -0.1240 | 0.8372 | 0.7815 | 5.4532 | 0.2333 |
| AST | -0.0801 | 0.8705 | 0.7875 | 3.5367 | 0.2245 |
| STL | -0.0112 | 0.9146 | 0.8036 | 1.4849 | 0.2122 |
| BLK | 0.0018 | 0.9336 | 0.8106 | 0.9564 | 0.1556 |
| 3PM | -0.0519 | 0.8986 | 0.7962 | 2.1329 | 0.1963 |
| TO | -0.0339 | 0.8930 | 0.7823 | 1.9990 | 0.2181 |
| FGM | -0.1507 | 0.8436 | 0.7758 | 4.9271 | 0.2340 |
| FGA | -0.3200 | 0.8271 | 0.7662 | 8.8880 | 0.2289 |
| FTM | -0.0065 | 0.8945 | 0.8002 | 2.7969 | 0.1974 |
| FTA | -0.0159 | 0.8899 | 0.7964 | 3.4561 | 0.2045 |

Shooting percentages are ratios of makes/attempts, not independent count means.

| Ratio | Targets with attempts | Season-to-date MAE | Recency MAE | Bayesian MAE | Recency bias | Raw coverage | Raw width | Brier |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FG% | 3127 | 0.1680 | 0.1727 | 0.1692 | 0.0077 | 0.8110 | 0.5595 | 0.2798 |
| FT% | 1762 | 0.2244 | 0.2288 | 0.2231 | -0.0042 | 0.8802 | 0.8330 | 0.3254 |

Minute segments use origin-known mean minutes: high ≥28, medium 15–<28, low <15; missing retained. All categories/models/segments are in JSON. Selected PTS illustrates the calibration failure:

| Segment | Cases | PTS MAE | PTS bias | Raw coverage | Residual coverage |
|---|---:|---:|---:|---:|---:|
| high | 892 | 6.6817 | 0.7090 | 0.8161 | 0.6379 |
| medium | 1841 | 5.0106 | -0.2699 | 0.7990 | 0.7545 |
| low | 1417 | 3.2996 | -1.1359 | 0.8200 | 0.8800 |
| unknown | 20 | 1.3000 | -1.3000 | 0.8500 | 0.9000 |

PTS paired MAE difference versus season-to-date: **-0.3335**, player-cluster bootstrap 95% interval **[-0.4336, -0.2347]**, 1,000 resamples.

#### Observed seven-day player-window

| Count | Season-to-date MAE | Selected recency MAE | Bayesian MAE |
|---|---:|---:|---:|
| PTS | 14.0238 | 13.1160 | 13.5095 |
| REB | 5.5053 | 5.1704 | 5.2567 |
| AST | 3.4612 | 3.2660 | 3.3861 |
| STL | 1.3533 | 1.3278 | 1.3392 |
| BLK | 0.9225 | 0.8957 | 0.9226 |
| 3PM | 2.0104 | 1.9125 | 2.0016 |
| TO | 1.9112 | 1.8504 | 1.8799 |
| FGM | 5.2565 | 4.9484 | 5.0908 |
| FGA | 10.4636 | 9.7587 | 10.0776 |
| FTM | 2.5573 | 2.4556 | 2.5364 |
| FTA | 3.1536 | 3.0102 | 3.1304 |

Selected recency diagnostics, nominal central 80% intervals:

| Count | Bias | Raw coverage | Residual coverage | Raw width | Common-event Brier |
|---|---:|---:|---:|---:|---:|
| PTS | -2.8546 | 0.7294 | 0.7662 | 35.4056 | 0.2622 |
| REB | -0.9804 | 0.7625 | 0.7854 | 14.3591 | 0.2544 |
| AST | -0.6934 | 0.7957 | 0.7869 | 8.8643 | 0.2565 |
| STL | -0.1466 | 0.8348 | 0.7994 | 3.5280 | 0.2534 |
| BLK | -0.0089 | 0.8864 | 0.8119 | 2.2950 | 0.2254 |
| 3PM | -0.3899 | 0.8193 | 0.7935 | 5.0288 | 0.2344 |
| TO | -0.2635 | 0.7920 | 0.7684 | 4.8326 | 0.2556 |
| FGM | -1.1074 | 0.7588 | 0.7640 | 13.1976 | 0.2629 |
| FGA | -2.3007 | 0.7279 | 0.7478 | 26.2765 | 0.2563 |
| FTM | -0.2499 | 0.8127 | 0.7972 | 6.6475 | 0.2431 |
| FTA | -0.3530 | 0.8119 | 0.8075 | 8.2670 | 0.2459 |

Shooting percentages are ratios of makes/attempts, not independent count means.

| Ratio | Targets with attempts | Season-to-date MAE | Recency MAE | Bayesian MAE | Recency bias | Raw coverage | Raw width | Brier |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FG% | 1185 | 0.1192 | 0.1221 | 0.1166 | 0.0011 | 0.7696 | 0.4154 | 0.2783 |
| FT% | 908 | 0.1773 | 0.1818 | 0.1715 | -0.0084 | 0.8491 | 0.7071 | 0.3003 |

Minute segments use origin-known mean minutes: high ≥28, medium 15–<28, low <15; missing retained. All categories/models/segments are in JSON. Selected PTS illustrates the calibration failure:

| Segment | Cases | PTS MAE | PTS bias | Raw coverage | Residual coverage |
|---|---:|---:|---:|---:|---:|
| high | 303 | 19.8918 | 1.2830 | 0.7855 | 0.5677 |
| medium | 532 | 12.8837 | -2.6455 | 0.7500 | 0.7914 |
| low | 511 | 9.5458 | -5.5305 | 0.6751 | 0.8532 |
| unknown | 10 | 2.6000 | -2.6000 | 0.7000 | 1.0000 |

PTS paired MAE difference versus season-to-date: **-0.9079**, player-cluster bootstrap 95% interval **[-1.2214, -0.5830]**, 1,000 resamples.

The intervals describe repeated-player comparison uncertainty; common calendar
shocks are not removed. All-count paired deltas are stored, but not a causal
training-size experiment. Pooling residual widths hides heterogeneity: high-minute
PTS coverage is only **63.79% per-game / 56.77% weekly** after marginal calibration.
Do not promote these widths as trustworthy nominal player-specific uncertainty.
Raw joint samples remain unchanged; no joint or matchup probability recalibration
is claimed. Brier compares `actual > floor(origin-known current-season own mean)`;
five-bin reliability, finite-draw MC SE, interval scores and calibration widths
are in JSON. Ratio zero-target-attempt cases are excluded; simulated zero attempts
follow explicit zero policy. No ratio residual calibration is fitted.

Primary PTS MAE reductions are **6.54% per-game / 6.47% weekly**. In the previously
examined 2026 replication, season/recency/Bayesian PTS MAE is
**4.7645 / 4.5179 / 4.6148** per-game and **12.8815 / 12.3285 / 12.7169** weekly.
These are broader descriptive transfer checks, not fresh confirmation. Replication
minute segments can differ by model because prior-season history differs;
compare overall common-target metrics, or within-model segments, rather than
assuming identical cross-model segmented populations. First-ever/no-history
observations, absent player-weeks and participation are not forecast targets.

### Actual current inference and complete decisions

Strict production fitting at **2026-10-13T03:40:00Z** used all **64,695** eligible
records for **697** supported historical IDs. Latest game data are April 2026;
today's roster membership and roles are unverified. Model ID:
`ef43c29259d05e398713f6fc0dd732b0960e97abb6395966b3a7fd8662bbe450`.
All 697 persisted forecasts contain eleven expected counts, joint vectors,
sample dispersion, raw and marginal residual intervals, cutoff/prediction time,
NBA ID, seed and model/dataset/code version. The prediction timestamp is the
requested origin, fixed for reproducibility; it is not a claim of earlier creation.
These are next recorded player-game forecasts **conditional on a row occurring**,
including the source's historical zero/DNP support. Unknown minutes, participation
and exposure remain unknown. Seven-day projections explicitly report unavailable
with null game count: no verified future schedule was supplied.

All eight fixture roles have exact IDs verified in source rows. Fictional ownership,
positions, roster protection, transaction limits, lineup and long-term proxies
remain labelled. Actual NBA sample vectors replace every synthetic game vector;
C++ aggregates the existing int64 interface, percentages use makes/attempts, and
TO remains lower-is-better. Native/reference categories, utility and ranked actions
match exactly. A 10k-draw integration check verifies count moments within five MC
standard errors and points arithmetic; equal inputs/versions/seed reproduce banks.
No fitting logic was added to C++ and the existing objective is unchanged.

The complete hypothetical fixture run recommends **ADD Al Horford (201143), DROP
Jeff Green (201145)**. With seed 42, 256 screening / 4,096 finalist scenarios,
matchup win probability is **18.75% HOLD → 49.90% action**; paired gain **31.15
percentage points**, paired Monte Carlo SE **0.78 points**. HOLD is retained.
There are 13 enumerated actions, three evaluated feasible actions, two refined;
protection/eligibility/value guards eliminate others. FG%, FT% and TO win chances
worsen for the selected action; the unchanged nine-category objective ranks its
net benefit. Complete categories, lineups, probabilities, rejection reasons,
provenance and sample budgets are recorded in the evidence JSON. These are
**fixture simulations, not live Yahoo recommendations or calibrated live odds**.

### Measured CPU costs and limitations

| Work | Wall seconds | Peak process memory | Scope |
|---|---:|---:|---|
| Full-population development/calibration/evaluation | 1,119.47 internal / 1,145.39 external CLI | 747.58 MiB before report serialization / 2,263,592 KiB overall | Both horizons, all candidates, held-out and replication |
| Chosen model production fit | 3.41 internal / 3.93 external CLI | 164.27 MiB | Load, 697 summaries, registry persistence |
| Prepared population summaries | 1.75 | 389.03 MiB for entire profiling process | Loading measured separately at 2.00s |
| Eight prepared player predictions | 0.0241 | Same profiling process | 256 draws each, imports excluded |
| All 697 player inference/persistence | 13.86 | Included in fresh CLI below | Full real distribution artifacts |
| Add/drop search | 0.2355 | Included in fresh CLI below | Existing screen/refine search + cache write |
| Fresh full CLI | 14.75 internal / 15.29 external | 559.32 MiB | Fit already registered; load/infer/search/persist |
| Cached full CLI | 5.71 internal / 6.31 external | 329.55 MiB | Identical saved report; no resampling or optimization |
| C++ kernel, 1k / 10k / 20k scenarios | 0.00049 / 0.00450 / 0.00920 | Banks 2.1 / 21.1 / 42.2 MB | Warmup, median three runs; preparation excluded |
| Python reference, 1k / 10k / 20k scenarios | 0.03926 / 0.39919 / 0.79219 | Same banks | Exact category parity |

Preparation is 0.064 / 0.122 / 0.197s for those scenario budgets. Imports, whole
pipeline peak RSS and CLI stdout are separate from pure kernels. Cached all-player
CLI still loads/checks input and parses large joint-sample JSON; caching avoids
inference and simulation, not serialization costs. Full original replay JSON was
318 MiB: complete cases are now deterministically compressed under ignored source
features, with case counts and SHA-256 paths in a 1.55 MB tracked metric summary.
The temporary full report serialization caused the ~2.16 GiB peak; steady fitting
and inference are much smaller. This local CPU measurement supports a practical
16 GB workload, but the owner's specific WSL2/RTX laptop was not benchmarked.
No measured reason to add GPU infrastructure. No swaps occurred.

Daily count estimates can incorporate newly known rows under the frozen config;
unchanged inputs reuse checksum-validated caches. Repeated actual train produces
the same model ID and identical registry bytes; inference/run leave it untouched.
The existing registry supports scoped all-count candidate validation and archived
rollback. Automatic retraining/promotion is explicitly disabled. Live new-season
acquisition and partial-season ingestion are absent: the historical adapter gates
two verified complete seasons. There is no claim of an operating continuous live
learning loop. Prior fixture running aggregates/incremental store remain available.

### Exact reproduction and review gate

At project root, using the existing pinned snapshot and locked environment:

```bash
export UV_CACHE_DIR=/tmp/fantasy-stage01-uv-cache
uv sync --locked --offline --group dev
uv run --offline --no-sync fantasy nba backtest
# Returns frozen report on repeat; never reselects from held-out outcomes.
uv run --offline --no-sync python scripts/summarize_nba_benchmark.py
uv run --offline --no-sync fantasy nba train --as-of 2026-10-13T03:40:00Z
uv run --offline --no-sync fantasy nba model --model-action status
uv run --offline --no-sync fantasy nba forecast --as-of 2026-10-13T03:40:00Z > /tmp/nba-predictions.json
uv run --offline --no-sync fantasy nba run --fixture --as-of 2026-10-13T03:40:00Z > /tmp/nba-decision.json
uv run --offline --no-sync fantasy nba run --fixture --as-of 2026-10-13T03:40:00Z > /tmp/nba-decision-cached.json
uv run --offline --no-sync python scripts/benchmark_nba_pipeline.py
uv run --offline --no-sync fantasy auth status
```

Defaults: `--data data/nba_data`, `--registry models/nba-registry.json`,
`--output data/nba-runs`, seed 42, 256 forecast draws and 256/4096 search samples,
C++ backend. Saved report hashes are deterministic on the tested code/native/NumPy
versions; transient timers/cache flags vary. Keep original and population research
registries/frozen evidence and compressed replays with the snapshot. Changed
code/data/protocol must use a newly declared chronological evaluation, never delete
the consumed-holdout guard to retune. Summary compression is idempotent. First
execution of the full protocol takes about 19 minutes; frozen repeat is quick.

Original 24-player regression remains **188 cases**, evidence SHA-256
`151cf5647da844f0e4bea8a62a6a653b78584cd77af8b26068e434c6b7d767e8`.
Reproduce using the original code without switching branches or modifying `dev`:

```bash
mkdir -p /tmp/fantasy-original-42a5f83
git archive 42a5f83 src/fantasy_optimizer docs/benchmarks/nba-protocol.json docs/benchmarks/nba-real-data.json | tar -x -C /tmp/fantasy-original-42a5f83
.venv/bin/python -I -S - "$PWD" <<'PYCODE'
import hashlib
import sys
from pathlib import Path
project = Path(sys.argv[1])
original = Path('/tmp/fantasy-original-42a5f83')
site = next((project / '.venv/lib').glob('python*/site-packages'))
sys.path[:0] = [str(original / 'src'), str(site)]
from fantasy_optimizer import historical_benchmark
assert Path(historical_benchmark.__file__).is_relative_to(original)
output = original / 'docs/benchmarks/nba-real-data.json'
before = output.read_bytes()
report = historical_benchmark.run(project / 'data/nba_data', original / 'docs/benchmarks/nba-protocol.json', output)
assert report['evaluation']['recency_selected']['metrics']['cases'] == 188
assert output.read_bytes() == before
print(hashlib.sha256(before).hexdigest())
PYCODE
```

This verifies the original frozen replay guard/evidence and unchanged input/code
identity; it does not reopen that consumed period to tune or resample. On a fresh
research state the original command reproduces its frozen protocol instead.

Verification: Ruff lint/format **44 files**, mypy **26 source files**, targeted
real-distribution tests **10 passed**, final full suite **213 passed in 63.62s**,
Debug CMake configure/build, tracked C++ clang-format and **3/3 standard CTest with
full sanitizers/leak checks**. Restricted socket/LeakSanitizer failures were
investigated; unchanged approved unrestricted runs passed. No diagnostics suppressed
or tests skipped locally. Independent compressed replay checks verify all model
targets/outcomes/thresholds/counts and checksums; repeated current model/decision
artifacts and original evidence stayed unchanged. No changed C++ requires fresh
clang-tidy. Pure-Python changes used installed CLI; no wheel rebuild or remote CI
is claimed. Exact engineering commands:

```bash
uv run --offline --no-sync ruff check .
uv run --offline --no-sync ruff format --check .
uv run --offline --no-sync mypy src
uv run --offline --no-sync pytest -q
cmake -S cpp -B build/cpp -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build/cpp
ctest --test-dir build/cpp --output-on-failure
git ls-files -z -- '*.cpp' '*.hpp' | xargs -0 -r clang-format-14 --dry-run --Werror
git diff --check
```

**Stop at owner review.** Next milestone: verified new-season acquisition/schedule,
current roster/participation and authorized Yahoo identity/rules, followed by a new
chronological protocol for subgroup/ratio/joint calibration. Credentials are
`missing_auth` with no approved/network-checked live scope; no live recommendation,
transaction, main merge, external push or publication occurred.


Advanced forecasting milestone (2026-10-13): [actual LightGBM/PyTorch training,
fresh chronological comparisons, conditional minutes/rates/uncertainty and native
fixture integration](ADVANCED_FORECASTING.md) are complete. The selected candidate
fails its frozen practical promotion threshold; recency and previous evidence
remain unchanged. No Yahoo integration or real future schedule was added.
