# Stage 07 — Fast retraining, calibration, model registry and walk-forward evaluation

**Goal:** reliable continuous improvement without long mandatory training windows or overfitting.

## Implement

- Separate quick daily running-stat updates from periodic LightGBM/full-model retraining and infrequent policy-parameter tuning. Training is NOT part of normal `fantasy run` unless explicitly requested.
- Implement small active/candidate/archived model registry: model version, config hash, dataset watermark, training cutoff, metrics and promotion reason; atomic promotion/rollback.
- Implement time-respecting replay with an `as_of` guard, and never reconstruct historical waiver availability using today's roster. Where old availability snapshots do not exist, scope backtests to forecasting or label the decision replay incomplete.
- Calibrate prediction intervals/probabilities on chronologically later evaluation data. Prefer a simple ensemble only if it beats its constituent baselines out of time.
- Compare new models to incumbent and baselines; protect an untouched final holdout against repeated Optuna tuning. Keep training budgets configurable, early stopping and deterministic seeds.
- Log recommendation outcomes and model uncertainty, but don't treat one lucky/unlucky outcome as proof a policy is good/bad. Counterfactual transactions are approximations.

## Acceptance criteria

- `fantasy train --fixture`, `fantasy backtest --fixture`, model status and rollback work offline.
- Repeated `fantasy run` leaves models unchanged. A worse candidate isn't auto-promoted; promotion and rollback are tested.
- Measured training duration/storage size and reasons for active-model selection are reported.
- Update `STATUS.md`.
