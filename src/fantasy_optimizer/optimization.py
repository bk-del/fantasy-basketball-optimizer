"""Read-only fixture action search, with fail-closed transaction constraints."""

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from math import isfinite, sqrt
from pathlib import Path
from typing import Literal, cast
from zoneinfo import ZoneInfo

import numpy as np
from numpy.typing import NDArray

from fantasy_optimizer.simulation import (
    CATEGORIES,
    Counts,
    GameForecast,
    Rules,
    ScenarioBank,
    Selection,
    evaluate_scenarios,
    sample_scenarios,
)


@dataclass(frozen=True)
class PlayerSnapshot:
    key: str
    owner: Literal["ours", "opponent", "free"] | None
    addable: bool | None
    market: Literal["free_agent", "waiver"] | None
    droppable: bool | None
    eligible_slots: tuple[str, ...]
    in_ir: bool | None
    protected: bool
    long_term_value: float | None
    observed_at: datetime
    ingested_at: datetime
    version: str
    waiver_clears_at: datetime | None = None


@dataclass(frozen=True)
class TransactionRules:
    version: str
    source: Literal["fixture", "yahoo_unverified"]
    observed_at: datetime
    ingested_at: datetime
    roster_capacity: int | None
    acquisitions_remaining: int | None
    budget_remaining: int | None
    acquisition_cost: int | None
    waiver_policy: Literal["free_agents_only"] | None
    ir_moves_allowed: bool | None
    effective_at: datetime | None
    lineup_policy: Literal["daily"] | None


@dataclass(frozen=True)
class Action:
    add: str | None = None
    drop: str | None = None

    @property
    def key(self) -> str:
        return "HOLD" if self.add is None else f"ADD:{self.add}/DROP:{self.drop or '-'}"


@dataclass(frozen=True)
class Assessment:
    action: Action
    status: Literal["feasible", "rejected", "unverified"]
    reasons: tuple[str, ...]
    roster: tuple[str, ...]
    value_loss: float | None


@dataclass(frozen=True)
class SearchConfig:
    seed: int = 42
    screening_samples: int = 256
    finalist_samples: int = 4096
    close_margin: float = 0.05
    max_value_loss: float = 0.0
    backend: Literal["python", "cpp"] = "cpp"
    max_actions: int = 256


def yahoo_constraints_unverified(as_of: datetime) -> TransactionRules:
    """No verified Yahoo samples exist; do not map guessed Yahoo fields."""
    return TransactionRules(
        "yahoo-unverified",
        "yahoo_unverified",
        as_of,
        as_of,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )


def _known_at(observed: datetime, ingested: datetime, as_of: datetime) -> bool:
    return (
        observed.utcoffset() is not None
        and ingested.utcoffset() is not None
        and observed <= ingested <= as_of
    )


