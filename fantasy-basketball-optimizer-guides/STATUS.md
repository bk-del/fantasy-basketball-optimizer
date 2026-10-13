# STATUS — agent handoff (update on every working session)

**Current stage:** 06 — Context and breakout detection (fixture-only).
**State:** Fixture diagnostic/label implementation committed locally on dev in the main checkout; required local checks passed. Stopped at Stage 06 approval gate.
**Data constraints:** Zero authorized Yahoo histories/context/exposure samples; zero usable fixture labels. No role/injury narrative, fitted model, calibrated breakout probability or live improvement claim.
**Active baseline:** Stage 03 weekly-counts-v1 recency remains provisional and unchanged, including its existing exposure/small-history uncertainty widening.
**Next exact step:** Owner reviews Stage 06 protocol/results on dev. Obtain authorized point-in-time counts/exposure/context and strictly later evaluation periods before fitting/promoting a model. Stage 07, merge into main and publication require new approval.
**Workflow/storage:** Direct dev development; main/remotes untouched. No transactions, storage migration, new dependencies, C++ changes or system-wide installs.

## Stage 06 execution plan (completed 2026-10-12)

Recorded before implementation: revisit Yahoo capability audit, reuse known-at-T windows; count-shift diagnostics with coverage/missingness/ambiguity; pre-register future-label horizon/gain/games/availability; separate features from outcomes; preserve active baseline/uncertainty and skip insufficient-data model/calibration/uplift; fixture CLI/provenance/tests; full Python/C++/package/CLI checks, focused dev commit and stage gate.

## Stage 06 completed work and changed files

- New src/fantasy_optimizer/context.py: frozen versioned BreakoutProtocol, proposed ExposureEvidence and explicit point-in-time shift_features/breakout_label functions. Uses existing known_windows filtering/revision logic; no alternate storage or API parser.
- Registered weekly-production-breakout-v1 before fitting: four baseline/two recent contiguous known weeks; baseline PTS >=10; both recent weeks >=25% gain, standardized shift >=2 with a one-point noise floor. Future horizon two weeks; both future PTS totals >=125% baseline, >=4 future games total and >=75% played/scheduled availability per future week. Missing/unqualified evidence excludes labels rather than fabricating negatives. This is weekly-production proxy labeling, not an asserted category-adjusted live replacement value.
- Transparent shift alarm from counts, with no breakout probability. Minutes/status/exposure/transactions/opponent-role/teammate-injury/usage sources explicitly skipped and coverage/ambiguity annotated. No count change is explained as an injury or depth-chart event.
- Origin features contain only already completed/observed/ingested windows; future outcomes and exposure use a separate evaluation-time boundary and hash. Later corrections/ingestion cannot leak into origin features. Conflicting exposure metadata requires explicit resolution; invalid protocols/timestamps/game counts reject.
- New context_fixture.py: deterministic diagnostic report on existing 48 handmade weekly vectors, chronological origins, explicit null precision/recall/calibration/decision-uplift and skipped training with reasons. Retains Stage 03 default and existing joint exposure widening; no unsupported extra role multiplier or optimizer forecast adjustments.
- Updated cli.py/tests/test_smoke.py for fantasy context --fixture, live gating and Stage 06 status. New tests/test_context.py: eight focused tests with multiple meaningful boundary cases. CI adds offline context command. README and docs/YAHOO_CAPABILITIES.md updated; new docs/CONTEXT.md and docs/benchmarks/stage06.json document protocol/skips and saved reproducible report.
- Capability audit revisited without new live request/sample; production classifications unchanged. No fabricated per-game rows or exposure fixtures shipped. Label tests use separately handmade exposure metadata only to validate the conceptual contract.
- Existing STATUS.md remains the single handoff; prior stage records preserved below. No Stage 07 training/backtesting framework, live data, transactions or remote operations.

## Stage 06 verification — actual outcomes

All commands ran at project root; uv used UV_CACHE_DIR=/tmp/fantasy-stage01-uv-cache.

