# Pragmatic verification and quality gates

## Automated essentials

- Python: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest -q`.
- C++ when present: CMake/Ninja Debug configure/build, `ctest`, formatting for source files, clang-tidy on changed code; sanitizers in an appropriate test target.
- CI (GitHub Actions) should run offline lint/unit/fixture tests on PR/push; never require Yahoo credentials to validate standard contributions.

## Required high-value tests

1. Yahoo response parsing from small redacted/handmade fixtures; missing fields and token refresh failures are handled without leaking secrets.
2. Database migrations, duplicate ingestion, partial API failures, timestamp/as-of semantics and schema compatibility.
3. 9-CAT arithmetic: FG/FT attempt weighting, TO inversion, zero attempts, ties, partial remaining games, win conditions.
4. Simulator reproducibility with same seed; appropriate statistical confidence bands; convergence and Python/C++ parity on a tiny deterministic fixture.
5. Transaction feasibility: impossible positions, occupied slots, acquisition limits, waiver/injury restrictions and `HOLD` baseline.
6. Time-series backtesting must prove no future observations or ownership data enter past decisions.
7. Forecast calibration/error versus simple baseline; candidate models never promoted solely by training score.
8. Caching invalidation: changed inputs refresh only affected outputs, while identical inputs reuse results.

## No false precision

Matchup probability comes from finite correlated simulations and has Monte Carlo uncertainty. Separate model uncertainty from sampling error. Any unobserved injury/context feature must be reported as unavailable, not extrapolated as a verified event. Historical action quality is counterfactual and cannot be perfectly proven from one league's observations.

## Stage completion template

- Acceptance criteria actually met: yes/no, evidence.
- Exact commands executed and exit results.
- Known skips, constraints, and rationale.
- Benchmark comparison if performance is claimed.
- `STATUS.md` updated before stopping.
