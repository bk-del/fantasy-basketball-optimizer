# Stage 04: fixture matchup simulation

Stage 04 exposes `fantasy simulate --fixture` with `--seed`, `--scenarios`,
`--backend python|cpp` and `--benchmark`. No live simulation or recommendations
are enabled. Stage 03 weekly aggregates are **not** split into invented games.
The separate fixture has 40 explicitly handmade player-games, ten fictional
players, four future days and three joint vectors per game, including a zero
participation vector. This is an arithmetic/performance demonstration, not a
forecast trained or calibrated on real games.

## Contract and arithmetic

`simulation.py` receives typed `GameForecast`, `Selection`, `Rules`, an explicit
as-of time, two observed count vectors and a reusable `ScenarioBank`. Count order
is FGM, FGA, FTM, FTA, 3PM, PTS, REB, AST, STL, BLK, TO. Missing counts are rejected;
zero is an observed/sample count, never an imputed missing value. Makes/attempts,
three-point makes and the exact points identity are validated.

Each forecast supplies a unique player-game identifier, aware start/end times,
explicit eligibility, model version and complete joint count samples.
Availability/minutes metadata can remain null with explicit missing inputs;
the joint vectors already include any participation uncertainty. Metadata does
not cause a second independent availability draw. No schedule, minutes or
availability probability is inferred from Yahoo statuses or weekly aggregates.

Rules supply both rosters, unique lineup slots, remaining per-team game caps,
locked assignments, league timezone and scoring-period boundaries. Duplicate
selections, conflicting daily slots, overlapping rosters, unknown/ineligible
players, changed locks and cap/period violations fail explicitly. These are
synthetic daily lineup rules, not a verified complete Yahoo constraint adapter.
No automatic lineup optimization, injury-slot transitions, waiver transactions
or acquisition policies are implemented.

Completed selected games contribute nothing further: their actual counts must
already be in the observed totals. Future selected games are added to those
totals. A currently playing game is rejected because full-game samples would
double-count play already observed. Supporting within-game remaining forecasts
requires a verified contract and is deliberately deferred. A matchup with no
remaining games is supported using an empty scenario bank.

FG% and FT% compare summed makes divided by summed attempts using exact integer
cross-products; player percentages are never averaged. Counts are bounded at
10,000,000 per aggregate stat, keeping products below int64 overflow. TO reverses
the comparison; other counting categories prefer higher totals. Exact equality
produces a category tie.

Fixture rules explicitly select:

- `zero_attempts=zero`: zero attempts means a zero percentage (both zero tie).
  `tie` instead ties that percentage whenever either team has no attempts.
- `scoring=at_least_five`: the objective is at least five category credits;
  category ties give zero or half a credit according to `category_ties`.
- `scoring=category_majority`: compare category wins with losses. A tied matchup
  receives loss, half credit or a win according to `matchup_ties`. Equal half
  category credits on both sides do not change this comparison.

`win_probability` reports full-win frequency under those rules; a half-credit
matchup tie does not count as a full win. `expected_matchup_credit` reports the
separate tie-adjusted objective. Each has its own Monte Carlo SE (sample variance
of scenario utility divided by scenario count). One scenario reports null SE;
zero observed variance does not prove certainty. The toy default is five wins,
zero category-tie credit and zero percentage for zero attempts. **Actual Yahoo
league scoring and tie rules remain unverified; these defaults are not live
league claims.**

## Dependence and reproducibility

Bootstrap entire player-game vectors. Never sample category-win flags
independently. Dependencies among makes, attempts and counting categories survive
sampling and team aggregation. Different games are sampled independently: this
fixture does not model shared team pace, opponent context, multi-game availability
or cross-player dependence. Calibration and unknown context remain unverified.

Use one scenario bank for every alternative selection. Stable sorted game keys
and SHA-256-derived per-game RNG streams preserve unchanged samples when the
input order or candidate pool changes. C++ uses these same contiguous int64
batches, so parity is exact; it has no separate RNG and makes no Python calls in
scenario loops. Native outputs have explicit capsule ownership. Python handles
rule validation, final scoring, uncertainty and reporting.

Output records as-of, seed, sample count, simulator/model/rules versions, NumPy
version, Python code hash, forecast input hash, selection/rule/observed-input
hash and sampled scenario hash. The native kernel is versioned with the repository
and packaged in the wheel. Pin NumPy to preserve the tested sampler environment.
The raw batch allocation is limited to 256 MiB; preparation, selection copies
and result hashing require additional memory. At 20k/40 games, one raw cube is
70.4 MB. No persistent simulator cache, storage migration or model promotion.

Monte Carlo precision describes finite sampling from supplied forecasts; it does
not measure calibration or forecast uncertainty. The two-state regression has
jointly moving winning categories and known probability 0.5; fixed-seed 1k, 10k
and 20k estimates fall within four theoretical sampling standard errors.

## Measured fixture performance

A preliminary 1k Python reference measured 0.118 seconds, motivating the native
aggregation/comparison kernel. Saved final results are in
[benchmarks/stage04.json](benchmarks/stage04.json), produced by:

```bash
uv run --offline --no-sync fantasy simulate --fixture --benchmark
```

Final benchmark: Python 3.12.14, GCC 11.4.0, installed Release wheel with nanobind's
default size optimization; 40 selected player-games, seed 42. Each kernel is
warmed, then timed three times; the table uses medians. Preparation is timed once
per size and includes sampling, validation and contiguous selection copies.

| Scenarios | Preparation (s) | Python kernel (s) | C++ kernel (s) |
|---:|---:|---:|---:|
| 1,000 | 0.025638 | 0.098992 | 0.001273 |
| 10,000 | 0.171255 | 1.026109 | 0.013294 |
| 20,000 | 0.321204 | 2.024418 | 0.026835 |

This compares a small explicit Python reference with a batched native kernel.
It is not a comparison against all possible optimized NumPy implementations.
Timings exclude CLI startup, final summaries/hashing and artifact I/O. Preparation
is substantial and dominates the native path; these measurements do not establish
an end-to-end production speedup. No GPU, speculative tuning or CI wall-clock
threshold is introduced. CI checks deterministic arithmetic/constraints/parity
regressions, not environment-sensitive runtime ratios.

## Build and verification

Pinned scikit-build-core 0.11.6 builds the native extension and packages existing
JSON fixtures. Nanobind 2.9.2 and NumPy 2.2.6 are pinned; install the documented C++
tools before `uv sync`. Debug CMake tests use Catch2 (2.13.8 tested locally).
Project C++ code retains warnings-as-errors and clang-tidy. Third-party nanobind
implementation is excluded from project clang-tidy policy, and its headers are
system includes; project diagnostics are not suppressed.

The same kernel is compiled into standalone ASan/UBSan Debug tests and the Python
module. The module itself omits sanitizers because loading ASan into an ordinary
Python process needs interpreter preloading; standalone tests instrument the
kernel. CTest explicitly loads the just-built extension by path, bypassing editable
wheel import redirection, before executing Python parity tests. Tests cover
weighted ratios, TO, ties, completed games, in-progress-game rejection, scoring
variants, bounds, shared streams, convergence and deterministic/stochastic parity.
Full CTest with leak checking passed outside the sandbox; a restricted run fails
because LeakSanitizer cannot run under tracing. Remote GitHub CI remains unverified.

Stop at the Stage 04 gate. Stage 05 and live data require separate authorization.
