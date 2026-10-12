# Fantasy Basketball Decision Engine — implementation guide

A staged, agent-friendly implementation plan for a **personal, local-first Yahoo Fantasy Basketball H2H 9-category waiver optimizer** (initial league: 14 teams; roster and transaction rules not yet known).

**Objective:** recommend `ADD / DROP / HOLD` to maximize calibrated matchup-win probability while protecting longer-term roster value. Never claim that a player will break out with certainty. **Yahoo Fantasy is the only runtime data source** unless the owner explicitly changes this constraint. No paid LLM inference or paid data dependencies.

## Start here

1. Place these files at the root of a new repository, retaining `docs/stages/`.
2. Open the repository with Codex and say: **"Read AGENTS.md and STATUS.md, then execute docs/stages/00-repository-foundation.md. Stop at its approval gate."**
3. After each stage, the agent must update `STATUS.md` and stop. To resume: **"Read AGENTS.md and STATUS.md; execute the next unblocked stage, then update STATUS.md."**
4. Stage 00 prepares a public-facing README/repo for the Yahoo access request, but **does not assume Yahoo access has been approved**.

## Stage map

| Stage | Purpose | Key gate |
|---|---|---|
| [00](docs/stages/00-repository-foundation.md) | Repo, standards, toolchain, public README, GitHub | Owner approves repository publication |
| [01](docs/stages/01-yahoo-api-audit.md) | Real Yahoo OAuth/API audit, availability and limitations | Credentials + verified endpoints (or fixture-only fallback) |
| [02](docs/stages/02-storage-and-ingestion.md) | Typed schemas, DuckDB, snapshots, incremental ingestion | Idempotence, point-in-time records |
| [03](docs/stages/03-baseline-forecasting.md) | Lightweight probabilistic forecasts and baselines | Walk-forward forecast benchmarks |
| [04](docs/stages/04-matchup-simulator.md) | C++20/CPU Monte Carlo matchup engine | Statistical tests and reference parity |
| [05](docs/stages/05-waiver-optimization.md) | Valid add/drop/hold ranking, lineup constraints | Correct objectives and feasibility |
| [06](docs/stages/06-context-and-breakouts.md) | Injury/role proxy signals where Yahoo supports them | No fabricated context; incremental gain |
| [07](docs/stages/07-learning-and-backtesting.md) | Retraining, calibration, model promotion | Out-of-time validation; rollback |
| [08](docs/stages/08-cli-and-operations.md) | End-to-end manual CLI, caching, scheduler-ready | Repeatable and observable runs |
| [09](docs/stages/09-optional-extensions.md) | Multiweek planning, behaviour modelling, CUDA | Only after evidence of benefit |

Stages are sequential by default. Fixture-based development can continue while approval is pending, but never label fixtures as real Yahoo data.

## System boundaries

- Python: OAuth, ingestion, storage, feature generation, forecasting, CLI.
- C++20: measured hotspots in matchup simulation and candidate evaluation; `nanobind` interface after a trusted Python reference is available.
- DuckDB: metadata, league state and run records; Parquet only when justified for immutable game logs.
- No live trading/transactions. Read-only recommendation tool; the owner executes adds/drops.
- Manual CLI first, external scheduling later. No daemon, cloud deployment, deep RL or GPU requirement in the initial release.

See [Design rules](docs/DESIGN_RULES.md), [Data contracts](docs/DATA_CONTRACTS.md), [Validation](docs/VALIDATION.md), and [Status](STATUS.md).