- uv sync --locked --offline --group dev: passed, 15 resolved/14 checked; no dependency/lockfile changes.
- uv run --offline --no-sync ruff check . and ruff format --check .: passed (23 formatted files). mypy src: passed, 15 source files. Initial line-length findings fixed, none suppressed.
- uv run --offline --no-sync pytest -q: **120 passed in 8.71 seconds**; focused tests/test_context.py initially passed 8/8, then full suite included additional minimum-game/availability boundary assertions. No configured tests skipped.
- Tests cover sustained versus transient/flat/declining changes; missing counts/gaps/zero baseline; future corrections and late ingestion/order independence; positive/negative/excluded future labels, incomplete horizons and exposure requirements; separate game/availability minima; conflict/protocol validation; explicit feature/model/calibration/uplift skips; unchanged baseline and repeatable fixture/live CLI gates.
- cmake -S cpp -B build/cpp -G Ninja -DCMAKE_BUILD_TYPE=Debug and cmake --build build/cpp: passed, existing targets current. No changed C++ requires fresh lint; the native wheel rebuild ran configured project clang-tidy checks.
- ctest --test-dir build/cpp --output-on-failure outside sandbox tracing: **3/3 passed in 1.45 seconds**, retaining full ASan/UBSan/leak checking and explicitly loaded just-built native/reference parity. No sanitizer suppression this stage.
- git ls-files -z -- '*.cpp' '*.hpp' | xargs -0 -r clang-format-14 --dry-run --Werror: passed. git diff --check and staged checks passed. Elevated local git add/commit succeeded for the 11 Stage 06 files; final observed handoff is included in that dev commit. Main/remotes untouched.
- fantasy context --fixture saved to docs/benchmarks/stage06.json and repeated to /tmp: byte-identical JSON by cmp. Live refusal tested; no credentials/network requests made.
- uv build --offline: passed, sdist and native cp312 Linux wheel produced. Isolated Python -I -S imported context/native from the extracted wheel with paths asserted; report/provenance matched saved fixture JSON, prior read-only optimizer worked and recency baseline stayed active.
- README/context/capability local links and CI YAML parse: passed. Remote GitHub CI remains unverified. Live fitting, probability calibration, precision/recall and decision uplift were not run because verified Yahoo histories/labels/context do not exist; these are explicit data-dependent skips, not successful evaluations.

## Stage 06 observed results, limitations and acceptance

Four fixture players have final relative weekly PTS gains 15.13%, 13.29%, 11.91%, 10.34%; none reaches the registered 25% sustained-shift threshold. Twenty-eight chronological candidate label origins yield zero usable labels: twenty complete horizons lack game/availability evidence and eight horizons are incomplete. The saved report exposes null precision/recall/calibration/uplift with reasons. No fitted classifier/LightGBM is justified or installed; baseline promotion is false.

**Fixture/data-insufficiency acceptance met:** sustained shift and pre-registered label contracts verified, point-in-time boundaries tested, coverage/missingness/ambiguity and source skips explicit, baseline/uncertainty retained, insufficient Yahoo data documented instead of asserting improvement, required checks passed and handoff updated.

**Unverified live work:** true Yahoo context/window/exposure semantics, category-adjusted replacement labeling, calibrated probabilities and decision uplift cannot be established. Shift statistic is a count-only heuristic, not causal evidence or a formal significance guarantee. Weekly exposure can confound gains; no real player/game labels or randomly shuffled splits. Small deterministic diagnostics reuse fixture windows without large model/storage cost or performance claims. Stop at Stage 06 gate; owner review/new authorization is next.

## Archived Stage 05 completion record

Owner authorized Stage 06 after the following Stage 05 results; previous gate statements are historical.

## Stage 05 execution plan (completed 2026-10-12)

Recorded before implementation: point-in-time player/transaction contracts and fixture constraints; fail-closed legality and unknown settings; HOLD/add/add-drop enumeration; protected roster value; eligible daily lineups/timing/caps/locks; reusable correlated scenario screening/refinement and paired SE; explanatory fixture CLI; focused acceptance tests; full Python/C++ checks, package/CLI verification, this handoff and a focused dev commit. Stop at Stage 05 gate.

## Stage 05 completed work and changed files

