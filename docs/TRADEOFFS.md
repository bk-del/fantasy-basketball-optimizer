# Stage 09 proposal: category tradeoffs and Pareto display

Owner selected this extension explicitly. Scope is an opt-in, read-only view of
existing fixture optimization results. It does not change the at-least-five-category
objective, protection/value guard, ranked recommendations or transaction behavior.
No adaptive punt policy, new model, search algorithm or service is included.

**User value:** make category sacrifices and roster-value costs visible together,
including alternatives that remain incomparable. Default output shows two separate
point-estimate frontiers: matchup credit versus lower long-term value loss, and
selected category win-probability deltas versus lower long-term value loss. Category
ties are shown separately; no unavailable category calibration or standard error is
invented. Turnover effects already use the simulator's lower-is-better orientation.

**Data requirement:** existing refined, feasible action rows from a single fixture
run, with the same finalist sample count, category win/tie deltas, matchup credit,
win probability and sampling SE, paired gain SE, and explicit roster-value loss.
Missing or screening-only rows are excluded with reasons. Do not compare independent
runs, different sample budgets or unverified actions. No new Yahoo data is required
for the display; live quality/availability remains unverified.

**Cost:** bounded pairwise dominance checks on at most 256 rows, up to ten objectives;
O(actions squared times objectives), small derived JSON and console formatting.
Existing NumPy evaluates bounded pairwise matrices one objective at a time (under
0.4 MB of temporary arrays at the cap). No extra simulation, DB write or dependency. Runtime/storage are measured
on actual fixture output after implementation, not forecast from production usage.

**Measurable success / rejection:** hand-calculated crossing/dominated/equal rows
produce the exact expected frontier; fixture comparisons preserve incumbent action,
probabilities, seed and underlying saved artifacts; category changes/cost/uncertainty
are visible without inventing missing values. Benchmark 256 rows within 0.1 seconds
per view on this development host (median five runs), with no additional simulator
call; reject/revise the extension if correctness, invariance or this budget fails.
This is display correctness and measured operational cost, not proven decision uplift.
No live win-rate improvement can be tested without historical snapshots/outcomes.

**Rollback:** omit `--tradeoffs` or stop using `fantasy tradeoffs`; normal optimizer
and saved run artifacts remain unchanged. Revert this focused extension commit if
needed. No model migration, data rewrite or scheduler rollback is required.

## Usage

```bash
uv run fantasy optimize --fixture --tradeoffs
uv run fantasy run --fixture --tradeoffs
uv run fantasy tradeoffs --fixture --input data/fixture-runs/RUN_HASH.json
uv run fantasy tradeoffs --fixture --input /tmp/optimization.json --format json --categories PTS,REB,AST
```

The standalone command accepts a saved run artifact or a standalone optimizer JSON
report and writes no files. Its default text view shows all nine category effects,
including losses and tie changes, with action, win probability, gain uncertainty,
roster cost and both frontier memberships. `--categories` chooses display/frontier
axes only; it never changes scoring, recommendations or silently punts categories.
Run/optimize flags append a JSON view to console output, computed after the existing
pipeline; it is not stored inside or allowed to change cached recommendations.

Dominance uses point estimates: an action is no worse on every chosen objective
and strictly better on at least one. Exact equal points all remain on the frontier.
Sampling/model uncertainty may reverse that ordering. Frontier membership does not
mean recommendable: the incumbent's value guard and paired-gain rule still decide
that, and the existing explanation/recommendable flag is retained. Category frontier
axes are win-probability deltas, not summed Z-scores or expected half-tie credit.

See [fixture benchmark](benchmarks/stage09.json) and [operations](OPERATIONS.md).
Owner review and Stage 08 actual-output validation remain pending. No other Stage 09
extension, live operation, merge or publication is authorized by this selection.
