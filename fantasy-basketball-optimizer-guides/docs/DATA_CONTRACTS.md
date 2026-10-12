# Minimal contracts and storage entities

These are **internal proposed schemas**, not claims that Yahoo exposes every field. Stage 01 will classify each field as confirmed, derivable, unavailable, or optional.

## Canonical entities

- `league`: league_key, season, scoring_type, nine categories, timezone, lineup rules, acquisitions policy, waiver rules, league_settings_version.
- `player`: yahoo_player_key, canonical display name, team if exposed, eligible positions, source_updated_at.
- `game_observation`: player_key, NBA game/date identifier **if available**, counts (FGM/FGA, FTM/FTA, 3PM, PTS, REB, AST, STL, BLK, TO), minutes **if available**, source and event timestamps. If only aggregate windows are available, store windowed facts separately; **do not synthesize fake per-game rows**.
- `roster_snapshot`: league_key, fantasy_team_key, player_key, status, observed_at, source_watermark.
- `availability_snapshot`: league_key, player_key, eligible/addable/waiver status, observed_at.
- `matchup_snapshot`: scoring-period identifier, fantasy_team identifiers, observed category totals, as-of time.
- `feature_snapshot`: player_key, as_of, feature_definition_version, source_watermark, values, missingness flags.
- `forecast`: player_key, horizon, as_of, model_version, distribution parameters/scenario reference, input hash.
- `decision_run`: created_at, as_of, data version, model version, simulator version, RNG seed, constraints version, ranked actions, predicted utility, diagnostic warnings.
- `decision_outcome`: decision_run_id, evaluation window, observed outcome, known confounders.

## Time semantics

- `event_at`: when a real NBA/league event took place, where known.
- `observed_at`: when the system could first have known it (API observation or source publication).
- `ingested_at`: when local persistence completed.
- Backtests may only read records with `observed_at <= simulated_decision_time`.
- If historic Yahoo data lacks genuine `observed_at`, do not pretend to recover historical injury/roster ownership perfectly; label backtests accordingly.

## Forecast payload contract (conceptual)

Per player-game: availability probability; eligible positions; distribution for minutes when observable; raw makes/attempts and counting stats; joint uncertainty or a reproducible scenario sampler; explicit missing inputs; provenance and version. Forecast daily schedule/game count only if confirmed by Yahoo data.

## Decision output contract

Action (`ADD`, `DROP`, `HOLD` or combined add/drop), feasibility/rejection reasons, roster before/after, weekly win probability with Monte Carlo standard error, category impact, longer-term cost or proxy, evidence source versions. An optimized score is not the same as a calibrated probability.