- New src/fantasy_optimizer/optimization.py: typed PlayerSnapshot, TransactionRules, Action/Assessment and SearchConfig; observed/ingested-at validation, ownership/roster consistency, bounded enumeration and explicit constraint provenance.
- Enumerates HOLD, no-drop adds and one-add/one-drop pairs. Known ownership/addability, positions, droppability/protected players, IR restrictions, locks, roster capacity, acquisition caps and budget violations reject; absent required settings produce unverified actions. No hardcoded live slot/budget defaults.
- Live Yahoo adapter cannot be verified without authorized settings/samples. Added yahoo_constraints_unverified boundary with null settings and unverified source. CLI live optimization refuses before any requests; unknown data is not presented as feasible.
- Deterministic maximum-cardinality daily eligible matching, preserved locks, fixed validated opponent selections, explicit acquisition effective time and earliest-game remaining-cap policy. Completed games excluded from future starts; active partial games, unknown IR state or multiple same-day games/player require verified semantics and return unverified planning. This is a documented lineup heuristic, not exhaustive lineup optimization.
- Reuses one seeded full scenario bank and common screening prefixes across actions. Default 256-sample screen/4096-sample finalists; HOLD always refined. Matchup credit gain uses paired SE; category deltas are explanatory, not summed Z-scores. Only refined positive gains exceeding two paired SEs within the explicit value-loss guard can outrank HOLD. Adaptive screening is a heuristic and can miss improvements.
- Reports before/after win chance and tie-adjusted credit, category win/tie deltas, active lineups, legal/rejection/unverified reasons, roster changes and separate added/dropped long-term proxies/loss. Default loss guard zero; missing value is not invented; protected players always retained. No fitted penalty weights or transactions.
- New src/fantasy_optimizer/optimization_fixture.py: 8 fictional players, 24 handmade game forecasts, explicit synthetic rules and six scenario variants. Separate from weekly aggregates and Stage 04 fixture. New tests/test_optimization.py: 35 focused acceptance cases.
- Updated simulation.py: extracted evaluate_scenarios for shared outcomes/credit without changing arithmetic or existing simulate results except its source hash. Updated cli.py and tests/test_smoke.py for fantasy optimize --fixture and Stage 05 status; CI includes offline optimization. Updated README; new docs/OPTIMIZATION.md and docs/benchmarks/stage05.json record limits and measured fixture results.
- This STATUS.md remains the single handoff; archived previous-stage evidence is preserved below. No Stage 06 work, C++ source change, merge/push/publication or live Yahoo data.

## Stage 05 verification — actual outcomes

Commands ran at project root; uv used UV_CACHE_DIR=/tmp/fantasy-stage01-uv-cache.

- uv sync --locked --offline --group dev: passed, 15 resolved/14 checked; no new dependency downloads or installs.
- uv run --offline --no-sync ruff check .: passed; ruff format --check .: passed, 20 files. mypy src: passed, 13 source files. Initial formatting/type/closure findings fixed; no diagnostics suppressed.
- uv run --offline --no-sync pytest -q: **112 passed in 6.53 seconds**. Focused tests/test_optimization.py: **35 passed in 0.89 seconds** before full verification. No tests skipped. An initial cap test expected a later target start with only two earliest-game slots; corrected its explicit cap to three, consistent with the documented policy rather than changing code to force an outcome.
- Acceptance coverage: empty available pool/no addability, full roster/no-drop rejection, protected/locked drops, invalid positions, acquisitions/budgets, ownership/IR/waiver/unknown settings, vacancies, timing/game caps/completed games, flexible-position matching, hand-calculated fifth marginal category, impossible comeback, HOLD above harmful/uncertain moves, explicit long-term guard/tradeoff, tie credit, shortlist refinement, seed/input-order/Python/native parity and paired arithmetic. Future observed/ingested player/settings snapshots reject; no point-in-time leakage claims beyond these fixture inputs.
- cmake -S cpp -B build/cpp -G Ninja -DCMAKE_BUILD_TYPE=Debug and cmake --build build/cpp: passed, existing targets current. No changed C++ required new analysis; wheel rebuild also ran the configured project clang-tidy checks.
- Standard ctest --test-dir build/cpp --output-on-failure **outside sandbox tracing: passed 3/3 in 1.50 seconds**, retaining ASan/UBSan/leak checks and explicit just-built Debug native/reference parity. No sanitizer suppression needed this stage.
- git ls-files -z -- '*.cpp' '*.hpp' | xargs -0 -r clang-format-14 --dry-run --Werror: passed. git diff --check and staged diff checks passed. Elevated git add/git commit succeeded for the 11 Stage 05 files on dev; this final observed handoff is included in that local commit. Main/remotes untouched.
- Installed fantasy optimize --fixture run twice: byte-identical JSON. CLI tests verify live refusal/invalid configuration. All six fixture variants executed and saved measured results; baseline recommendation ADD:target/DROP:streamer, other variants HOLD.
- uv build --offline: passed, source distribution and native cp312 Linux wheel. Isolated Python -I -S imported package/native module from extracted wheel with paths asserted, matched full installed optimizer output/provenance, matched Python/native ranked actions and loaded prior simulation/forecast fixtures.
- README/optimization local links, CI YAML parse and saved code/simulator/scenario provenance consistency checks: passed. Remote GitHub CI not run or claimed. Live adapter/calibration/transaction behavior not tested because settings/access remain unverified and auto-execution is out of scope.