def validate_inputs(
    players: tuple[PlayerSnapshot, ...],
    transactions: TransactionRules,
    rules: Rules,
    as_of: datetime,
    config: SearchConfig,
) -> dict[str, PlayerSnapshot]:
    if as_of.utcoffset() is None:
        raise ValueError("as_of must have a timezone.")
    if not _known_at(transactions.observed_at, transactions.ingested_at, as_of):
        raise ValueError("Transaction settings are not known at as_of.")
    if not transactions.version or transactions.source not in (
        "fixture",
        "yahoo_unverified",
    ):
        raise ValueError("Unknown constraint provenance.")
    if (
        not 32 <= config.screening_samples <= config.finalist_samples <= 20000
        or type(config.max_actions) is not int
        or not 1 <= config.max_actions <= 10000
        or config.seed < 0
        or not isfinite(config.close_margin)
        or config.close_margin < 0
        or not isfinite(config.max_value_loss)
        or config.max_value_loss < 0
    ):
        raise ValueError("Invalid search configuration (32..20000 samples).")
    for value in (
        transactions.roster_capacity,
        transactions.acquisitions_remaining,
        transactions.budget_remaining,
        transactions.acquisition_cost,
    ):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Invalid transaction budget/capacity.")
    if transactions.effective_at is not None and (
        transactions.effective_at.utcoffset() is None
        or transactions.effective_at < as_of
    ):
        raise ValueError("Transaction effective time must be at/after as_of.")
    by_key = {player.key: player for player in players}
    if len(by_key) != len(players) or any(not p.key or not p.version for p in players):
        raise ValueError("Duplicate/invalid player snapshot.")
    for player in players:
        if (
            player.owner not in (None, "ours", "opponent", "free")
            or player.market not in (None, "free_agent", "waiver")
            or any(
                value is not None and type(value) is not bool
                for value in (player.addable, player.droppable, player.in_ir)
            )
            or type(player.protected) is not bool
        ):
            raise ValueError("Invalid player ownership/permission snapshot.")
        if not _known_at(player.observed_at, player.ingested_at, as_of):
            raise ValueError("Player snapshot is not known at as_of.")
        if player.long_term_value is not None and (
            not isfinite(player.long_term_value) or player.long_term_value < 0
        ):
            raise ValueError("Invalid long-term value proxy.")
        if (
            player.waiver_clears_at is not None
            and player.waiver_clears_at.utcoffset() is None
        ):
            raise ValueError("Waiver time requires a timezone.")
    for team, owner in ((0, "ours"), (1, "opponent")):
        if set(rules.rosters[team]) != {p.key for p in players if p.owner == owner}:
            raise ValueError("Roster and ownership snapshots disagree.")
    return by_key


def enumerate_actions(
    players: tuple[PlayerSnapshot, ...], rules: Rules
) -> tuple[Action, ...]:
    """Unknown ownership still appears as unverified, never silently addable."""
    candidates = sorted(p.key for p in players if p.owner in ("free", None))
    drops = sorted(rules.rosters[0])
    return (Action(),) + tuple(
        Action(add, drop) for add in candidates for drop in (None, *drops)
    )


