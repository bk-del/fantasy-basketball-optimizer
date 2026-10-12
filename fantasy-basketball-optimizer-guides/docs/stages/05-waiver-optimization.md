# Stage 05 — Waiver add/drop/hold optimizer

**Goal:** recommend legal actions that improve matchup win odds and respect longer-term roster opportunity cost.

## Implement

- Build a verified rules/constraints adapter using actual Yahoo league settings and a fixture adapter for unknown settings. Never hardcode roster slots or acquisition limits as live facts.
- Enumerate valid add/drop pairs and `HOLD`. Filter ownership/addability, positional eligibility, IR restrictions, waiver conditions, acquisition budgets and lineup locks. If an action requires unprovided league settings, mark it **unverified** rather than feasible.
- For each feasible action, simulate active lineups, games that can realistically start and full 9-CAT matchup outcome. Reuse scenarios. Rank by improvement in probability of winning matchup (tie handling per rules), not summed Z-scores.
- Include long-horizon replacement cost and protected players; initially transparent rule-based penalty or Pareto report, not poorly trained weights. Report current-week and longer-term value separately.
- Implement explanatory output showing before/after win chance, category deltas, matchup uncertainty, why an action is legal, and why HOLD might be best.
- Use first-pass cheap screening and more samples for close finalists. Keep comparisons reproducible.

## Acceptance criteria

- Tests: no available player, full roster, protected drop, invalid positional replacement, acquisition cap, one marginal category, impossible comeback, HOLD outranks bad moves.
- No auto-execution or claiming transactions; read-only suggestions only.
- `fantasy optimize --fixture` produces a ranked result with diagnostics and reproducible seed.
- Update `STATUS.md`.