## Stage 05 measured fixture result, decisions and gate

Saved docs/benchmarks/stage05.json uses seed 42, 256 screening/4096 finalist scenarios and the installed Release native module. Default enumerates 13 actions, screens 3 legal actions and refines 2. Baseline HOLD win chance 0; target-for-streamer 0.1298828125; paired gain SE 0.0052533673; long-term proxy loss 0 (add value 2, drop value 1). This is a toy result, not calibrated Yahoo advice.

One raw scenario cube is 8,650,752 bytes; validation/copies/results/hashing require additional memory. Single in-process runs of the six fixtures measured 0.035–0.100 seconds locally. No production speedup, calibrated uncertainty or optimal lineup-search claim. Ordinal long-term proxies are reported separately; default refuses their loss. Sampling the full bank upfront preserves common prefixes; screening reduces action evaluation cost, not bank allocation. Action/scenario budgets fail explicitly instead of silently truncating.

**Fixture acceptance met:** legal/unverified filters, all specified rejection/HOLD/marginal-category/impossible-comeback tests, reproducible ranked fixture CLI, read-only explanations and handoff checks. **Live portion blocked/unverified:** cannot construct a verified actual-Yahoo rules adapter without authorized samples; explicit fixture/unverified adapters are the mandatory fallback. Waiver priority/FAB claims and full Yahoo bench/IR transitions are not assumed. No configured tests skipped; remote CI remains unverified. Stop at Stage 05; owner review/new authorization is next.

## Archived Stage 04 completion record

Owner authorized Stage 05 after these verified Stage 04 results; its historical gate is superseded for Stage 05 only.

## Stage 04 execution plan (completed 2026-10-12)

Recorded before implementation: validated roster/schedule/eligibility and observed-count inputs; explicit scoring/ties; reusable seeded joint scenarios; Python reference followed by measured C++20/nanobind kernel; arithmetic/constraints/parity/convergence tests; 1k/10k/20k benchmarks; all configured Python/C++ checks, package/CLI verification and this handoff. Stop at Stage 04 gate.

## Stage 04 completed work and changed files

- New src/fantasy_optimizer/simulation.py: typed game forecasts, rules, selection and scenario bank; count/metadata/bounds validation; schedule/roster/eligibility/locks/daily slots/caps/scoring-period checks; exact weighted percentages and TO inversion; selectable scoring/category ties/zero attempts/matchup ties; observed totals plus remaining games only.
- Completed games are skipped; actively playing games reject full-game forecasts to prevent double-counting. Empty remaining schedules work. Half-credit matchup ties have separate expected credit and SE; they are not mislabeled as full wins.
- New src/fantasy_optimizer/matchup_fixture.py: 40 handmade player-games, ten fictional players and three joint vectors/game. Unknown minutes/availability probabilities stay null. Stage 03 weekly vectors are not converted to fake games.
- Stable per-game seeded joint bootstrap, input/scenario/Python-code hashes, model/simulator/rules versions and NumPy version. Reuse the same bank across selections; adding/reordering unrelated games preserves existing RNG streams. Raw batch capped at 256 MiB; selected copies/hashing use additional memory.
- New cpp/include/fantasy_optimizer/matchup.hpp, cpp/src/matchup_kernel.cpp and cpp/src/matchup.cpp: shared C++20 count/comparison kernel plus batched nanobind binding with contiguous int64 inputs and owned int8 output; no Python calls or RNG inside scenario loops.
- New cpp/tests/test_matchup.cpp (Catch2 2.13.8 locally), cpp/tests/run_parity.py and tests/test_simulation.py. CTest explicitly loads its freshly built extension because editable-wheel redirection otherwise selects the installed Release module.
- Updated cpp/CMakeLists.txt, pyproject.toml and uv.lock: pinned NumPy 2.2.6/nanobind 2.9.2; scikit-build-core 0.11.6 builds native wheels. Existing fixtures remain packaged. Sanitized standalone tests exercise the same kernel; the interpreter-loaded binding omits ASan instrumentation.
- Updated cli.py/tests/test_smoke.py: fixture-only fantasy simulate with seed/scenarios/backend/benchmark and live gating. Updated CI to install tools before native uv build and run offline simulation. Updated README; new docs/SIMULATION.md and docs/benchmarks/stage04.json record contracts, limitations and measured costs.
- This STATUS.md is the single handoff. No later-stage implementation, system-wide dependency installation, live request, storage schema change or remote operation.

