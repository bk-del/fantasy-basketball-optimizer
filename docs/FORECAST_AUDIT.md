# Forecasting audit — 2026-10-12

Current end-to-end audit and connections: [real NBA pipeline](REAL_DATA_PIPELINE.md).

Historical audit record: the owner subsequently authorized and completed the
[historical integration and real-data benchmark](HISTORICAL_FORECAST_BENCHMARK.md).
The findings below describe the pre-integration system; current NBA adapter,
configuration, actual measured results and remaining limitations are in that report.

The forecasting machinery is implemented and tested, but it does **not** yet use
the downloaded NBA game history. Existing results describe synthetic weekly
counts. This audit stays within the approved Stage 09 data preparation work:
verification, evidence and a concrete follow-up proposal. No forecasting model,
active registry, runtime source or optimizer objective was changed.

Read the Stage 02, 03, 06 and 07 implementation guides and inspected storage,
forecasting, context, replay, registry, CLI and pipeline boundaries, their tests
and the associated implementation documentation. The pinned NBA snapshot is
[prepared separately](../fantasy-basketball-optimizer-guides/docs/NBA_DATA.md).

## Requirements and implementation findings

| Requirement | Verified implementation | Missing or constrained |
|---|---|---|
| Historical NBA integration | Offline DuckDB views over verified Parquet, manifest and schema/quality report | No NBA-to-forecast adapter or Yahoo/NBA identity crosswalk. Forecasts still load `fixtures/forecast.json`; game optimizer uses independently handmade samples. |
| Stable identifiers | Storage keys source/league/entity; forecasting groups by `player_key`; NBA logs retain `personId`, `teamId` and string `gameId` | Yahoo player keys and NBA IDs are different namespaces. Names are display fields, not model inputs. Cross-season Yahoo correspondence is unverified. |
| Player/team histories | Raw seasonal exports retained for 2010–2026; team game logs retain team IDs, game dates and season labels. Same NBA person IDs occur on multiple teams across the 2025/2026 files. | No canonical stint/season entity or exposure-aware joins. Raw position/team strings are not a reliable fantasy eligibility contract. Older player logs are sparse and duplicated. |
| Temporal integrity | `Store.as_of` checks observation/ingestion; `known_windows` also checks completed event end, then resolves only known revisions. Replay refits at each origin. | Snapshot retrieval is not historic publication time. Raw offline SQL has no automatic as-of guard; the catalog must not be fed directly into historical features. |
| Exponential recency | Both forecast weights and running aggregates decay exponentially with 28-day half-life | Global `CONFIG`, no validated per-run configuration or CLI half-life setting; no half-life walk-forward comparison. |
| Bayesian shrinkage | Optional empirical-Bayes approximation over contemporaneously known peers; finite effective sample size and explicit no-peer fallback | Default recency does not shrink. Prior mixes heterogeneous weekly player totals, not role/exposure-matched peers or an own-player long-term component. |
| Role changes | Four baseline weeks versus two recent weeks, sustained PTS thresholds and standardization; isolated spike/noisy shift tests | Count-only diagnostic, no minutes/opportunity model, adaptive forgetting or formal change-point posterior; does not alter forecasts. |
| Minutes and production | Missing minutes/exposure explicitly null; no fabricated per-game projections | No separate minutes and per-minute models. NBA minutes are text and need validated parsing/participation semantics. |
| Cross-player/season learning | Shrinkage pools other players' counts with equal total mass per peer; identifiers only group/seed streams | No real cross-season evaluation, contextual similarity, team/teammate feature learning, embeddings, neural network or graph database. |
| Validation | Expanding chronological replay, earlier residual calibration, later validation and reserved final holdout; guarded manual promotion/rollback | True current-season baseline, half-life tuning, adaptive model and real NBA evaluation absent. Only fixed PTS MAE controls fixture promotion. |
| Lightweight updates | O(11) new-window aggregate update; content-addressed caches; daily runs do not train or mutate registry | Each forecast still filters history, rebuilds aggregates and constructs samples. Cache invalidation can scan all rows; no measured large-history RAM/time budget. |

