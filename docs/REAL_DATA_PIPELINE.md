# Real NBA pipeline audit and integration

Audit recorded before implementation, 2026-10-12. Owner authorizes completing this
milestone; previous stage gates are historical. No live Yahoo activation is implied.

| Connection at 42a5f83 | Audit finding |
|---|---|
| NBA Parquet → DuckDB → observations → weekly features | Working: checksum-verified 2025/2026 partitions, 64,695 player-games, 20,987 full observed weekly windows; no cohort cap in adapter. Older sparse/duplicate seasons excluded. |
| NBA identity → forecasts | NBA IDs work. Exact time-aware Yahoo mapping contract works but has zero verified real links. Fixture players are fictional and have no real mapping. |
| Features → forecast persistence | Existing weekly joint-count engine works through Python historical adapter; historical CLI only benchmarks, normal forecast CLI remains synthetic. No actual next-game inference or current production NBA artifact. |
| Forecasts → C++ simulation → optimization | C++ consumes complete joint game samples with correct makes/attempts and TO. Operations passes independent handmade game vectors: real weekly forecasts are disconnected from decisions. |
| Selection/calibration/versioning | Chronological 24-player research selects 28d, freezes hashes and separate residual calibration. Cap applies to benchmark development, calibration, evaluation and peers, not source loading/inference. No full-population selection or production NBA fit. |
| Registry/promotion/rollback | Atomic lifecycle tested for fixtures. Promotion uses PTS only, not appropriate to claim production 9-CAT validation. Historical benchmark uses separate one-use holdout guard; residual calibration does not change joint distributions. |
| Incremental updates/cache | Running sufficient statistics and operational caches work for fixtures. Historical windows cache by source/code/policy; source snapshot replacement rebuilds derived features. No configured automatic retrain/new-game policy; no real update loop. |
| Yahoo constraints and context | No verified credentials/sample/crosswalk/rules/history path. Live pipeline refuses. Injuries, current membership, availability, playing time and future schedule absent. |

Historical replay may use explicitly assumed next-day publication; actual retrieval
is retained. Strict forecasts before retrieval cannot use the snapshot. Original
publication/revision times cannot be recovered. Conditional per-game forecasts do
not imply a game is scheduled or that a player will participate. A hypothetical
fixture schedule can exercise constraints but cannot supply actual seven-day totals.

The original 24-player protocol and JSON remain a regression reference, with the
original code available at commit `42a5f83`. Its Jan–Apr 2026 final period has already
been inspected. The expanded protocol will distinguish a fresh late-2025-season
primary period from a larger 2026 replication and freeze selection before either.

## Connected implementation

`fantasy nba` is a scoped real-data entry point; original fixture commands remain
available. It reuses the historical adapter's checksum/coverage gates and reads the
same game/team Parquet join into `GameObservation`. `Population` prepares known
count summaries once per origin, using the original equal-weight, exponential
recency and empirical-Bayes estimators. Scalar weekly-reference tests establish
expected-count and prior-strength equivalence. Shared whole-vector exposure draws
retain makes/attempts/count dependence and recompute PTS from makes. Relative ages
avoid weight underflow for stale histories; no future exposure is inferred.

The full-population protocol includes all historically observed IDs and requires
one own origin-known observation in the target season. No positive-points, high-
minutes, current-roster or consecutive-week filter selects the population. Future
first-ever observations are excluded until one own record exists: the existing
engine cannot forecast an unidentified player with no history. All origin-known
players contribute to priors, including reserves and departed players. The season-
to-date baseline resets; recency/shrinkage may use earlier seasons. Segment labels
use only available historical minutes, excluding blank/unknown minute fields;
zero-stat rows stay in counts. This estimates performance conditional on source
rows, not participation or missing player-weeks.

Production fitting uses all 64,695 strictly available records for 697 supported
historical IDs. Membership in today's NBA roster is unknown. Forecasts describe
the next **recorded player-game row conditional on one occurring**, retain observed
DNP/zero rows, and expose unknown participation/minutes. `prediction_timestamp`
is the requested prediction origin; it is fixed for reproducibility. Data source,
cutoff, latest observation, ID, configuration/model/code version and seed are saved.
Every player has raw-count means, sample dispersion, intervals and joint samples.
Residual calibrated count intervals are additional marginal diagnostics; they do
not change the joint distribution. FG/FT uses raw makes/attempts throughout.