## Stage 04 verification — actual outcomes

Commands ran at project root; uv used UV_CACHE_DIR=/tmp/fantasy-stage01-uv-cache.

- Initial restricted uv add failed DNS; approved elevated uv add installed pinned numpy==2.2.6 and nanobind==2.9.2. Elevated uv sync downloaded the pinned native build backend. Subsequent uv sync --locked --offline --group dev passed (15 resolved/14 checked).
- uv run --offline --no-sync ruff check .: passed; ruff format --check .: passed (17 files). mypy src: passed (11 source files). Initial formatting/type diagnostics were fixed, not suppressed.
- uv run --offline --no-sync pytest -q: **77 passed in 8.19 seconds** on the final full check. Tests include weighted FG/FT, exact ratio ties, inverted TO, five-win/half-category/majority scoring, zero attempts, observed partial matchup totals, completed games and active-game rejection, empty schedules, invalid inputs, constraints, shared streams, reproducibility, convergence and exact stochastic/deterministic native parity. No tests skipped.
- cmake -S cpp -B build/cpp -G Ninja -DCMAKE_BUILD_TYPE=Debug; cmake --build build/cpp: passed. CMake automatically selects root .venv Python when no interpreter override is supplied. Project changed sources compiled with clang-tidy and warnings-as-errors. Third-party nanobind implementation is excluded from project lint policy; its headers use system include treatment.
- Standard sandbox CTest failed with LeakSanitizer's ptrace limitation. ASAN_OPTIONS=detect_leaks=0 ctest passed 3/3 as a constrained diagnostic. Then **standard ctest --test-dir build/cpp --output-on-failure outside sandbox tracing passed 3/3 in 1.56 seconds**, including final Catch2 ASan/UBSan/leak checks and the just-built Debug native parity tests. Full leak verification is now confirmed locally for these targets.
- git ls-files -z -- '*.cpp' '*.hpp' | xargs -0 -r clang-format-14 --dry-run --Werror: passed; explicit dry-run of all four new C++ source/header/test files also passed before tracking. git diff --check passed.
- uv run --offline --no-sync fantasy simulate --fixture --benchmark: passed; saved final 1k/10k/20k timings in docs/benchmarks/stage04.json. A preliminary 1k Python measurement was 0.118 s; final warmed kernel medians below. No production/end-to-end speedup claim.
- Two installed fantasy simulate --fixture runs produced byte-identical JSON. CLI tests verify live refusal and invalid scenario counts.
- uv build --offline: passed, sdist and native cp312 Linux wheel produced. Isolated Python -I -S imported both package/native module from an extracted wheel (paths asserted), matched Python/native results and all saved benchmark result/provenance fields, and loaded Stage 03 packaged forecasts successfully.
- Elevated git add and git commit succeeded for the 18 Stage 04 files on dev; restricted Git metadata did not block the local commit. Tracked formatting and staged diff checks passed; this final handoff update is included in that commit. No main/remote changes.
- Local README/simulation documentation links and CI YAML parsing passed. Remote GitHub CI not run/claimed. No Yahoo/live calibration tests run because data/settings are unverified.

## Stage 04 measured performance and acceptance

Installed Release wheel, GCC 11.4.0, Python 3.12.14, NumPy 2.2.6, seed 42, 40 synthetic player-games. Warm-up excluded; kernel medians over three repetitions. Preparation measured once separately; final reporting/hashing/CLI startup/I/O excluded.

