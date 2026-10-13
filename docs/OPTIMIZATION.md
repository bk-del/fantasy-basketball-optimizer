# Stage 05: fixture add/drop/HOLD optimizer

`fantasy optimize --fixture` provides read-only suggestions, never transactions.
Live optimization refuses execution. Yahoo league transaction settings, ownership,
waiver/IR rules and game forecasts remain unverified. The fixture adapter supplies
explicit synthetic constraints; the Yahoo boundary returns `yahoo_unverified`
with null settings. No guessed Yahoo field mapping is presented as verified.
Authorized samples and settings validation are prerequisites for a live adapter.

```bash
uv run fantasy optimize --fixture
uv run fantasy optimize --fixture --scenario none_available
uv run fantasy optimize --fixture --scenario acquisition_cap
uv run fantasy optimize --fixture --scenario bad_moves
uv run fantasy optimize --fixture --scenario impossible_comeback
uv run fantasy optimize --fixture --scenario unknown_settings
uv run fantasy optimize --fixture --seed 42 --screening-samples 256 --finalist-samples 4096
uv run fantasy optimize --fixture --backend python
```

## Inputs and legality

`PlayerSnapshot` records ownership, addability, market state, droppability,
position eligibility, IR state, protection and optional long-term proxy, plus
observation/ingestion times and evidence version. `TransactionRules` records
provenance, total roster capacity, remaining acquisitions/budget, per-add cost,
waiver policy, IR move permission, acquisition effective time and lineup policy.
The Stage 04 `Rules` still supplies active slots, rosters, period/timezone,
scoring/ties, locked selections and remaining-game caps. Every snapshot must be
observed and ingested at/before as-of; ownership must match those rosters.
Unknown ownership is never treated as a free agent. Duplicate or contradictory
snapshots fail explicitly rather than silently choosing a revision.

Enumerate HOLD, a no-drop add and every one-add/one-drop pair. Do not enumerate
standalone drops, multi-add plans or waiver bids. Full rosters reject no-drop adds.
Protected/undroppable players and all supplied lineup locks forbid drops. Reject
known ownership/addability, position, IR, capacity, acquisition-cap and budget
violations. Missing required transaction settings or player permissions produce
**unverified** actions. Known contradictions can still reject an action while
also reporting missing settings. No unavailable setting is filled with a default.

Only explicit immediate/delayed free-agent additions are supported. A snapshot
marked on waivers is rejected for an immediate add even if its clearance time is
in the past: the optimizer needs a newly observed free-agent/addable state.
Priority/FAB claims cannot be assumed successful. Unsupported waiver/lineup
policies are unverified. The simple fixture capacity includes all supplied roster
members; it is not a complete live Yahoo active/bench/IR-slot transition model.
HOLD consumes neither acquisition nor budget, so missing transaction budgets
need not prevent a baseline when the daily lineup policy itself is known.

## Active lineups and opportunity cost

For each feasible resulting roster, build daily maximum-cardinality eligible
matchings, preserving supplied locks. Eligibility is the intersection of game
and player-snapshot positions. IR occupants do not start. Stable start-time/game
ordering resolves choices; earlier dates consume remaining-game caps first.
Opponent selections are held fixed and validated. Newly acquired players only
start games strictly after the explicit effective time. Completed games remain
in observed totals; actively playing games require a remaining-count contract
and are unverified here. Multiple same-day games for a player also require verified
lineup semantics and are rejected from planning.

This matching is a transparent heuristic, not an exhaustive matchup-optimal
lineup search. An added bench player may not start while occupied positions stay
filled. The report shows every planned active game/slot so this limit is reviewable.
A game assigned to the bench contributes no counts. No NBA schedule is inferred
from Stage 03 weekly aggregates: all 24 game forecasts in Stage 05 are handmade.

Long-term values are supplied ordinal proxies, not inferred dollars or calibrated
rest-of-season points. Report the added/dropped values and
`max(0, drop_value - add_value)` separately from matchup odds. The default maximum
value loss is zero. Missing values or excessive loss prevent promotion above HOLD,
even when an action has positive current-week gain. Protected players cannot be
dropped regardless of a proxy. The Python `SearchConfig` can explicitly change
the loss limit; no fitted weights or arbitrary conversion into probability units.

## Objective, common samples and explanations

