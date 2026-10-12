# Engineering and design rules

## Priorities

Correct forecasts and matchup arithmetic > point-in-time data integrity > calibrated uncertainty > reproducibility > measured performance > abstraction. Build the smallest credible system; no speculative general-purpose framework.

## Boundaries

- Data acquisition cannot depend on forecasting or optimization.
- Data model separates observed event time, publication/observation time, and ingestion time. Never backfill newly discovered status into historical features as though known earlier.
- Forecasters output a stable **joint player-game forecast contract** containing expected raw counts/makes/attempts, minutes/availability assumptions, uncertainty, and model version. No independent FG%/FT% averaging.
- Simulator consumes distributions/samples, not an LLM explanation; action optimizer consumes simulated matchup outcomes and Yahoo constraints.
- An explanation is generated from the same decision inputs/results, never as an independent guess.

## Data source realism

Yahoo-only is binding. Yahoo fantasy fields may provide scoring totals and player statuses, but not enough to infer precise teammate absences, starting lineups, usage, or official game-by-game injuries. Audit first; add only grounded proxy features (e.g. games played, recent production, status, roster changes) unless Yahoo exposes more. Missing context must widen uncertainty, not become made-up certainty.

## Lightweight storage

- Primary DuckDB file under `data/` ignored by Git. Partitioned Parquet only for data with clear size/query benefit; avoid a second source of truth.
- Stable Yahoo resource identifiers. Unique keys for games, player observations, roster changes and forecast/run versions. Deduplicate/upsert idempotently.
- Retain compact raw API snapshots only as needed for debugging/data provenance; redacted and compressed with retention policy.
- Snapshot roster ownership, waiver availability and scoring rules **as observed**. Availability cannot be perfectly reconstructed from current data.
- Cache derived features under explicit code version and input-watermark IDs; invalidate when data changes.

## Runtime and training

- Manual CLI first: `fantasy sync`, `forecast`, `optimize`, `run`, `status`, `train`, `backtest` when implemented.
- Daily: refresh and re-forecast. Weekly: candidate full retrain only if enough new observations; active model continues while training/evaluation proceeds. Avoid retraining on every run.
- Fast online updates: regularized recency estimators and sufficient-statistic aggregates. Gradient-boosted models are periodically fully retrained; warm-start is an experiment, not assumed to be sound online learning.
- Fixed seeds, deterministic ordering, sample reuse/common random numbers. Recompute affected data only. Benchmark real workloads before porting bottlenecks to C++ or CUDA.

## Mathematics and objective

- Default decision: maximize **P(win at least five categories)** under actual tie/scoring rules. Carry correlated category simulation, not nine independent Bernoulli decisions. Optionally evaluate expected category wins as a separate sensitivity metric.
- H2H 9-CAT: FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO; turnovers lower is better; team FG% and FT% = team makes/team attempts, handle zero attempts explicitly.
- Include `HOLD` action and protect long-horizon roster value; negative expected-value acquisitions should not be recommended.
- Roster eligibility, lineup locks, games caps, acquisition counts, waiver priority/FAB and injury slots must come from verified league settings, not assumed.

## Code quality

- Python type hints for public functions, small modules, Ruff, mypy, pytest. No meaningless 100% coverage target.
- C++20 with explicit ownership, RAII, const correctness, `std::span`/contiguous arrays where appropriate, `clang-format`, `clang-tidy`, and Catch2 or GoogleTest (choose one).
- Compile warnings (`-Wall -Wextra -Wpedantic`) and sanitizers for debug/test configurations where supported. Avoid undefined behaviour and clever premature optimizations.
- Write short design comments explaining assumptions and numeric invariants, not narrating obvious code.
- Use structured logs without tokens, player/account secrets or excessive raw responses.

## Scope control

For each stage, commit: smallest implementation + focused tests + docs/status update. Prefer an explicit error with actionable diagnostics over silent fallback. Document every deliberate simplification.

## Branches and merge gates

The required flow is `dev_<feature>` -> `dev` -> `main`.

- `main` is the protected, stable branch. Require pull requests and passing CI;
  disable force pushes and deletion, and do not bypass protection. Its only
  normal source of changes is a promotion pull request from `dev`.
- `dev` is the integration branch. Agents do not commit directly to it. Changes
  enter through reviewed pull requests from descriptive `dev_<feature>` branches.
- `dev_<feature>` is the agent work branch, created from current `dev` before
  editing. Use names such as `dev_branch-workflow` or `dev_stage00-foundation`.
  Use the underscore prefix: `dev` and `dev/feature` cannot coexist in Git.
- If `dev` does not exist, create it from the reviewed `main` baseline, then
  create the work branch from it. For a repository with no commits, the owner
  establishes the initial baseline first. Preserve existing user changes when
  switching branches. If permissions block branch creation, work in an isolated
  checkout and hand off a patch; do not make changes on `main` or `dev` instead.

Before merging a work pull request into `dev`, review its scope, update STATUS.md,
and run the applicable local engineering checks plus required CI on the proposed
merge result. Resolve conflicts on the work branch and rerun affected checks.
Missing tools, skipped required checks, or failing CI block the merge. Record
the tested commit and actual results in the pull request; invalidate that evidence
if the source or destination changes before merging.

Before promoting `dev` to `main`, open a separate promotion pull request and
verify the full configured lint, format, type, unit, build, sanitizer and CI
checks for the proposed merge result. Review the accumulated changes and stage
acceptance evidence, resolve outstanding failures/blockers, and obtain owner
approval for the promotion. Passing a feature branch's checks alone does not
establish that the combined release is safe. Never merge unverified changes or
bypass the protected branch's checks.

Repository settings must enforce the `main` policy. Documenting this rule does
not enable GitHub branch protection; verify the settings separately before a
promotion and record any missing protection as a blocker.
