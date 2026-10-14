# Advanced NBA forecasting — completed 2026-10-13

**Recency remains the production baseline.** Actual LightGBM and PyTorch training,
chronological evaluation, full-population refits, conditional forecasts and native
fixture optimization all executed. The development-selected LightGBM improves the
final normalized nine-category error score **0.58%**, below the **2%** promotion
threshold frozen before opening the new period. Its all-count registry loss also
slightly worsens (**1.023635 → 1.023995**). No advanced model was promoted. No Yahoo
integration, credentials, new historical download, GPU or optimizer/C++ rewrite.

Evidence: [frozen protocol](benchmarks/nba-advanced-protocol.json),
[all development/final/segment metrics](benchmarks/nba-advanced.json),
[CPU/component benchmarks](benchmarks/nba-advanced-performance.json), and
[actual predictions, complete baseline/candidate fixture decisions and checks](benchmarks/nba-advanced-end-to-end.json).
Earlier [24-player/full-population references](HISTORICAL_FORECAST_BENCHMARK.md)
and the approved NBA model registry remain unchanged.

## Data and point-in-time contract

The existing checksum/coverage-gated Parquet/DuckDB adapter supplies **64,695 valid
regular-season rows, 697 historical NBA IDs, two seasons (2024–25 and 2025–26)**.
No player cohort or current roster/survivorship filter is applied. Source counts
are retained, including reserves, zero rows and players who later leave the league.
All source observations contribute to lagged estimates/population priors. Supervised
eligibility requires **one own origin-known prior row**: **63,955 cases / 689 target
IDs**. First-ever/not-yet-known histories account for the remaining 740 cases;
eight source IDs never have an eligible supervised target. All **697** historically
supported IDs still receive current forecasts using their known history and priors.
No identities or games are invented for unseen rookies with no recorded history.

Historical replay explicitly retains the prior **retrospective_next_day** policy:
unknown publication is assumed at noon UTC following the game-date label. A feature
origin is midnight UTC; source rows must have both event-end and availability at
or before that origin. Earlier known outcomes can update features at later origins,
including earlier final-period games. Fitted learner/configuration/calibration
parameters do not update during evaluation. Input hashes include only origin-known
records. Date labels are not verified tip-off/completion times. Actual retrieval
is retained; snapshot corrections and original publication times cannot be recovered.
This is temporal correctness under the declared assumption, not recovered historical
publication-time evidence. Current fitting/inference uses **strict actual retrieval**.

Minutes: **11,738** blank fields and **127** malformed values (e.g. `29:60`) remain
unknown; 125 malformed-minute rows have nonzero counts. No guessed carry/zero-minute
repair is made. Their valid counts still enter count history, shooting evidence
and nonzero-row labels. Minute/rate targets require known **>=1 minute and a nonzero
box-score row**; missing minute targets never become zero. Some numerical input
features use a zero placeholder plus explicit missing-history fraction. This is
separate from target missingness.

## Lagged features and learners

| Feature group | Inputs | Information available at the origin |
|---|---:|---|
| History/exposure | 8 | History/effective size, days since known row, minute missingness/mean/recent mean/dispersion, nonzero-box-score frequency |
| Raw count history | 44 | 14-day recency, last 3/10 known rows and dispersion for all eleven counts |
| Production per minute | 16 | Recency and long-run attempt/REB/AST/STL/BLK/TO rates with known exposure |
| Shooting priors | 9 | Own attempt-weighted 2P/3P/FT estimates/mass and target-excluded contemporary population rates; fixed 50-shot prior |
| Past team context | 8 | Last observed team's previous six completed-game pace, own/opponent scoring, opponent REB/AST/3PA, home frequency and coverage |

Total **85** inputs. Player/team IDs identify records/groups and RNG streams, never
numeric learner inputs. `context_last_home` names a past-six-game home frequency;
it is not the upcoming venue. Target game team/opponent/home/lineup/minutes, future
team changes, injuries, availability and schedules are excluded. No teammate-absence,
usage-rate, depth-chart or causal role narrative is inferred from count changes.