The NBA identity audit records multi-team stable person IDs and all team-season
coverage in [saved evidence](benchmarks/forecast-audit.json). This verifies that
raw history survives trades/seasons in the snapshot; it does not verify upstream
accuracy against official records or map anyone to a Yahoo identity. Player-log
2025/2026 keys have no duplicate/null identifiers. 2010–2024 logs cover just 4–15
distinct games per file with repeated keys. Downloaded years are not equivalent
to complete seasons. Preserve questionable rows and gate usable partitions rather
than silently inventing or repairing history.

## Mathematics already used

For completed weekly counts `x_i` ending at `t_i`, forecast origin `T` and fixed
half-life `h=28` days:

```text
w_i = 2^(-(T - t_i) / h)
a_i = w_i / sum(w_i)
recency_mean = sum(a_i * x_i)
long_run_mean = sum(x_i) / n
n_eff = 1 / sum(a_i^2)
alpha = n_eff / (n_eff + k)
shrinkage_mean = alpha * recency_mean + (1-alpha) * peer_mean
```

An observation 28 days old has half the unnormalized mass of an otherwise equal
observation ending now; at 56 days it has one quarter. These are ratios before
normalization, not percentages of the whole history. `long_run` weights all known
windows equally; it is **not** a season-average baseline because `Window` has no
season boundary. `recency` already is the fixed exponential-decay model, so a
second separately named fixed-decay implementation would duplicate it.

The peer mean gives each other player equal total mass, each of that player's
windows equal mass. Peers pass the same origin-known filtering. Prior strength
`k` is an approximate within-player variance/between-player signal moment ratio,
clipped to 2–20 pseudo-windows; absent peers yield no invented prior. This is an
empirical-Bayes approximation, not a fully fitted hierarchical posterior. The
prior does not retain a separate long-run component of the target player's own
history; older own observations keep exponentially diminishing mass.

Forecast uncertainty uses weighted whole-vector empirical resampling plus a
shared heuristic exposure multiplier, wider for fewer than three observations.
Makes/attempts and count dependence are preserved, and sampled PTS is recomputed
from makes. Rounded sample moments can differ from analytic expected counts.
Monte Carlo SE describes sampling precision, not model calibration. Tail support
and contextual dependence remain limited. Missing counts in any support row can
withhold the corresponding forecast statistic; heterogeneous peer missingness can
therefore reduce shrinkage coverage.

The shift diagnostic compares recent/baseline PTS means with
`sqrt(var(old)/n_old + var(recent)/n_recent)` and a one-point denominator floor.
Both recent weeks must exceed the fixed 25% gain. This guards against a single
spike but weekly game-count changes remain confounded with role/productivity.
The diagnostic neither learns a change point nor changes the decay rate.

Calibration fits an 80% absolute-residual quantile on earlier calibration cases,
using rank `ceil((n+1)*0.8)` and at least eight cases. Later validation evaluates
marginal coverage and count MAE. Calibrated widths do not replace joint predictive
samples. No live matchup/breakout probability calibration exists.

## Actual comparison, unchanged models

Re-executed existing implementations with seed 42 and 256 samples. No registry
write, model training/promotion, final-holdout opening or NBA forecast occurred.
Full per-stat results, source hashes and NBA manifest hash are saved in
[forecast-audit.json](benchmarks/forecast-audit.json).

| Existing model | Rolling PTS MAE, 40 synthetic cases | Rolling FGA MAE | Rolling TO MAE | Later PTS MAE, 8 synthetic cases |
|---|---:|---:|---:|---:|
| Equal-weight long-run | 9.2438 | 8.4635 | 0.8409 | 9.2361 |
| Fixed 28-day recency | 7.7342 | 7.0440 | 0.8644 | 6.7560 |
| Fixed recency + peer shrinkage | 9.1400 | 7.8606 | 0.9149 | 7.2909 |
| Current-season average | Not implemented | — | — | — |
| Adaptive recency | Not implemented | — | — | — |

These reproduce earlier evidence. Recency's rolling synthetic PTS error is about
16.3% lower than equal-weight history; its TO error is higher. All rolling raw
80% intervals cover 100% of these toy targets, indicating conservative intervals,
not demonstrated 80% calibration. Later residual-calibrated PTS coverage is 8/8
for each model; repeated fictional players and such small samples do not prove
calibration or generalization. Real NBA out-of-sample improvement is **unmeasured**;
this audit introduces no new model improvement. Keep the existing provisional
recency default and do not promote shrinkage or an adaptive model from these data.

