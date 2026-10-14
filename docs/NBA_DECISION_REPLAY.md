# Chronological hypothetical fantasy decisions

Protocol frozen before execution, 2026-10-13. This is descriptive research on
already examined NBA periods, never a fresh holdout, Yahoo transaction backtest,
or championship estimate. The authoritative executable protocol is `PROTOCOL` in
`src/fantasy_optimizer/decision_replay.py`; its digest is recorded with results.

Twelve Monday UTC origins run from 2025-10-27 through 2026-01-12. Eligibility
requires five known same-season rows and a row no more than 14 days old. Origins
with fewer than 24 eligible players are explicitly skipped. Rank up to 96
eligible players by a fixed past production score. Four seeded drafts per week
assign eight players each to our roster, opponent and free-agent pool. Drafts
reset weekly; ownership is entirely synthetic and may overlap between leagues.
All players occupy unrestricted UTIL slots, are active for all their actual games,
and face no games cap, IR, waiver delay, or protection. Permit one immediate
add/drop or HOLD, giving the same 65 feasible actions for every strategy.

Season-to-date, recency14d, and checksum-verified frozen research LightGBM/MLP
models forecast only from origin-known history. The original frozen model fit
and calibration precede every decision; current all-history refits are forbidden.
HOLD uses the recency simulation only for its diagnostic forecast. Maximize mean
matchup credit, then category credit, preserving HOLD on ties. Historical first
publication/revision times are unknown: the existing explicit next-day
availability assumption applies, with actual retrieval retained in provenance.

Unknown future exposure is sampled from four past seven-day observed-row counts,
including zero weeks. Joint primitive vectors are sampled from the last 28 days
(or ten last rows if empty), scaled to each model's conditional primitive means,
rounded, and converted to coherent makes/attempts/points. Zero empirical components
use deterministic rounded model means. There is no invented Gaussian noise.
This pragmatic rescaled bootstrap is uncalibrated; player samples are independent
and do not encode shared pace or teammate redistribution. The same random numbers
are reused across actions/models. Historical schedule gaps, source DNP rows,
rounding, and missing support can affect this approximation.

Only after every action at an origin is frozen does the outcome path sum actual
subsequent NBA box scores over seven days. No future game, lineup, or team filter
selects the draft. Missing outcome rows contribute no recorded statistics and are
never labelled injuries or confirmed DNPs. Existing Python simulation arithmetic
compares aggregate FG/FT makes and attempts with integer crossproducts, gives a
ratio-category tie if either side has zero attempts, and reverses turnovers.
Tied categories count half; matchup credit is one for more categories won than
lost, half for a tie. This path reuses the existing simulator comparison contract;
the production optimizer and C++ kernel remain unchanged.

Report realized category wins/credits, matchup wins/ties/credits, transactions,
and ex-post regret against the best of the *same* 65 available actions. Ex-post
best is diagnostic, never a selection input. Paired versus HOLD uncertainty
resamples whole calendar weeks (2,000 seeded bootstrap replicates), retaining
within-week league overlap. Report 2025 and 2026 separately. The very small number
of independent weeks, synthetic ownership, fixed opponent, unverified schedule
and simplistic rules sharply limit generalization. No strategy is promoted from
this backtest. Waiting, season-long roster value, opponent reactions, unknown
future waivers and real position constraints remain unsupported.

Reproduce from repository root (cached data and advanced dependencies required):

```bash
UV_CACHE_DIR=/tmp/fantasy-stage01-uv-cache uv run --offline --no-sync python scripts/backtest_nba_decisions.py
UV_CACHE_DIR=/tmp/fantasy-stage01-uv-cache uv run --offline --no-sync pytest tests/test_decision_replay.py -q
```

The script writes `docs/benchmarks/nba-decision-replay.json`, containing complete
individual choices, origin input hashes, distinct outcome hashes, frozen learner
checksums, source provenance, protocol, summary, runtime and process peak RSS.
Full real-NBA replay has **not been executed**. Owner usage-limit steering stopped
new experiments before launch; the JSON currently records `NOT_EXECUTED`, protocol,
and exact resume command. Four tiny contract tests pass (HOLD, legal actions,
shooting/turnover arithmetic, deterministic count identities, temporal refusal and
outcome separation). This does not establish working end-to-end historical replay
or any strategy advantage. Running the script replaces this placeholder with
actual observations.

For adding pre-origin GRU/GNN forecasts, `run_replay(..., forecast_provider=...)`
passes the provider only origin-known feature arrays, stable player IDs and origin.
Return one mapping per strategy with `primitive` means (players × 11),
`trained_through` (latest training/selection/calibration cutoff), and
`artifact_sha256`. Invalid means, overlapping labels, absent checksums and cutoffs
at/after the origin are rejected. No external model has been evaluated here.