LightGBM uses 13 bounded residual heads: nonzero-box-score probability, conditional
minutes, eight per-minute production rates and three shot probabilities. Rates use
known minute exposure weights; shooting targets are makes/attempts weighted by
attempts, anchored to the earlier statistical prior. Two fixed tree configurations:
15 leaves/120 rounds and 31 leaves/180 rounds, learning rate .05, L2 regularization10,
minimum leaf80, max-bin63. The small PyTorch challenger is **85→64→32→13**, **8,013
parameters**, ReLU, AdamW .001/weight-decay .01, 32 epochs, batch256, masked/scaled
residual squared loss. All scalers use training rows only. Seed42, CPU, two threads;
no random player-game train/test split, Optuna, GPU or additional ML framework.

CPU determinism uses LightGBM's documented `deterministic`/`force_col_wise` options
([official 4.6 parameters](https://lightgbm.readthedocs.io/en/v4.6.0/Parameters.html))
and PyTorch seeds/deterministic algorithms
([official reproducibility guidance](https://docs.pytorch.org/docs/stable/notes/randomness.html)).
Versions are pinned: LightGBM4.6.0, PyTorch2.6.0+cpu, SciPy1.15.3, existing NumPy2.2.6;
CPU wheels use the [official PyTorch index](https://pytorch.org/get-started/previous-versions/).
Exact replication was actually checked on this software/hardware environment;
cross-version/platform bitwise equivalence is not promised.

Ablations retain the 15-leaf/120-round settings: remove eight team-context inputs;
remove minute/rate inputs and use a direct primitive-count residual model (a combined
feature/structure ablation); remove engineered own shot-prior features and replace
its prior anchor with population shooting. Remaining raw shooting-count history is
retained. Ablations are development diagnostics, not selected using final outcomes.

## New chronological protocol

Previously examined target periods **Mar24–Apr14 2025** and **Jan5–Apr13 2026** are
excluded from advanced fitting, selection and calibration target labels. The new
final period **Oct21 2025–Jan5 2026** was previously unscored. Previously observed
games from older periods may appear as legitimate past inputs at later origins;
no old final-period scores select parameters. No final outcomes tune a model,
feature, prior, epoch count, calibration width or promotion threshold.

| Stage | Dates / boundary (UTC) | Actual support |
| Walk-forward fold | Fit before 2024-11-25; score through 2024-12-16 | 6,003 fit / 3,288 development cases |
| Walk-forward fold | Fit before 2024-12-16; score through 2025-01-06 | 9,449 fit / 3,510 development cases |
| Research fit | Labels available before 2025-01-06 | 13,142 cases / 518 players |
| Calibration | 2025-01-06–2025-02-17 | 7,635 cases/model |
| Fresh final period | 2025-10-21–2026-01-05 | 13,656 cases / 522 players |

Selection minimizes equally weighted MAE for seven counting categories plus FG%
and FT%, scaled by fixed recency development MAEs, pooled over both folds. All eleven
underlying counts are also measured and guarded. Final labels may be observed up to
two days after the prediction-period end; they never enter features or calibration.
The late boundary permits final Jan4 outcomes without including any Jan5 target.

| Development configuration | Relative nine-category error (recency=1) |
|---|---:|
| ablate_context | 1.007080 |
| ablate_minutes_rates | 1.012119 |
| ablate_shot_priors | 1.005204 |
| lgbm_medium | 1.018720 |
| lgbm_small | 1.005812 |
| mlp_small | 1.005908 |

Selected **lgbm_small** before final exposure. The slightly lower shot-prior ablation
is a diagnostic, not a new post-test configuration. Both tree and neural candidates
roughly match recency in development; there is no general advanced-model superiority.
The best development tree and the predeclared neural challenger are final diagnostic
comparisons. The selected candidate is never switched based on their final scores.

## Final accuracy, probability scores and uncertainty

MAE per recorded player-game, including observed zeros; ratios exclude target zero
attempts. FG%/FT% errors are fractions (e.g. .1762 =17.62 percentage points of absolute
ratio error), not a percentage-accuracy claim. Model means are analytic; interval/
probability metrics use 256 seeded draws with common target events.

| Statistic | Season-to-date | Recency14 | Bayesian14 | Selected LightGBM | Neural challenger |
|---|---:|---:|---:|---:|---:|
| PTS | 4.3251 | 4.2925 | 4.5053 | 4.2649 | 4.2903 |
| REB | 1.8024 | 1.7951 | 1.8530 | 1.8038 | 1.7926 |
| AST | 1.2234 | 1.2132 | 1.2640 | 1.2272 | 1.2332 |
| STL | 0.6345 | 0.6344 | 0.6442 | 0.6339 | 0.6325 |
| BLK | 0.4318 | 0.4333 | 0.4449 | 0.4508 | 0.4407 |
| 3PM | 0.7897 | 0.7904 | 0.8202 | 0.7847 | 0.7872 |
| TO | 0.8113 | 0.8109 | 0.8276 | 0.8052 | 0.7964 |
| FGM | 1.6476 | 1.6381 | 1.7074 | 1.6312 | 1.6343 |
| FGA | 2.7101 | 2.6675 | 2.8577 | 2.6790 | 2.6939 |
| FTM | 1.2111 | 1.2069 | 1.2396 | 1.1909 | 1.2180 |
| FTA | 1.4745 | 1.4670 | 1.5043 | 1.4460 | 1.4814 |
| FG% | 0.1860 | 0.1854 | 0.1787 | 0.1762 | 0.1760 |
| FT% | 0.2406 | 0.2264 | 0.2190 | 0.2182 | 0.2175 |

Selected model's **nine-category relative gain0.5799%** is modest. PTS error falls
about0.64%; FG% about4.95% and FT% about3.61%, while REB/AST/BLK errors worsen.
Normalized all-eleven-count registry loss is slightly worse. The paired
player-cluster bootstrap (1,000 resamples) gives normalized error-delta 95% interval
**[-.009634,-.001581]**; it excludes zero but does not meet the predeclared practical
2% gain requirement. Common calendar shocks are not removed by that bootstrap.
Per-category MAE-delta intervals are in JSON. These comparisons do not establish
live decision uplift or isolate a causal benefit from more training observations.

Selected LightGBM distribution diagnostics:

| Statistic | Bias | 80% coverage | Mean interval width | Interval score | Common-event Brier |
|---|---:|---:|---:|---:|---:|
| PTS | -0.0189 | 0.8006 | 11.9360 | 19.3921 | 0.2367 |
| REB | 0.1271 | 0.8831 | 5.6958 | 8.0006 | 0.2354 |
| AST | 0.0728 | 0.8981 | 3.6495 | 5.3092 | 0.2213 |
| STL | 0.0239 | 0.9388 | 1.6812 | 2.4603 | 0.1973 |
| BLK | 0.0066 | 0.9450 | 1.0909 | 1.7712 | 0.1592 |
| 3PM | 0.0003 | 0.9249 | 2.1586 | 3.2409 | 0.1869 |
| TO | 0.0892 | 0.9241 | 2.3225 | 3.2763 | 0.2064 |
| FGM | 0.0542 | 0.8590 | 4.7076 | 7.1736 | 0.2314 |
| FGA | 0.0910 | 0.7810 | 7.2008 | 12.6669 | 0.2468 |
| FTM | -0.1276 | 0.8908 | 3.0673 | 5.1795 | 0.2006 |
| FTA | -0.1342 | 0.8615 | 3.5347 | 6.3576 | 0.2089 |
| FG% | 0.0129 | 0.8896 | 0.6307 | 0.7662 | 0.2446 |
| FT% | -0.0030 | 0.9783 | 0.9119 | 1.0523 | 0.2603 |

Mean count interval-score ratio versus raw recency **.90481** (about9.5% lower);
mean count Brier ratio **.95762** (about4.2% lower). These are means of per-count
ratios, not pooled errors. Probability events are the same across models: actual
count greater than the floored origin-known season-average count, or actual ratio
greater than that baseline ratio. TO's event is a diagnostic above-threshold event;
the simulator separately correctly treats TO as lower-is-better. Five-bin reliability
and finite-draw probability MC SE are retained. Zero simulated shooting attempts
use the simulator's explicit zero policy. Point MAE alone does not establish calibration.

Minute segments use origin-known mean reported minutes: low<15, medium15–<28,
high>=28; unknown kept separately. Sparse means fewer than four known rows and is
a separate overlapping partition. All thirteen statistics/models/segments are in JSON.

| Segment | Cases | Recency PTS MAE | LightGBM PTS MAE | Recency PTS coverage | LightGBM PTS coverage |
|---|---:|---:|---:|---:|---:|
| low | 3,978 | 2.7061 | 2.7521 | 0.8399 | 0.8421 |
| medium | 6,256 | 4.2982 | 4.2463 | 0.7834 | 0.7876 |
| high | 3,339 | 6.2540 | 6.1767 | 0.7823 | 0.7754 |
| unknown | 83 | 0.9880 | 1.2530 | 0.7349 | 0.8072 |
| sparse | 244 | 2.5963 | 2.6372 | 0.7172 | 0.8074 |
| established | 13,412 | 4.3234 | 4.2945 | 0.8008 | 0.8005 |

On this **same final period**, high-minute PTS coverage .7754 is slightly lower than
raw recency .7823. Do not compare it to the previous milestone's .6379 coverage as
an improvement: those were different dates and a different marginal calibration.
Conditional calibration remains approximate and subgroup/role shifts remain risks.

Conditional minutes use **11,149** known >=1-minute nonzero rows. The following
component-baseline comparison is descriptive post-evaluation analysis, not used
for selection/promotion; its intervals use only the earlier calibration period.

| Model | Minute MAE | Bias | 80% coverage | Mean width (minutes) | Nonzero-box-score Brier |
|---|---:|---:|---:|---:|---:|
| lgbm_small | 4.8448 | 0.2480 | 0.7905 | 15.0316 | 0.0972 |
| mlp_small | 4.8374 | -0.1002 | 0.7912 | 15.0781 | 0.0982 |
| recency_components | 4.8438 | -0.2043 | 0.7933 | 15.0778 | 0.1052 |

Minute accuracy is essentially unchanged from recency; no meaningful minutes gain
is claimed. Eight per-minute target MAEs for all models are in the performance JSON.
Availability remains unknown. The nonzero-row head is an auxiliary estimate used in
mean factorization, not the zero-mass of the calibrated sampler. Minute intervals
are conditional marginal diagnostics, not a joint availability/minute/count model.

### Joint sampling and fixed promotion gate

Means factor predicted nonzero-row probability × conditional minutes × production
rates, with makes from attempt rates and estimated shooting probabilities. Sampling
uses eleven nonnegative primitives: 2P makes/misses, 3P makes/misses, FT makes/misses,
REB/AST/STL/BLK/TO. Earlier calibration learns whole-vector residual factors,
conditional on origin-known minute/history groups; at least100 rows per cell,
otherwise minute group then pooled fallback. Factors have component means1 and
Poisson noise yields coherent count draws. FGM/FGA/FTM/FTA/3PM and PTS are reconstructed,
so makes/attempts bounds and points identity hold. Sharing a whole residual vector
preserves modeled within-vector dependence; cross-player/game dependencies remain
unmodelled. These are moment-based conditional distributions with no coverage or
matchup-probability guarantee.

Promotion was frozen before opening the period: >=2% normalized nine-category gain,
paired cluster upper95% delta below0, no underlying count category >5% worse or
shooting ratio >1% worse, mean count interval-score ratio<=1.05, Brier ratio<=1.02,
overall count coverage and sufficiently populated minute-group PTS coverage in
[.70,.90]. Existing scoped all-count registry validation also remains binding.
The held-out gate fails its 2% criterion; no promotion is attempted. Recency stays
active, the fitted selected model remains a candidate, and an explicit manual
promotion also refuses a failed gate. Approved model history/rollback is retained.

## Actual all-history forecasts and fixture decisions

After freezing/evaluating the configuration, LightGBM was actually refitted on all
**63,955 eligible cases / 689 target IDs**. The same predeclared neural configuration
was also actually refitted on that full population for current inference/runtime
benchmarking, with **8,013 parameters**. Neither new full-history fit is scored on
its previously examined holdout: accuracy above pertains to the earlier research
fits. Current all-history weights have no independent future evaluation. No new
parameter, feature or model was chosen after final exposure.

Strict current cutoff **2026-10-13T03:40:00Z** generates **697** candidate forecasts.
All include eleven expected counts, joint draws, uncertainty, conditional minute/
rate/shot estimates, IDs, prediction/data cutoff, latest observation and model/data/
code versions. Timestamp is the explicit requested origin, fixed for reproducibility;
it does not assert earlier creation. Latest observations end in April2026, so current
membership/roles/availability are unknown. No verified future schedule means actual
seven-day totals remain **unavailable/null game count**.

The original eight-role fixture league binds verified source NBA IDs, retaining its
hypothetical eligibility, ownership, schedule and value proxies. All synthetic count
vectors are discarded. Real candidate samples go through the unchanged Python/C++
int64 interface and existing add/drop/HOLD objective, constraints, lineups and value
guard. C++ contains no learned model/fitting logic. Complete native/reference ranked
actions match exactly at4,096 finalist scenarios; input moments at20k draws match
empirical input distributions within five MC SE. Fixed seed/model/input repeats are
identical, including cache hits; ordinary inference never changes registries.

Both baseline and candidate fixture runs recommend **ADD Al Horford (201143), DROP
Jeff Green (201145)**. Baseline HOLD/action win probabilities **18.75%→49.90%**;
candidate **25.42%→50.44%**, paired gain25.02 percentage points / MC SE.76 points,
seed42, 256 screening/4096 finalist scenarios. HOLD is retained. Different model
probabilities are **not measured decision-quality improvement**. These are fixture
simulations, not live Yahoo recommendations or calibrated live odds. Full category
tradeoffs/lineups/protection/rejections/provenance and eight forecast examples are
in the end-to-end evidence, with full artifact paths/SHA256. Original NBA production
registry and both older benchmark evidence files stayed byte-identical.

## Measured CPU runtimes and memory

| Work | Seconds | Peak process memory / scope |
|---|---:|---|
| Full85-feature preparation | 169.4008 | 641.39MiB; once, then verified NPZ cache |
| Development selection + calibration | 82.7900 | 588.16MiB external peak; 12 fold fits + final research fits/calibration |
| Six final comparisons | 146.4200 | 727.40MiB; previously frozen models |
| All-history LightGBM fitting | 25.5577 | 559.16MiB whole CLI; 36.65s external total |
| All-history neural fitting | 16.5595 | 8,013 parameters; unpromoted diagnostic refit |
| Current all697 feature preparation | 3.1543 | Loading excluded |
| All697 LightGBM / neural pure inference | 0.0933 | Neural 0.00526s; sampling/JSON excluded |
| Fresh candidate full CLI | 20.3672 | 645.64MiB; all-player forecasts/persistence/search |
| Cached candidate full CLI | 6.7815 | 299.12MiB; no resampling/search |
| Candidate native add/drop optimization | 0.2395 | 256/4096 search, includes decision cache write |
| Full profiling process | 51.3455 | 903.11MiB including neural fit/all-player inference/20k banks |

| Scenarios | Preparation seconds | Native kernel seconds | Python kernel seconds |
|---:|---:|---:|---:|
| 1,000 | 0.05623 | 0.000460 | 0.038290 |
| 10,000 | 0.13320 | 0.004946 | 0.388588 |
| 20,000 | 0.17400 | 0.009153 | 0.856442 |

Kernels are median3 after warmup, with exact category parity. Peak profiling memory
**903.11MiB** fits the requested16GB budget; source dataset fits in bounded DuckDB/
NumPy memory. This measures local CPU, not the owner's specific WSL2/RTX laptop.
No GPU speed claim or GPU infrastructure. Some checks ran concurrently; monotonic
and external-clock measurements differ slightly (final147.66s internal vs146.42s
external), preserved in evidence. Large all-player joint JSON still costs seconds
to parse/hash/persist on cached CLI paths. No timing optimization changes accuracy. Batch model timings include estimator
reconstruction; the tree row also reads its model JSON. These rows are not a
controlled comparison of architecture speed.

## Exact reproduction and verification

At repository root, using the existing pinned cached NBA source:

```bash
export UV_CACHE_DIR=/tmp/fantasy-stage01-uv-cache
export OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
# First dependency setup may need network; CPU-only optional extra, project-local:
UV_SYSTEM_CERTS=true uv sync --locked --extra advanced --group dev
# Thereafter offline; no historical NBA download:
uv run --offline --no-sync fantasy advanced backtest --prepare-only > /tmp/advanced-prepared.json
uv run --offline --no-sync fantasy advanced backtest > /tmp/advanced-final.json
# Rebuild missing ignored learners/calibration, without selecting/scoring final targets:
uv run --offline --no-sync python scripts/rebuild_advanced_models.py
# Optional actual retraining + checksum verification of both frozen research models:
uv run --offline --no-sync python scripts/rebuild_advanced_models.py --verify
uv run --offline --no-sync fantasy advanced train --as-of 2026-10-13T03:40:00Z
uv run --offline --no-sync fantasy advanced model --model-action status
# Default uses the approved recency baseline:
uv run --offline --no-sync fantasy advanced run --fixture --as-of 2026-10-13T03:40:00Z > /tmp/advanced-baseline.json
# Explicit read-only candidate evaluation does not promote:
uv run --offline --no-sync fantasy advanced forecast --candidate --as-of 2026-10-13T03:40:00Z > /tmp/advanced-predictions.json
uv run --offline --no-sync fantasy advanced run --fixture --candidate --as-of 2026-10-13T03:40:00Z > /tmp/advanced-candidate.json
uv run --offline --no-sync fantasy advanced run --fixture --candidate --backend python --as-of 2026-10-13T03:40:00Z > /tmp/advanced-reference.json
uv run --offline --no-sync python scripts/benchmark_advanced_nba.py
```

Defaults: source `data/nba_data`, frozen protocol/report in `docs/benchmarks`,
separate registry `models/advanced-registry.json`, original baseline registry
`models/nba-registry.json`, forecast/decision output `data/advanced-runs`, seed42,
256 forecast draws, 256/4096 search. Full current joint forecasts, learned weights,
calibration/replay artifacts and feature arrays remain ignored; tracked results
reference their SHA256. Retain `features/advanced-benchmark-registry.json`, frozen
report and source snapshot. Repeated backtest returns the unchanged frozen report;
it never reselects or recalibrates on final outcomes. Identical frozen computation
can resume after interruption. Changing scientific code/config/data after final
consumption refuses. Never delete guards/edit evidence to retune on that period.

Both frozen research learners were actually independently retrained and all **seven
model/calibration artifacts** reproduced exact SHA256. The reconstruction script
only uses pre-holdout training/calibration rows, and refuses mismatching replacements.
Six replay checksums, **81,936 model-case rows**, identical target/input/outcome/
threshold keys and independently recomputed per-count MAEs were checked. Actual
current train repeats keep the same model IDs/registry bytes; candidate cache hits
return identical reports. The original registry and older evidence stayed unchanged.
Native/reference current4096-scenario rankings and20k input moments passed.

Required checks actually passed: locked offline sync with `--extra advanced`, Ruff
lint/format (**51 files**), mypy (**30 sources**), focused suite **40 passed**,
final full Python suite **225 passed in117.95s**, Debug CMake configure/build,
tracked clang-format14, **3/3 standard CTest in1.70s**, full leak checks retained.
Existing sandbox socket/ptrace restrictions required approved unrestricted pytest/
CTest; no suppression or local skips. C++ unchanged, fresh clang-tidy not applicable.
Offline sdist/native wheel built; isolated wheel asserted package/native file paths,
both actual research learner predictions exactly, advanced CLI/extra metadata and
actual candidate native/reference optimization parity. Remote CI/specific laptop
hardware were not run or claimed. Engineering commands:

```bash
uv sync --locked --offline --extra advanced --group dev
uv run --offline --no-sync ruff check .
uv run --offline --no-sync ruff format --check .
uv run --offline --no-sync mypy src
uv run --offline --no-sync pytest -q
cmake -S cpp -B build/cpp -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build/cpp
ctest --test-dir build/cpp --output-on-failure
git ls-files -z -- '*.cpp' '*.hpp' | xargs -0 -r clang-format-14 --dry-run --Werror
uv build --offline --out-dir /tmp/fantasy-advanced-dist
git diff --check
```

**Acceptance:** actual advanced training/evaluation, all-eligible refits, conditional
forecasts and unchanged native/legal fixture integration verified. **Advanced model
promotion not accepted**; recency remains production. Missing verified schedules,
current roles/injuries and historical publication/revision evidence remain explicit.
No automatic training/acquisition/transaction policy was enabled. Next milestone
should add verified fresh contextual data and use a newly declared future evaluation
period; the just-examined final period cannot guide another selection. Stop at owner
advanced-milestone review gate; no Yahoo integration, main merge or publication.
