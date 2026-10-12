# Stage 03 — Day-one probabilistic player forecasting

**Goal:** useful, calibrated baseline before adding complex ML.

## Implement

- Implement point-in-time data splits and baseline forecasting for Yahoo-available stat granularity. Use recency-weighted estimates, regression to defensible priors and availability/game-count proxies when verifiable.
- Model makes and attempts (FGM/FGA, FTM/FTA) separately; simulate/count 3PM, PTS, REB, AST, STL, BLK and TO. Avoid naive independent category assumptions. When game-level history is absent, be explicit about coarser forecasts and uncertainty.
- Build two simple baselines (long-run mean, recency-weighted) plus empirical-Bayes shrinkage; benchmark them before any new model.
- Keep lightweight per-player running aggregates for fast daily updates; maintain feature snapshots tied to `as_of` and code version.
- Implement a stable forecast output contract, versioned model artifacts, fixed RNG seed and `fantasy forecast --fixture`.
- Historical evaluation: time-ordered rolling origins, MAE where appropriate, interval coverage and probabilistic calibration where sample permits. Separate model errors from Monte Carlo error.

## Acceptance criteria

- All forecasts are computed using only records known at forecast time.
- Tests cover missing data, small samples, makes/attempts integrity, shrinkage, deterministic reruns and forecast serialization.
- Document objective benchmarks and failure cases; do not assert model quality without numbers.
- Update `STATUS.md` with active baseline and data constraints.