`fantasy nba run --fixture` binds the original eight fictional roles to exact NBA
IDs present in the cached rows: anchor 2544, streamer 201145, opponent-g 101108,
opponent-f 201142, target 201143, bad-target 200768, waiver-target 201144,
wrong-position 201572. This is an explicit fixture assignment, **not** a Yahoo
crosswalk or ownership claim. Positions, protection, values, transaction permissions
and schedule remain hypothetical. All 24 game distributions come directly from
actual NBA forecasts; handmade sample counts are discarded. HOLD, add/drop legality,
lineups, long-term guard, shared scenario banks and objective remain unchanged.

C++ receives the existing contiguous int64 arrays and performs count aggregation/
category comparisons. It contains no fitting logic. Real-distribution tests show
exact native/reference category outcomes, utility and ranked-action parity, points
identity, deterministic banks and empirical input-moment consistency at 10k draws.
Cross-player/game dependence and contextual tail support remain unmodelled. Monte
Carlo SE describes sampling precision; matchup probabilities remain uncalibrated.

## Lifecycle and updates

The separate NBA registry stores the development-selected configuration, earlier
calibration widths, all-count validation evidence, fit summaries and cutoff/data
watermark. Normal inference refuses wrong scope/code or later-selected models.
Explicit repeated train is idempotent; inference/run never alters the registry.
Manual candidate promotion requires comparable dataset/evaluation/scope and lower
normalized all-count validation loss, no worse than the best baseline. Earlier
approved records remain available for atomic rollback. The original fixture PTS
rule remains specific to fixtures. The research holdout guard is separate and
consumed before final evaluation; the final period cannot drive configuration tuning.

There is **no enabled automatic training/promotion policy**. Daily inference fits
newly known count summaries under the frozen configuration and calibration. It
reuses the existing lock and checksum-validated content cache; unchanged cutoff,
data/model/code/seed/sample inputs skip inference and decision evaluation. Changed
snapshots invalidate derived inputs. This finite cached snapshot needs only one
population pass per origin; there is no repeated per-player historical query.

Acquisition of new live NBA/Yahoo games remains disconnected: the historical
adapter intentionally gates these two complete regular seasons, not partial new
season exports. Its source/config changes rebuild derived windows, whereas the
canonical fixture store and running weekly aggregates support incremental updates.
Do not claim live incremental ingestion or automatically learned recalibration.
A verified new-season ingestion contract is part of the next milestone. Nothing
is redownloaded or a second raw-game store introduced here.

`fantasy auth status` actually returned `missing_auth`, `approval_declared=false`,
`network_checked=false`. Yahoo access, exact identity links, ownership, rules,
waiver/IR history, current injuries and future schedule remain unavailable. Current
seven-day NBA projections therefore explicitly report unavailable/null game counts.
The historical observed-week benchmark and hypothetical fixture matchup are
separately labelled and cannot substitute for real scheduled weekly predictions.

## Executed evidence and reproduction

The [expanded benchmark report](HISTORICAL_FORECAST_BENCHMARK.md#full-population-integration-milestone--completed-2026-10-12) contains exact CLI/check commands, chronological splits, all-category errors and calibration failures. [Recorded current outputs](benchmarks/nba-end-to-end.json) include eight prediction examples with every raw-count uncertainty field and the complete actual-distribution fixture decision; all 697 full joint forecasts remain in the ignored artifact identified there by SHA-256. [Full population metrics](benchmarks/nba-population.json) retain every evaluated model and minute segment, with compressed replay checksums. [CPU profiling](benchmarks/nba-performance.json) records native/reference parity at three scenario budgets.

Actual next recorded player-game means at the fixed cutoff (conditional on a row occurring):

| Verified historical ID/name | PTS | REB | AST |
|---|---:|---:|---:|
| 2544 / LeBron James | 20.491 | 6.762 | 8.232 |
| 201143 / Al Horford | 7.832 | 3.216 | 2.352 |
| 201145 / Jeff Green | 0.889 | 0.627 | 0.229 |

These include historical zero/DNP source support and do not imply current playing time or participation. Actual future seven-day NBA totals remain unavailable. The complete fixture simulation selects Horford for Green, 18.75% HOLD versus 49.90% simulated matchup win probability; HOLD, legal constraints and value guard remain present. Read the evidence's fixture assumptions and uncalibrated probability limitations before interpreting this example.
