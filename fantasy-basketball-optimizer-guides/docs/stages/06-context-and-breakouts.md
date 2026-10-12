# Stage 06 — Context and breakout detection under Yahoo-only constraints

**Goal:** improve forecasts for emerging players without inventing teammate/injury context.

## Implement

- Revisit `docs/YAHOO_CAPABILITIES.md`. Only create features supported by Yahoo data. Candidate features: recency/minutes if provided, per-game/opponent/role-related stat changes where available, availability statuses, scoring-window deltas and transactions. Do not claim usage rate, depth-chart hierarchy or injury on/off splits exist unless audited.
- Define a **pre-registered breakout label** (e.g. sustained multi-week gain in category-adjusted replacement value); choose minimum games/availability and label horizon before modelling. Ensure labels use future outcomes but features use only known-at-T facts.
- Add change-point/shift detection and a lightweight supervised model (LightGBM only if enough observations and meaningful features exist). Probability calibration and comparison with baseline are mandatory.
- For role/injury proxies, explicitly annotate coverage, missingness and ambiguity; widen uncertainty when key context unavailable.
- Train locally on time-based splits; avoid impressive-looking but invalid randomly shuffled player-game splits.

## Acceptance criteria

- Report precision/recall/calibration and decision uplift versus Stage 03 (or document insufficient Yahoo data to establish improvement).
- Model is optional: baseline stays active until improvement on strictly later periods is established.
- Missing feature sources cause explicit skip, not fabricated injury narratives.
- Update `STATUS.md`.