| Scenarios | Preparation (s) | Python kernel (s) | C++ kernel (s) |
|---:|---:|---:|---:|
| 1,000 | 0.025638 | 0.098992 | 0.001273 |
| 10,000 | 0.171255 | 1.026109 | 0.013294 |
| 20,000 | 0.321204 | 2.024418 | 0.026835 |

**Fixture acceptance met:** hand-calculated arithmetic/remaining-games/ties/five-win scoring; fixed-seed native repeatability and exact shared-sample Python/native parity; three benchmark sizes and saved regression tests; handoff updated. No runtime thresholds or GPU work.

**Limitations/decisions:** games sampled independently, so within-vector dependence survives but cross-game/player context does not. Monte Carlo SE measures sampling precision; a zero observed SE does not prove certainty. Actual Yahoo scoring/constraints, game forecasts and calibration remain unverified. Partial NBA-game forecasts and verified live adapters are deferred explicitly. All configured local checks passed; actual GitHub CI still unverified. Stage 05, merge and publication await owner approval.

## Archived Stage 03 completion record (historical)

The following prior handoff is preserved as history; its then-current gate and leak-check limitation are superseded by the Stage 04 authorization/results above.

### Completed execution plan and work

- Read required handoff/stage/design/contracts/validation documents; recorded Stage 03 plan before implementation. Initial workspace was clean on dev, preserving the owner's previous commits.
- Implemented typed seven-day count windows, point-in-time splits, revision selection, duplicate handling and rejection of overlapping or impossible records. Training requires window end, observation and ingestion at/before origin.
- Built long-run and half-life-28-day recency means plus approximate empirical-Bayes shrinkage. The prior uses only contemporaneously known other players, equal-player mass, and clipped within/between-player moment estimates (2–20 pseudo-windows). No unsupported prior is invented when peers are absent.
- Sampled complete joint count vectors, preserving within-player category dependence and makes/attempts constraints. Unknown exposure gets a shared heuristic multiplier; small histories use a wider multiplier. Raw percentages are not independently averaged or forecast. Missing counts remain null; unknown game count, availability probability and minutes stay null.
- Added per-player running count/decay aggregates, copied as-of feature snapshots, provenance/config hashes, model/code versions, deterministic player RNG streams and content-addressed JSON artifacts under ignored models/weekly-counts-v1.
- Added 48 explicitly handmade weekly vectors for four fictional players, separate from Stage 02's coarse season aggregate. No season totals were converted to fabricated games/weeks.
- Implemented fantasy forecast --fixture, --model, --seed, --samples, --benchmark and --output. Live forecasts refuse execution before creating artifacts.
- Benchmarked all three baselines over 40 rolling-origin cases each, with per-stat MAE, empirical 80% coverage, threshold Brier and probability Monte Carlo SE. No complex ML, matchup simulation or waiver recommendations.
- Added offline forecasting to CI and documented exact measured results and failure cases in docs/FORECASTING.md.

### Changed files

- New: src/fantasy_optimizer/forecasting.py, forecast_fixture.py, fixtures/forecast.json; tests/test_forecasting.py; docs/FORECASTING.md.
- Updated: src/fantasy_optimizer/cli.py, tests/test_smoke.py, .github/workflows/ci.yml, README.md, this STATUS.md.
- No dependencies, lockfile, DuckDB schema, C++ sources, Git protections or remote publication changed.

### Verification — actual outcomes

Commands ran at the repository root, with UV_CACHE_DIR=/tmp/fantasy-stage01-uv-cache for uv:

- uv sync --locked --offline --group dev: passed, resolved 13/checked 12 packages.
- uv run --offline --no-sync ruff check . and ruff format --check .: passed (13 files formatted). Initial import/line-length findings fixed; none suppressed.
- uv run --offline --no-sync mypy src: passed, 9 source files. Initial Optional-count typing errors fixed using explicit checked count access, preserving missingness.
- uv run --offline --no-sync pytest -q: **55 passed in 5.60 seconds**. Added point-in-time/future correction/late ingestion tests, missing/zero counts, small samples, invalid makes/points/timestamps, overlap/conflicting revisions, shrinkage/fallback, joint sample integrity, deterministic input ordering/seeds, serialization, incremental aggregates, immutable saved features, rolling-origin metrics, artifact hashes and CLI gating.
- fantasy forecast --fixture --benchmark --output /tmp/fantasy-stage03-final-artifacts: passed; measured all three baselines with seed 42 and 256 samples. Final numbers below and in docs/FORECASTING.md.
- Installed CLI rerun twice: byte-identical stdout and one content-addressed artifact; serialized artifact forecasts matched output.
- uv build --offline: passed, sdist/wheel produced. Isolated Python imported forecast_fixture from the wheel (asserted .whl/ module path), loaded packaged fixtures, and matched all four CLI forecasts and code hash.
- CMake Debug configure/build: passed, existing targets unchanged. Tracked C++ clang-format-14 dry-run: passed.
- Standard CTest: failed with LeakSanitizer's ptrace fatal error. ASAN_OPTIONS=detect_leaks=0 ctest --test-dir build/cpp --output-on-failure: passed 1/1; ASan/UBSan retained. Full leak validation remains unverified; no global suppression.
- README/forecast local links and offline CI YAML parsing: passed. git diff --check passed before this handoff; final diff check follows its update.
- No live Yahoo requests, real-history evaluation, remote GitHub CI, merge or push performed.

### Measured synthetic benchmark (40 cases/model)

| Model | PTS MAE | FGA MAE | TO MAE | PTS 80% coverage | PTS threshold Brier |
|---|---:|---:|---:|---:|---:|
| long_run | 9.2438 | 8.4635 | 0.8409 | 1.000 | 0.2802 |
| recency | 7.7342 | 7.0440 | 0.8644 | 1.000 | 0.2461 |
| shrinkage | 9.1400 | 7.8606 | 0.9149 | 1.000 | 0.2575 |

Recency reduces PTS/FGA error on the smooth synthetic trend; TO does not improve.
It is a provisional fixture default, not a proven live winner. Shrinkage improves
sparse-history behavior but is not promoted as universally superior. Shared
exposure uncertainty makes intervals conservative on this toy dataset. Earlier
unwidened toy intervals undercovered; exposure multipliers were added because
unknown context requires uncertainty, not tuned to achieve nominal coverage.
The final overly broad intervals still do not establish calibration.

### Decisions, acceptance and blockers

- Stage 03 fixture acceptance met: no later-known input enters training, counts/missingness/small samples and shrinkage tested, deterministic forecasts and versioned serialization verified, objective rolling benchmarks documented.
- Honest granularity fallback: only seven-day aggregate forecasts, not a claimed per-player-game contract backed by absent game history. No verified schedule/availability proxies exist; those assumptions remain unknown.
- Running aggregates support O(stats) new-window updates; fixture CLI rebuilds its tiny selected history. Persistent incremental caches and live storage adapters are deferred until verified windows justify them.
- Whole-vector empirical resampling preserves observed within-vector dependence, with shared uncalibrated exposure shocks. No cross-player/teammate absence model or precise tail-support claim.
- Monte Carlo mean/probability SE concerns finite sampling, not model uncertainty. Coverage's plug-in binomial SE is only a diagnostic with repeated players; zero observed failures do not prove calibrated coverage. Synthetic sample size does not justify a live calibration curve.
- Yahoo approval/authorized histories, real model quality, full LeakSanitizer and remote CI remain blocked/unverified. No successful live tests are claimed.
- Files are saved in the main checkout on dev. The session cannot commit because .git is read-only; no temporary branch or bundle workflow is needed.
- Stop here. Stage 04 requires the owner's next instruction.

## Session history (append concise dated entries)

- Initial planning files prepared; no code or GitHub remote created.
- 2026-10-12: Read required instructions and referenced constraints in full. Owner approved project name and root layout. Implemented Stage 00 local scaffold; C++ build/analysis/format and constrained CTest verified; supplementary CLI tests 5/5 passed. Shell DNS and read-only Git metadata block dependency lock/pinned Python validation and Git acceptance. Stop here pending environment repair; exact continuation above.
- 2026-10-12 continuation: Owner explicitly approved a public repository and push. git status --short now succeeds; main has no commits and no remote. git add of the intended scaffold/docs failed with read-only .git/index.lock (exit 128). uv sync --group dev retried with writable /tmp cache/runtime directories and failed DNS (exit 2); getent hosts github.com pypi.org returned no addresses. gh auth status failed (exit 1), while GitHub connector get_user_login verified bk-del; connector lacks repository creation. Tracked C++ enumeration is empty because staging failed, so no tracked-format success is claimed. No source changes or new test passes this session. Existing blockers remain; authorization persists for completion once session permissions/network are repaired.
- 2026-10-12 ROS fix: Owner installed pinned environment and generated uv.lock; pytest crashed loading ROS plugins from PYTHONPATH. Reproduced failure, enabled pytest's --disable-plugin-autoload in project config, and verified 5/5 pinned tests plus Ruff/format/mypy/installed CLI. C++ build and constrained CTest also passed. README lockfile note corrected. Continue owner terminal checks, staging and approved publication; no Stage 01 work.