def assess(
    action: Action,
    players: dict[str, PlayerSnapshot],
    tx: TransactionRules,
    rules: Rules,
    forecasts: tuple[GameForecast, ...],
    as_of: datetime,
) -> Assessment:
    roster = tuple(sorted(rules.rosters[0]))
    if action.add is None:
        if action.drop is not None:
            return Assessment(
                action,
                "rejected",
                ("Standalone drops are outside this search.",),
                roster,
                None,
            )
        if tx.lineup_policy != "daily" or tx.source != "fixture":
            return Assessment(
                action, "unverified", ("Daily lineup rules are unverified.",), roster, 0
            )
        return Assessment(
            action, "feasible", ("HOLD uses no acquisition or budget.",), roster, 0
        )
    missing, rejected = [], []
    if action.add not in players:
        return Assessment(
            action, "rejected", ("Unknown candidate snapshot.",), roster, None
        )
    candidate = players[action.add]
    if tx.source != "fixture":
        missing.append("Authorized Yahoo settings/sample mapping is unavailable.")
    for field in (
        "roster_capacity",
        "acquisitions_remaining",
        "budget_remaining",
        "acquisition_cost",
        "waiver_policy",
        "ir_moves_allowed",
        "effective_at",
        "lineup_policy",
    ):
        if getattr(tx, field) is None:
            missing.append(f"Missing setting: {field}.")
    if tx.waiver_policy not in (None, "free_agents_only") or tx.lineup_policy not in (
        None,
        "daily",
    ):
        missing.append("Unsupported waiver or lineup policy.")
    if candidate.owner is None or candidate.addable is None or candidate.market is None:
        missing.append("Ownership/addability/market state is unverified.")
    if candidate.owner not in ("free", None) or candidate.addable is False:
        rejected.append("Player is owned or not addable.")
    if candidate.market == "waiver":
        # Do not pretend a pending claim will be won or a cleared player is a fr
        rejected.append(
            "Waiver claims require verified priority/FAB and "
            "resolution; not an immediate free-agent add."
        )
    if candidate.in_ir is None:
        missing.append("Candidate IR state is unverified.")
    elif candidate.in_ir and tx.ir_moves_allowed is not True:
        rejected.append("Candidate is restricted by IR rules.")
    if not candidate.eligible_slots:
        missing.append("Candidate position eligibility is unverified.")
    elif not set(candidate.eligible_slots) & set(rules.slots):
        rejected.append("No eligible active roster position.")
    dropped = players.get(action.drop) if action.drop else None
    if action.drop and (dropped is None or action.drop not in roster):
        rejected.append("Drop is not on our roster.")
    if dropped is not None:
        if dropped.protected:
            rejected.append("Protected player cannot be dropped.")
        if dropped.droppable is None or dropped.in_ir is None:
            missing.append("Drop/IR permission is unverified.")
        if dropped.droppable is False:
            rejected.append("Player cannot be dropped.")
        if dropped.in_ir and tx.ir_moves_allowed is not True:
            rejected.append("IR drop is restricted.")
        if any(
            g.player_key == dropped.key and s.game_key == g.game_key
            for s in rules.locked
            for g in forecasts
        ):
            rejected.append("Drop conflicts with a locked lineup.")
    after = tuple(
        sorted((set(roster) - ({action.drop} if action.drop else set())) | {action.add})
    )
    if tx.roster_capacity is not None and len(after) > tx.roster_capacity:
        rejected.append("Roster is full; a drop is required.")
    if tx.acquisitions_remaining == 0:
        rejected.append("Acquisition cap reached.")
    if (
        tx.budget_remaining is not None
        and tx.acquisition_cost is not None
        and tx.acquisition_cost > tx.budget_remaining
    ):
        rejected.append("Acquisition budget is insufficient.")
    values = (candidate.long_term_value, dropped.long_term_value if dropped else 0.0)
    add_value, drop_value = values
    loss = (
        None
        if add_value is None or drop_value is None
        else max(0.0, drop_value - add_value)
    )
    status: Literal["feasible", "rejected", "unverified"] = (
        "rejected" if rejected else "unverified" if missing else "feasible"
    )
    reasons = (
        tuple(rejected + missing)
        if rejected or missing
        else (
            "Explicit fixture ownership, addability, "
            "eligibility, IR, locks, capacity and acquisition budgets passed.",
            "Free-agent add is effective at the supplied "
            "transaction time; no waiver claim is assumed.",
        )
    )
    return Assessment(action, status, reasons, after, loss)


