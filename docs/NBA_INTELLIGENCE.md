# Comprehensive NBA intelligence checkpoint

Work paused at the owner's usage-budget instruction on 2026-10-13. The
comprehensive milestone is **incomplete**. No full-data GRU/GNN fit, new feature
dataset, relational snapshot, model comparison or historical decision replay has
been executed. Recency remains active. Existing trained challengers, feature
caches, registries, raw data and frozen evidence are preserved.

The [data audit](NBA_INTELLIGENCE_DATA.md) identifies and actually loads six
complete cached ESPN seasons: 153,546 player-game rows and 1,150 NBA IDs. The
source already existed locally; no new raw data was downloaded. Incomplete
2020/2026 ESPN partitions are rejected. The older two-season NBA source and its
incumbent pipeline are unchanged. A historical box-score starter/played field
does not establish pregame availability, and missing rows never establish injury.

Three isolated modules and their focused tests are implemented:

| Component | Verified behavior | Still required |
|---|---|---|
| `intelligence_data.py` | Immutable manifest verification, coverage/identity gates, exact team joins, coherent counts, strict retrieval and explicit assumed historical availability, six-season loading | Versioned relationship and feature materialization; historical publication/availability evidence |
| `relational_models.py` | Small GRUCell sequence encoder, genuine one-hop GraphSAGE mean aggregation, MLP comparison, deterministic tiny real fits, chronological early stopping, training-only scalers, finite gradients, JSON roundtrip, valid expected counts | Real origin-safe sequence/node/edge dataset; actual NBA training/evaluation/calibration and performance measurements |
| `decision_replay.py` | Registered hypothetical league replay, same legal actions including HOLD, origin-only pools, historical exposure bootstrap, existing nine-category comparison, separate future outcomes, tiny contract tests | Execute real historical replay, inspect results, connect future origin-safe GRU/GNN forecasts |

The [decision protocol and command](NBA_DECISION_REPLAY.md) are preserved; its
[evidence placeholder](benchmarks/nba-decision-replay.json) explicitly says
`NOT_EXECUTED`. No decision-performance metrics exist for this new replay.

## Resume commands

Run from the repository root on `dev` after the owner resumes work:

```bash
export UV_CACHE_DIR=/tmp/fantasy-stage01-uv-cache
export OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
uv sync --locked --offline --extra advanced --group dev
git status --short --branch
uv run --offline --no-sync python scripts/audit_nba_intelligence_data.py
uv run --offline --no-sync pytest tests/test_intelligence_data.py tests/test_relational_models.py tests/test_decision_replay.py -q
# First actual historical decision replay; no training:
uv run --offline --no-sync python scripts/backtest_nba_decisions.py
# Only if ignored frozen research artifacts are absent; rebuild exact OLD models:
uv run --offline --no-sync python scripts/rebuild_advanced_models.py
```

The audit rewrites its deterministic coverage report. The replay command replaces
the explicit not-executed placeholder with real measured results; do this only
after resumption. Preserve the registered protocol and inspect missing-artifact
errors before rebuilding old models. No new GRU/GNN training CLI exists yet.

The expanded loader API is:

```python
from pathlib import Path
from fantasy_optimizer.intelligence_data import observations

records, provenance = observations(
    Path("data/nba_data"), policy="retrospective_next_day"
)
```

This reconstructs validated arrays from existing immutable Parquet, rather than
persisting a duplicate raw store. Default strict mode gates rows at actual
retrieval. The explicit historical mode assumes next-date noon UTC and retains
real ingestion separately; it cannot reconstruct publication or revision history.

## Next exact implementation work

1. Freeze a new research protocol **before fitting any new NBA challenger**.
   Previous 2025/2026 benchmark periods are examined. Newly audited older seasons
   have no model benchmark yet; decide chronological development/calibration/final
   boundaries explicitly, accounting for the missing 2019–20 ESPN partition and
   changed source-row semantics. No newly frozen forecasting protocol exists yet.
2. Implement a separate versioned relationship/feature builder over the expanded
   loader. Use source NBA IDs, observation-time membership, staleness and only
   origin-known teammate edges. Do not use current target-team/starter/played
   outcomes as pregame features. Persist Parquet relationship snapshots and
   checksum-validated feature tensors with leakage tests.
3. Match the existing learner API below. Start with small build/timing checks,
   then contextual LightGBM, MLP, GRU and graph comparisons under the frozen
   chronological protocol. Do not modify prior scientific files or guards.
4. Evaluate high-minute uncertainty and realistic joint scenarios; only then
   integrate validated forecasts through the existing C++ contract. The incumbent
   remains approved until appropriate independent promotion evidence exists.
5. Execute and inspect the preserved hypothetical decision replay, add forecasts
   through its `forecast_provider` hook with training cutoff and checksum, run
   engineering checks, report limitations and stop at final owner review.

The new learner contract is
`fit_relational(data, indices, config, validation_indices=None, seed=42, threads=2)`
and `predict_relational(artifact, data, indices)`. Import from
`fantasy_optimizer.relational_models`. Config `kind` is `mlp`, `gru` or `graph`;
defaults are hidden 32, maximum 20 epochs, patience 3, batch 256, learning rate
.001, weight decay .01 and gradient clip 5. No hyperparameter search has run.

Common arrays: `x[N,F]`, `base[N,13]`, `y[N,13]`, `weights[N,13]` using the existing
conditional component definitions. For GRU add `sequence[N,T,D]` and binary
`sequence_mask[N,T]`; for graph add `node[N,D]`, `neighbors[N,K,D]` and binary
`neighbor_mask[N,K]`. Supply `cases` with `as_of`/`outcome_available` for temporal
validation. Proposed builder sizes, **not implemented**, are T=8, K=20, D=13
(eleven lagged counts, known minutes, minute-missing flag). The returned artifact
stores model weights, scalers, config, training/validation support, early stopping
history and gradient diagnostics. Inference returns components, nonnegative
shooting primitives and coherent raw counts without reading labels.

All actual check outcomes, stopped/running state, preserved artifact hashes and
commit information belong to the existing single handoff:
[STATUS.md](../fantasy-basketball-optimizer-guides/STATUS.md).