- 2026-10-12 workflow simplification: Owner replaced feature branches with direct development on dev and verified merges into protected main. Updated all active guidance and preserved the Stage 01 implementation; integration remains the next action.

- 2026-10-12 integration: Copied the ten Stage 01 implementation files from the temporary checkout into the main workspace on dev, preserving the simplified branch guidance. No Git metadata or private credentials copied; verification is being rerun.

- 2026-10-12 workspace verification: uv sync --locked --offline --group dev passed; Ruff lint and format passed (7 files); mypy passed (5 source files); pytest passed 29/29. CMake Debug configure/build passed; CTest passed 1/1 with ASAN_OPTIONS=detect_leaks=0 (full leak checking remains unverified). Tracked C++ clang-format-14 dry-run and git diff --check passed. Installed fantasy auth status and fantasy audit --fixture passed without credentials. No live Yahoo access or remote CI verified.

- 2026-10-12 Stage 02: Owner authorized continuation and installed DuckDB 1.4.5. Implemented and verified fixture-only version-1 storage/ingestion directly in the main dev checkout. 41 tests, lint, formatting, mypy, package/CLI checks and constrained CTest passed; standard LeakSanitizer and live Yahoo/remote CI remain unverified. Owner review/commit and the Stage 02 stop gate are next.

- 2026-10-12 owner terminal verification: `uv run fantasy sync --fixture` succeeded with 7 changed snapshots, no failed sources, 4,993,024 database bytes and 0.319983 seconds. `uv run fantasy sync --fixture --scenario changed` succeeded with 3 changed snapshots, no failed sources, 7,876,608 bytes and 0.294168 seconds. Both reported synthetic fixture mode and schema version 1. Owner CLI verification is confirmed; full leak checks, remote CI and live Yahoo access remain unverified. Next action: review and commit working-tree changes on dev; no Stage 03 authorization yet.

- 2026-10-12 Stage 03: Owner authorized the next stage. Implemented weekly fixture forecasting directly on dev; all 55 tests, lint/format/mypy, CLI/artifact/wheel verification and constrained CTest passed. Benchmarked 40 synthetic origins per baseline; recency is provisional, intervals uncalibrated. Live forecasts and Stage 04 remain disabled/unimplemented. Next: owner review/commit and stage gate.

- 2026-10-12 Stage 04: Owner authorized only fixture matchup simulation. Implemented Python/C++20/nanobind joint count simulation, explicit synthetic schedule/rules and common scenario banks directly on dev; 77 Python tests and 3/3 full-sanitizer CTest targets passed, with lint/format/mypy/native wheel/CLI verification. Saved 1k/10k/20k benchmark results and limitations. No live Yahoo, merge, publication or Stage 05 work. Stop at Stage 04 gate.

- 2026-10-12 Stage 05: Owner authorized the next stage. Implemented fixture-only legal add/drop/HOLD search, deterministic eligible lineups, shared correlated sample screening/refinement, paired uncertainty and explicit long-term value protection directly on dev. 112 Python tests and 3/3 full-sanitizer CTest targets passed, with lint/format/mypy/package/CLI checks and saved six-variant results. Live Yahoo constraints remain unverified; no transactions, Stage 06, merge or publication. Stop at Stage 05 approval gate.

- 2026-10-12 Stage 06: Owner authorized context/breakout stage. Added fixture-only sustained weekly count-shift diagnostics, pre-registered future-label/exposure contract and explicit context/model/calibration/uplift skips; Stage 03 baseline retained. 120 Python tests and 3/3 full-sanitizer CTest targets plus lint/format/mypy/package/CLI checks passed on dev. Zero usable labels and live Yahoo evidence insufficient; no fitted model, injury narrative, Stage 07, merge or publication. Stop at Stage 06 gate.