def plan_lineup(
    forecasts: tuple[GameForecast, ...],
    rules: Rules,
    players: dict[str, PlayerSnapshot],
    as_of: datetime,
    opponent: tuple[Selection, ...],
    added: str | None,
    effective_at: datetime | None,
) -> tuple[Selection, ...]:
    """Maximum-cardinality daily matching; earliest games consume remaining caps."""
    if any(s.team != 1 for s in opponent):
        raise ValueError("Opponent selections must belong to team 1.")
    games = {g.game_key: g for g in forecasts}
    if any(s.game_key not in games for s in rules.locked):
        raise ValueError("Locked game lacks a forecast.")
    selections = [s for s in opponent if s.team == 1]
    our_locks = [s for s in rules.locked if s.team == 0]
    if any(games[s.game_key].player_key not in rules.rosters[0] for s in our_locks):
        raise ValueError("Locked player is missing from roster.")
    for selection in selections + our_locks:
        game = games.get(selection.game_key)
        if game is None or game.player_key not in players:
            raise ValueError(
                "Locked/opponent lineup lacks verified game/player inputs."
            )
        player = players[game.player_key]
        if game.ends_at > as_of and (
            player.in_ir is not False or selection.slot not in player.eligible_slots
        ):
            raise ValueError("Locked/opponent IR state or eligibility is inconsistent.")
    selections.extend(our_locks)
    days: dict[str, list[GameForecast]] = {}
    timezone = ZoneInfo(rules.timezone)
    for game in forecasts:
        if game.player_key not in rules.rosters[0] or game.ends_at <= as_of:
            continue
        if not rules.period_start <= game.starts_at < game.ends_at <= rules.period_end:
            continue
        if game.starts_at <= as_of:
            raise ValueError("Partially played games need remaining-count forecasts.")
        if game.player_key == added and (
            effective_at is None or game.starts_at <= effective_at
        ):
            continue
        player = players[game.player_key]
        if player.in_ir is True:
            continue
        if player.in_ir is None:
            raise ValueError("Roster IR state is unverified.")
        days.setdefault(
            game.starts_at.astimezone(timezone).date().isoformat(), []
        ).append(game)
    remaining = rules.remaining_game_caps[0] - sum(
        games[s.game_key].ends_at > as_of for s in our_locks
    )
    if remaining < 0:
        raise ValueError("Locked games exceed remaining cap.")
    locked_keys = {s.game_key for s in our_locks}

    def assign(
        game: GameForecast,
        visited: set[str],
        slots: dict[str, GameForecast],
        blocked: set[str],
    ) -> bool:
        eligible = set(game.eligible_slots) & set(
            players[game.player_key].eligible_slots
        )
        for slot in sorted(eligible & set(rules.slots) - blocked):
            if slot in visited:
                continue
            visited.add(slot)
            if slot not in slots or assign(slots[slot], visited, slots, blocked):
                slots[slot] = game
                return True
        return False

    for day, daily_games in sorted(days.items()):
        blocked = {
            s.slot
            for s in our_locks
            if games[s.game_key].starts_at.astimezone(timezone).date().isoformat()
            == day
        }
        slots: dict[str, GameForecast] = {}

        if len({g.player_key for g in daily_games}) != len(daily_games):
            raise ValueError(
                "Multiple same-day games per player need verified lineup semantics."
            )
        for game in sorted(daily_games, key=lambda g: (g.starts_at, g.game_key)):
            if game.game_key not in locked_keys:
                assign(game, set(), slots, blocked)
        matched = sorted(
            (Selection(g.game_key, 0, slot) for slot, g in slots.items()),
            key=lambda s: (games[s.game_key].starts_at, s.game_key, s.slot),
        )
        selections.extend(matched[:remaining])
        remaining -= len(matched[:remaining])
    return tuple(sorted(selections, key=lambda s: (s.team, s.game_key, s.slot)))


@dataclass
class Evaluation:
    outcomes: NDArray[np.int8]
    credit: NDArray[np.float64]
    selections: tuple[Selection, ...]


def _se(values: NDArray[np.float64]) -> float:
    return sqrt(float(values.var(ddof=1)) / len(values))


