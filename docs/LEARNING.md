# Offline learning and model lifecycle

Stage 07 evaluates existing handmade weekly counts, with no Yahoo request or new
dependency. `train`, `backtest`, `run` and `model` require `--fixture`. These are
forecasting experiments: historical waiver availability/ownership is absent, so
reports label decision replay incomplete. Today's roster never reconstructs a
past pool. No transaction counterfactual score or live improvement is claimed.

## Registry and commands

```bash
uv run fantasy train --fixture --model long_run --registry /tmp/models.json
uv run fantasy model status --fixture --registry /tmp/models.json
uv run fantasy model promote --fixture --registry /tmp/models.json --id CANDIDATE_HASH
uv run fantasy model rollback --fixture --registry /tmp/models.json
uv run fantasy backtest --fixture --registry /tmp/models.json
uv run fantasy run --fixture --registry /tmp/models.json
uv run fantasy backtest --fixture --registry /tmp/models.json --final-holdout
```

The default registry is ignored `models/fixture-registry.json`. Status and run
never create or modify it, including before initialization. Train initializes the
Stage 03 recency incumbent and records a content-addressed candidate. Metadata
includes model/code/config versions and hashes, selection dataset watermark,
initial training cutoff, split boundaries, deterministic budget, validation
metrics, interval calibration and promotion reason. Training duration and actual
registry bytes are returned by train; timing does not affect model identity.
Repeated identical training is idempotent.

Promotion is manual and atomic. The candidate must share the incumbent's dataset,
code and evaluation config, strictly improve later validation PTS MAE, and match
or beat all three baselines on that fixed metric. This single-stat fixture criterion
is not a live 9-CAT policy objective. Worse/tied candidates stay candidates; training
never promotes. Promotion archives the previous active model and records it for
rollback. Rollback restores that model in the same atomic write. No earlier active
model produces a clear refusal. Current fixtures do not beat the recency incumbent;
meaningful promotion/rollback paths use handmade comparative records in tests.

The registry is a small **single-writer manual CLI** document. Writes use a temporary
file in the same directory, flush/fsync the file and atomically replace the whole
registry. An interrupted replacement preserves the previous file and removes the
temporary file. No simultaneous-writer service or power-loss directory durability
guarantee is claimed. Invalid registry state refuses overwrite. Retain the registry:
deleting/replacing it or creating another path defeats its local experiment audit.

Daily runs select the frozen active model/seed/sample budget, use existing quick
running-stat forecasts and write no model artifacts. The tiny fixture history is
rebuilt in memory; no new persistent feature cache is justified. No full retrain
is part of normal run. Explicit train refits inexpensive baselines at origins.
Periodic LightGBM retraining, probability calibration and Optuna policy tuning are
skipped for insufficient verified histories/labels; no new libraries are installed.
There is no iterative learner requiring early stopping. Configurable hard limits
replace unbounded experimentation: seed 42, samples 256 (32–1024), cases per replay
32 (8–128), registered candidates per dataset 3 (1–3). Exceeding limits refuses
rather than truncating. Changing budgets cannot make evaluations comparable to an
incumbent trained under another config.

## Chronological evaluation and uncertainty

The fixed twelve-week fixture starts 2026-06-01 UTC. First six weeks form initial
history (cutoff July 13); weeks 7–8 calibrate (through July 27); weeks 9–10 validate
(through August 10); weeks 11–12 are final holdout (through August 24). Each later
origin expands its count history only with completed, observed and ingested windows
known by that origin. Revision filtering occurs before selection. Outcome hashes
are separate from origin input hashes. No shuffled splits.

Calibration uses only the earlier calibration period: per-stat absolute residuals,
fixed 80% finite-sample quantile rank `ceil((n+1)*0.8)`, minimum eight usable cases.
Insufficient counts produce null widths. Later validation reports raw and calibrated
marginal interval coverage and MAE for all eleven raw counts. Calibrated intervals
are `max(0, mean-width)` to `mean+width`; they are diagnostic, not a replacement joint
sampler or independent percentage distributions. Eight cases with repeated fictional
players cannot prove real-world calibration. Matchup/breakout probabilities lack
verified outcomes, so calibration is explicitly null. No ensemble is fit or promoted
without adequate out-of-time evidence over constituents.

Training and ordinary backtest never inspect final outcomes. Opening the final
holdout requires an initialized active model and its frozen budget. The registry
consumes the holdout **before** exposing outcomes, refusing a second opening and
further training/promotion in this registry. A failed final evaluation still consumes
the period: use a genuinely later period rather than repeated inspection. Final
reports identify the active model and show baseline comparisons. Operational rollback
and read-only runs remain available; final scores must not guide another candidate
on the same period. A later real dataset/period needs a separately reviewed protocol;
this stage does not implement live retraining.

See [saved fixture results](benchmarks/stage07.json) for actual selection scores,
calibration widths, measured training duration and registry storage. Synthetic
coverage and lower error on a smooth toy trend are not live quality guarantees.

## Compact observed-outcome log

```bash
uv run fantasy model log-outcome --fixture --outcome /tmp/outcome.json
```

Use the same `--registry` as the corresponding model. The proposed JSON contract
requires `decision_run_id`, `model_id`, timezone-aware `as_of`, later `evaluated_at`,
`predicted_utility` (0–1), `mc_se` (0–0.5), `model_uncertainty` (explicit text),
`observed_outcome`, `confounders` (list of strings) and `counterfactual` (boolean).
The entry is idempotent by run ID; a conflicting outcome requires an explicit
revision rather than silent overwrite. Outcome logs never promote or penalize a
model. A single lucky/unlucky win says little about policy quality. Counterfactual
transactions remain approximations, even if an outcome is logged. No live decision
outcome ingestion or new DuckDB migration is asserted; this is a fixture contract.