Reuse Stage 04 joint count aggregation through `evaluate_scenarios`; no independent
category-win flags or duplicated scoring implementation. Exact FG/FT ratios,
TO inversion and actual supplied scoring/tie policies remain in that reference/native
pipeline. Rank by gain in matchup credit over HOLD: default at-least-five rules
make this exactly the change in win probability. Under majority scoring with
half-credit ties, expected credit and full-win probability are reported separately.
Category win/tie probability deltas are sensitivity explanations, not the objective.

Generate one seeded bank for all supplied games at the finalist sample count.
Every action first uses the same 256-scenario prefix. Legality is the first cheap
filter; sample screening then retains value-safe actions within the configurable
close margin of the best estimate, allowing two paired standard errors. HOLD is
always retained. Finalists reuse the full 4,096 scenarios. The generation cost is
paid up front; screening reduces per-action arithmetic, not the bank's memory.
Reports distinguish screened and refined sample counts, and each action's before
and after estimates use the same batch. Excluded actions cannot be promoted.

Calculate gain SE from the sample variance of **paired action-minus-HOLD credit**,
not two independent error bars. A refined acquisition must have gain greater than
two paired SEs and pass the long-term guard to outrank HOLD. Remaining rows sort by
matchup gain; ties resolve by stable action key. Explanations identify rejection,
missing settings, screening, nonpositive/uncertain gains or excessive/unknown value
loss. A zero empirical SE does not prove certainty; adaptive screening/promotion
is a heuristic, not a multiple-comparison confidence guarantee. Screening can miss
an improvement and does not establish forecast calibration.

At most 256 enumerated actions by default and 32..20,000 scenarios are permitted;
`SearchConfig` exposes an explicit bounded action budget. Stage 04 caps the raw
scenario cube at 256 MiB. Large requests fail before uncontrolled evaluation;
there is no silent candidate truncation or fabricated performance estimate.

Each result records as-of, seed, constraint/data/model/optimizer/simulator versions,
NumPy version, normalized input/config/forecast/scenario hashes and both Python
code hashes. No persistent decision database/schema or backtesting framework was
added. If even HOLD cannot be simulated, return no ranked odds, retain the no-action
HOLD fallback and report unverified input reasons. This fallback is not a legal
transaction recommendation.

## Fixture evidence and verification

The default fixture has two players per team, four pool candidates and three
handmade games per player. The protected anchor has long-term proxy 10; the streamer
1; the target 2. The target has a 50/50 whole-vector play/zero bootstrap for each
independent game, not a verified availability probability. Game samples remain
independent across players/days; real context and calibration are unknown.

Seed 42, 256 screening and 4,096 finalist samples: recommend
`ADD:target/DROP:streamer`. Current-week full-win chance changes from 0 to
0.1298828125, with paired gain SE 0.00525337 and long-term proxy loss zero.
HOLD ranks above the inferior replacement. The no-available, cap, bad-move,
impossible-comeback and missing-setting variants all retain HOLD. Tests also
construct a hand-calculated four-win baseline where only BLK changes and creates
the fifth win, proving the optimizer uses matchup outcome rather than category
sum/Z-scores.

[Saved fixture evaluation measurements](benchmarks/stage05.json) record all six
variants and provenance. One raw bank is 8,650,752 bytes (4,096 × 24 × 11 × 8);
validation/selected copies/results consume additional memory. Single in-process
runs measured approximately 0.035–0.100 seconds locally using the installed Release
native module. These are observed fixture timings, not a speedup/production latency
claim. No native code, dependencies, storage schema or system packages changed.
The Stage 04 saved benchmark remains a historical measurement of its then-current
Python code hash; the scoring extraction changes that hash, not its arithmetic.

Focused tests cover no pool/no addability, full roster, protected/locked drops,
invalid positions, acquisitions/budget/IR/waivers/unknown settings, vacancies,
transaction timing/caps/completed games, flexible-position matching, impossible
comeback, one marginal category, HOLD above harmful moves, explicit proxy tradeoffs,
tie-adjusted scoring, shortlist refinement, seed/input-order/backend parity,
paired SE and rejection of future observed/ingested ownership/settings. All output
is fixture-only and read-only. CI runs the offline CLI; actual remote CI remains
unverified. Stop at Stage 05 approval gate; Stage 06 requires new authorization.