Existing threshold Brier events use each model's own forecast-mean threshold.
They are diagnostic scores for different events, not a fair head-to-head
probability comparison. A future comparison should freeze common origin-known
thresholds across models and also score intervals/distributions for sharpness.
No model ranking from these Brier values is justified.

## Verification added without changing forecasts

`tests/test_forecasting_audit.py` adds seven checks: hand-calculated 7/28/56-day
relative weights and running-aggregate agreement; predictive-mean invariance to
identifier relabeling for all three models; and exclusion/admission of a highly
influential peer correction at observation/ingestion boundaries. IDs deliberately
change RNG streams and provenance; they do not enter predictive means. Existing
tests already cover revisions, future outcomes, temporal storage queries, missing
counts, sustained versus transient shifts, deterministic serialization, holdout
reservation and registry safeguards; these were reused rather than duplicated.

## Proposed next work, requiring a separate approved scope

1. **Integration and time contract first (Stage 02 responsibilities).** Establish
   canonical `(source, nba_player_id)`/NBA team IDs and versioned exact Yahoo/NBA
   crosswalk; never name-only joins. Retain game/player/team/season history and
   separate event dates, first observed time, ingestion and correction revisions.
   Validate counts, minutes, game type, stints, duplicate conflicts and date joins.
   Use 2025/2026 only after a coverage audit; quarantine incomplete older partitions.
   Snapshot-based retrospective research must explicitly disclose absent historical
   publication times, and cannot masquerade as faithful point-in-time replay.
2. **Configuration and baselines (Stage 03/07 responsibilities).** Reuse existing
   decay and shrinkage; introduce an immutable validated config carried through
   forecast, aggregate, CLI, cache hashes and registry. Register a small half-life
   grid (7/14/28/56/112 days) before evaluation. Compare an origin-only season
   average, equal-weight history, fixed-decay candidates and shrinkage. Choose on
   chronological development folds, calibrate on later data, validate on a still
   later period and reserve a fresh final holdout. The existing fixture holdout
   has only two weeks and is not an NBA holdout. Do not tune on final outcomes.
3. **Exposure and role model (Stage 06 experiment).** Forecast participation/minutes
   separately from per-minute raw production. Preserve zero-minute DNP versus
   unknown exposure; never divide by zero or interpret absence as a low rate.
   Use known minutes/attempt opportunities with sustained-change evidence before
   adapting half-life. First compare a bounded two-window shift rule against fixed
   decay; quantify isolated-spike false alarms and sustained-shift recovery.
   Couple minutes/rate draws coherently and retain count/makes constraints.
4. **Useful historical priors/context (Stage 06/07 experiment).** Benchmark own-player
   long-term shrinkage and simple role/exposure-matched peer priors before more
   complex models. Use only reliably dated team/stint and teammate exposure at
   origin, annotate ambiguity/coverage, and avoid causal injury claims. Evaluate
   similarity based on minutes/rates/opportunity rather than names or numerical
   ID values. Test later seasons and sparse/new players separately; no embeddings,
   GNN, neural network or graph database is justified yet.
5. **Measured acceptance and rollback.** Bound DuckDB queries to approved partitions;
   avoid loading all observations per player repeatedly. Reuse incremental sums
   and revision-aware invalidation, with explicit daily inference versus training.
   Predeclare all-count MAE, common-event Brier, interval coverage/width and role-
   change subgroup metrics, chronological folds and an acceptable resource budget
   measured on the owner's 16 GB laptop. No GPU is needed for these baselines.
   Promote only on later-period evidence with uncertainty; otherwise retain the
   simpler incumbent. Keep old configuration/registry for explicit rollback.

The next exact task is owner review of this audit and selection of the integration
and temporal contract scope before introducing any forecasting improvement. No
new stage is automatically started.


Advanced forecasting milestone (2026-10-13): [actual LightGBM/PyTorch training,
fresh chronological comparisons, conditional minutes/rates/uncertainty and native
fixture integration](ADVANCED_FORECASTING.md) are complete. The selected candidate
fails its frozen practical promotion threshold; recency and previous evidence
remain unchanged. No Yahoo integration or real future schedule was added.