def optimize(
    players: tuple[PlayerSnapshot, ...],
    transactions: TransactionRules,
    rules: Rules,
    forecasts: tuple[GameForecast, ...],
    opponent: tuple[Selection, ...],
    observed: tuple[Counts, Counts],
    as_of: datetime,
    config: SearchConfig | None = None,
) -> dict[str, object]:
    config = config or SearchConfig()
    by_key = validate_inputs(players, transactions, rules, as_of, config)
    action_count = 1 + sum(p.owner in ("free", None) for p in players) * (
        1 + len(rules.rosters[0])
    )
    if action_count > config.max_actions:
        raise ValueError("Action enumeration exceeds the explicit search budget.")
    assessments = [
        assess(action, by_key, transactions, rules, forecasts, as_of)
        for action in enumerate_actions(players, rules)
    ]
    # Sampling once at the larger size gives every action identical common prefixes.
    bank = sample_scenarios(
        forecasts, seed=config.seed, scenarios=config.finalist_samples
    )
    prefix = replace(bank, values=bank.values[: config.screening_samples])
    input_hash = sha256(
        repr(
            (
                tuple(sorted(players, key=lambda p: p.key)),
                transactions,
                rules,
                tuple(sorted(opponent, key=lambda s: (s.team, s.game_key))),
                observed,
                as_of,
            )
        ).encode()
    ).hexdigest()
    provenance: dict[str, object] = {
        "fixture_only": True,
        "read_only": True,
        "optimizer_version": "waiver-fixture-v1",
        "simulator_version": "joint-matchup-v1",
        "numpy_version": np.__version__,
        "as_of": as_of.isoformat(),
        "seed": config.seed,
        "constraints_version": transactions.version,
        "constraints_source": transactions.source,
        "input_hash": input_hash,
        "forecast_input_hash": bank.input_hash,
        "scenario_hash": sha256(bank.values.tobytes()).hexdigest(),
        "config_hash": sha256(repr(config).encode()).hexdigest(),
        "code_hash": sha256(Path(__file__).read_bytes()).hexdigest(),
        "simulator_code_hash": sha256(
            Path(evaluate_scenarios.__code__.co_filename).read_bytes()
        ).hexdigest(),
        "model_versions": sorted({g.model_version for g in forecasts}),
        "data_versions": sorted({p.version for p in players}),
        "screening_samples": config.screening_samples,
        "finalist_samples": config.finalist_samples,
        "max_value_loss": config.max_value_loss,
    }
    plans: dict[str, tuple[Selection, ...]] = {}
    for i, assessment in enumerate(assessments):
        if assessment.status != "feasible":
            continue
        changed = replace(rules, rosters=(assessment.roster, rules.rosters[1]))
        try:
            plans[assessment.action.key] = plan_lineup(
                forecasts,
                changed,
                by_key,
                as_of,
                opponent,
                assessment.action.add,
                transactions.effective_at,
            )
        except ValueError as error:
            assessments[i] = replace(
                assessment, status="unverified", reasons=(str(error),)
            )
    feasible = [a for a in assessments if a.action.key in plans]
    if not feasible or feasible[0].action.key != "HOLD":
        return {
            **provenance,
            "recommended_action": "HOLD",
            "diagnostics": ["HOLD cannot be simulated with unverified lineup inputs."],
            "ranked_actions": [],
            "filtered_actions": [_filtered(a) for a in assessments],
        }

    def evaluate(assessment: Assessment, batch: ScenarioBank) -> Evaluation:
        changed = replace(rules, rosters=(assessment.roster, rules.rosters[1]))
        outcomes, credit = evaluate_scenarios(
            forecasts,
            batch,
            plans[assessment.action.key],
            changed,
            as_of,
            observed,
            backend=config.backend,
        )
        return Evaluation(outcomes, credit, plans[assessment.action.key])

    screen = {a.action.key: evaluate(a, prefix) for a in feasible}
    eligible = [
        a
        for a in feasible
        if a.value_loss is not None and a.value_loss <= config.max_value_loss
    ]
    best = max(float(screen[a.action.key].credit.mean()) for a in eligible)
    final_keys = {"HOLD"}
    for assessment in eligible:
        difference = screen[assessment.action.key].credit - screen["HOLD"].credit
        uncertainty = 2 * _se(difference)
        if (
            float(screen[assessment.action.key].credit.mean())
            + uncertainty
            + config.close_margin
            >= best
        ):
            final_keys.add(assessment.action.key)
    final = {
        a.action.key: evaluate(a, bank) for a in feasible if a.action.key in final_keys
    }
    rows = []
    for assessment in feasible:
        refined = assessment.action.key in final_keys
        evaluated = final if refined else screen
        baseline = evaluated["HOLD"]
        current = evaluated[assessment.action.key]
        difference = current.credit - baseline.credit
        gain, paired_se = float(difference.mean()), _se(difference)
        safe_value = (
            assessment.value_loss is not None
            and assessment.value_loss <= config.max_value_loss
        )
        recommendable = assessment.action.key == "HOLD" or (
            refined and safe_value and gain > 2 * paired_se
        )
        if assessment.action.key == "HOLD":
            explanation = "HOLD preserves roster value and uses no acquisition."
        elif assessment.value_loss is None:
            explanation = "Long-term value is unknown; retain HOLD."
        elif not safe_value:
            explanation = (
                f"Value loss {assessment.value_loss} exceeds "
                f"limit {config.max_value_loss}; retain HOLD."
            )
        elif not refined:
            explanation = "Screened out; fewer samples and no recommendation."
        elif gain <= 0:
            explanation = "No positive matchup gain over HOLD."
        elif not recommendable:
            explanation = "Gain does not exceed two paired Monte Carlo standard errors."
        else:
            explanation = (
                "Positive paired matchup gain within the explicit value-loss limit."
            )
        row: dict[str, object] = {
            "action": assessment.action.key,
            "add": assessment.action.add,
            "drop": assessment.action.drop,
            "feasibility": "feasible",
            "legal_reasons": list(assessment.reasons),
            "roster_before": sorted(rules.rosters[0]),
            "roster_after": list(assessment.roster),
            "samples": len(current.credit),
            "refined": refined,
            "win_probability_before": float((baseline.credit == 1).mean()),
            "win_probability_after": float((current.credit == 1).mean()),
            "matchup_credit_before": float(baseline.credit.mean()),
            "matchup_credit_after": float(current.credit.mean()),
            "matchup_credit_gain": gain,
            "paired_gain_mc_se": paired_se,
            "win_probability_mc_se": _se((current.credit == 1).astype(float)),
            "category_tie_deltas": dict(
                zip(
                    CATEGORIES,
                    (
                        (current.outcomes == 0).mean(axis=0)
                        - (baseline.outcomes == 0).mean(axis=0)
                    ).tolist(),
                    strict=True,
                )
            ),
            "category_win_deltas": dict(
                zip(
                    CATEGORIES,
                    (
                        (current.outcomes == 1).mean(axis=0)
                        - (baseline.outcomes == 1).mean(axis=0)
                    ).tolist(),
                    strict=True,
                )
            ),
            "long_term_value_loss": assessment.value_loss,
            "added_long_term_value": by_key[assessment.action.add].long_term_value
            if assessment.action.add
            else None,
            "dropped_long_term_value": by_key[assessment.action.drop].long_term_value
            if assessment.action.drop
            else None,
            "evidence_versions": {
                key: by_key[key].version for key in assessment.roster
            },
            "recommendable": recommendable,
            "active_lineup": [
                {"game_key": s.game_key, "team": s.team, "slot": s.slot}
                for s in current.selections
            ],
            "explanation": explanation,
        }
        rows.append(row)
    rows.sort(
        key=lambda row: (
            not bool(row["recommendable"]),
            -cast(float, row["matchup_credit_gain"]),
            str(row["action"]),
        )
    )
    return {
        **provenance,
        "recommended_action": rows[0]["action"],
        "ranked_actions": rows,
        "filtered_actions": [
            _filtered(a) for a in assessments if a.status != "feasible"
        ],
        "evaluated_actions": len(screen),
        "refined_actions": len(final),
        "diagnostics": [
            "Synthetic fixture suggestions; no transactions submitted or claimed.",
            "Long-term value is an explicit ordinal proxy, "
            "not calibrated economic value.",
            "Daily maximum-cardinality lineups and "
            "earliest-game caps are deterministic heuristics, "
            "not matchup-optimal lineup search.",
            "Paired Monte Carlo SE is sampling precision, "
            "not calibration; screening can miss an improvement.",
            "Waiver claims and live Yahoo rules remain unverified.",
        ],
    }


def _filtered(assessment: Assessment) -> dict[str, object]:
    return {
        "action": assessment.action.key,
        "feasibility": assessment.status,
        "reasons": list(assessment.reasons),
    }
