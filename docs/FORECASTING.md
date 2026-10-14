# Stage 03: weekly count baselines

Conditional actual NBA per-game forecasts and full-population validation now use
[the real-data pipeline](REAL_DATA_PIPELINE.md); this page retains the original fixture contract.

This page describes the original fixture path. The authorized NBA research path
now reuses this engine; see the [historical benchmark](HISTORICAL_FORECAST_BENCHMARK.md)
for the adapter, temporal assumptions and real-data results. Fixture/live command
behavior remains as documented below.

This is an offline, synthetic baseline. Live Yahoo access, comparable weekly
history and schedule/availability fields remain unverified. `forecast.json`
contains 48 handmade seven-day vectors for four fictional players. It is separate
from Stage 02's single season-window fixture; season totals are never divided
into made-up weeks or games. No training dataset from outside Yahoo is used.

## Contract and time semantics

Contract version 1, model `weekly-counts-v1`, feature `weekly-aggregates-v1`.
The next seven days are a **weekly aggregate**, not a player-game prediction.
Output includes raw FGM/FGA, FTM/FTA, 3PM, PTS, REB, AST, STL, BLK and TO;
expected counts; correlated integer samples; empirical 80% intervals; Monte Carlo
standard errors of sampled means; seed; input/config hashes; missingness;
feature snapshot and assumptions. FG%/FT% are not predicted or averaged
independently. Later consumers must aggregate makes/attempts, including a defined
zero-attempt policy. Game count, minutes and availability probability stay null.

A window enters training only when its end, observation and local ingestion
are all at or before `as_of`. Latest *known* revisions replace old values;
future corrections do not rewrite past forecasts. Duplicate identical windows
are ignored; conflicting equal-time revisions and overlapping windows fail.
Only disjoint seven-day windows are supported. Noninteger/negative counts,
makes exceeding attempts, threes exceeding makes and inconsistent PTS fail.
Missing counts remain null; if either make/attempt field is missing, both are
withheld. No missing field becomes zero or an invented league scoring category.

## Baselines and priors

- Long-run: equal-weight mean of the player's known windows.
- Recency: exponential weights, half-life 28 days.
- Shrinkage: recency mean mixed with contemporaneous peer means. Each other
  player has equal prior mass, regardless of its history length. A clipped
  moment estimate of within-player noise / between-player signal determines
  2–20 pseudo-windows of prior strength. Effective player sample size is
  `1 / sum(normalized_weight**2)`; own mass is `n_eff / (n_eff + strength)`.
  This is a pragmatic empirical-Bayes approximation, not a fitted injury model.
  Without peers, fall back explicitly to recency rather than inventing a prior.

`RunningAggregate.update` maintains count totals and decayed sufficient statistics
in O(number of stats) for a new completed window. Updates must be chronological;
revised histories rebuild selected aggregates. Saved feature arrays are copies,
so later updates cannot mutate an earlier snapshot. The fixture CLI rebuilds a
small history; persistent incremental-cache infrastructure is deliberately deferred.

Prediction resamples whole player/peer vectors with their fitted weights. This
preserves observed within-vector dependence; it does not estimate a full
parametric covariance model. A shared exposure multiplier (0.75/1/1.25; wider
0.5/1/1.5 with fewer than three own windows) accounts heuristically for unknown
schedule/availability. All categories share the multiplier; PTS is recomputed
from sampled makes when those counts exist. This widens uncertainty without
inventing a specific future game count or availability probability. It is not
learned or calibrated. Player RNG streams are deterministically derived from the
root seed and player key; equal sample indices do not intentionally impose
cross-player dependence.

## Reproducibility and artifacts

```bash
uv run fantasy forecast --fixture
uv run fantasy forecast --fixture --benchmark
uv run fantasy forecast --fixture --model shrinkage --seed 42 --samples 256
```

Artifacts under ignored `models/weekly-counts-v1/` are named by a SHA-256 of the
canonical report; `--output DIRECTORY` overrides the destination. Each artifact
contains all forecast/feature snapshots, code hash, configuration, model version
and input hashes. It has no nondeterministic creation timestamp. Same input,
configuration and seed produce byte-identical artifacts; changed inputs/config
produce new identities. Samples are bounded to 32–10,000. Model/source version
changes must be reviewed together; do not silently replace an active live model.

## Measured synthetic rolling-origin comparison

The following numbers are from the actual final local benchmark, seed 42,
256 joint samples, 40 one-window-ahead forecast cases per baseline (10 origins
for each of four players). Each prior is refit only on records known at the
origin. Targets are held-out later weekly windows. These are toy implementation
benchmarks, not evidence of real Yahoo accuracy or calibration.

| Model | Stat | MAE | 80% interval coverage | Threshold Brier | Mean probability MC SE |
|---|---|---:|---:|---:|---:|
| long_run | PTS | 9.2438 | 1.000 | 0.2802 | 0.0308 |
| long_run | FGA | 8.4635 | 1.000 | 0.2860 | 0.0307 |
| long_run | TO | 0.8409 | 1.000 | 0.2239 | 0.0310 |
| recency | PTS | 7.7342 | 1.000 | 0.2461 | 0.0308 |
| recency | FGA | 7.0440 | 1.000 | 0.2713 | 0.0309 |
| recency | TO | 0.8644 | 1.000 | 0.2263 | 0.0311 |
| shrinkage | PTS | 9.1400 | 1.000 | 0.2575 | 0.0310 |
| shrinkage | FGA | 7.8606 | 1.000 | 0.2721 | 0.0311 |
| shrinkage | TO | 0.9149 | 1.000 | 0.2648 | 0.0310 |

Recency is the provisional default: it reduces PTS/FGA point error on this toy
trend. Shrinkage is available for comparison and sparse-player behavior, but is
not promoted as a superior model. TO error does not improve with recency.
The exposure proxy produces overly conservative intervals on these smooth
fixtures. Neither nominal 80% intervals nor synthetic Brier values establish
real-world calibration. Before any live use, evaluate on verified point-in-time
Yahoo history with enough independent observations and revisit exposure/priors.

Threshold Brier evaluates `count > floor(origin_forecast_mean)` with that threshold
fixed before seeing the target; report per-stat sample counts. Monte Carlo SE
concerns finite sampling, not model error or forecast calibration. Coverage's
plug-in binomial SE is only a rough diagnostic: observations share players and
all-covered cases can yield a zero plug-in SE without proving perfect coverage.
No reliable calibration curve or matchup-win probability is claimed.

Failure cases include small/absent histories, missing shooting attempts, stale
or incomparable windows, pooled priors for unlike player roles, structural trends,
unverified schedule/availability and weak empirical tail support. Warnings and
missingness stay in the output. No forecasts from live Stage 02 storage are
produced until a verified adapter establishes coverage and point-in-time identity.
Stage 04 matchup simulation and roster optimization are not implemented.


Advanced forecasting milestone (2026-10-13): [actual LightGBM/PyTorch training,
fresh chronological comparisons, conditional minutes/rates/uncertainty and native
fixture integration](ADVANCED_FORECASTING.md) are complete. The selected candidate
fails its frozen practical promotion threshold; recency and previous evidence
remain unchanged. No Yahoo integration or real future schedule was added.
