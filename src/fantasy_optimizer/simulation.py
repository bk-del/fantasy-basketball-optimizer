"""Fixture-only correlated 9-CAT simulation; no schedule inference."""

import importlib
import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from math import isfinite, sqrt
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
from numpy.typing import NDArray

CATEGORIES = ("FG%", "FT%", "3PM", "PTS", "REB", "AST", "STL", "BLK", "TO")
Counts = tuple[int, ...]
MAX_COUNT = 10_000_000


def validate_counts(counts: Counts) -> None:
    if len(counts) != 11 or any(
        type(x) is not int or not 0 <= x <= MAX_COUNT for x in counts
    ):
        raise ValueError("Counts require eleven bounded nonnegative integers.")
    fgm, fga, ftm, fta, threes, pts = counts[:6]
    if fgm > fga or ftm > fta or threes > fgm or pts != 2 * fgm + threes + ftm:
        raise ValueError("Inconsistent makes/attempts/points.")


@dataclass(frozen=True)
class GameForecast:
    game_key: str
    player_key: str
    starts_at: datetime
    ends_at: datetime
    eligible_slots: tuple[str, ...]
    joint_samples: tuple[Counts, ...]
    model_version: str
    availability_probability: float | None = None
    expected_minutes: float | None = None
    missing_inputs: tuple[str, ...] = ("verified_availability", "verified_minutes")


@dataclass(frozen=True)
class Selection:
    game_key: str
    team: int
    slot: str


@dataclass(frozen=True)
class Rules:
    version: str
    rosters: tuple[tuple[str, ...], tuple[str, ...]]
    slots: tuple[str, ...]
    remaining_game_caps: tuple[int, int]
    timezone: str
    period_start: datetime
    period_end: datetime
    locked: tuple[Selection, ...] = ()
    scoring: Literal["at_least_five", "category_majority"] = "at_least_five"
    category_ties: Literal["zero", "half"] = "zero"
    matchup_ties: Literal["loss", "half", "win"] = "loss"
    zero_attempts: Literal["zero", "tie"] = "zero"


@dataclass(frozen=True)
class ScenarioBank:
    game_keys: tuple[str, ...]
    values: NDArray[np.int64]
    seed: int
    input_hash: str


def sample_scenarios(
    forecasts: tuple[GameForecast, ...], *, seed: int, scenarios: int
) -> ScenarioBank:
    """Bootstrap entire count vectors, with stable per-game RNG streams."""
    if not 1 <= scenarios <= 1_000_000 or seed < 0:
        raise ValueError("Require nonnegative seed and 1..1000000 scenarios.")
    ordered = sorted(forecasts, key=lambda game: game.game_key)
    if len({g.game_key for g in ordered}) != len(ordered):
        raise ValueError("Duplicate game key.")
    if scenarios * len(ordered) * 11 * 8 > 256 * 1024 * 1024:
        raise ValueError("Scenario batch exceeds the 256 MiB memory budget.")
    if len({(g.player_key, g.starts_at) for g in ordered}) != len(ordered):
        raise ValueError("Duplicate player-game schedule.")
    payload = []
    values = np.empty((scenarios, len(ordered), 11), dtype=np.int64)
    for index, game in enumerate(ordered):
        if (
            not game.game_key
            or not game.player_key
            or not game.model_version
            or game.starts_at.utcoffset() is None
            or game.ends_at.utcoffset() is None
            or game.ends_at <= game.starts_at
            or not game.joint_samples
            or not game.eligible_slots
        ):
            raise ValueError("Invalid game forecast metadata.")
        if game.availability_probability is not None and (
            not isfinite(game.availability_probability)
            or not 0 <= game.availability_probability <= 1
        ):
            raise ValueError("Invalid availability metadata.")
        if game.expected_minutes is not None and (
            not isfinite(game.expected_minutes) or game.expected_minutes < 0
        ):
            raise ValueError("Invalid minutes metadata.")
        for counts in game.joint_samples:
            validate_counts(counts)
        digest = sha256(f"{seed}:{game.game_key}".encode()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        indices = rng.integers(len(game.joint_samples), size=scenarios)
        values[:, index, :] = np.asarray(game.joint_samples, dtype=np.int64)[indices]
        payload.append(
            (
                game.game_key,
                game.player_key,
                game.starts_at.isoformat(),
                game.ends_at.isoformat(),
                game.eligible_slots,
                game.joint_samples,
                game.model_version,
                game.availability_probability,
                game.expected_minutes,
                game.missing_inputs,
            )
        )
    values.setflags(write=False)
    return ScenarioBank(
        tuple(g.game_key for g in ordered),
        values,
        seed,
        sha256(json.dumps(payload).encode()).hexdigest(),
    )


def prepare(
    forecasts: tuple[GameForecast, ...],
    bank: ScenarioBank,
    selections: tuple[Selection, ...],
    rules: Rules,
    as_of: datetime,
    observed: tuple[Counts, Counts],
) -> tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.int64]]:
    if as_of.utcoffset() is None:
        raise ValueError("as_of must have a timezone.")
    if len(observed) != 2:
        raise ValueError("Require observed totals for two teams.")
    if (
        len(rules.rosters) != 2
        or len(rules.remaining_game_caps) != 2
        or len(set(rules.rosters[0])) != len(rules.rosters[0])
        or len(set(rules.rosters[1])) != len(rules.rosters[1])
        or bool(set(rules.rosters[0]) & set(rules.rosters[1]))
        or len(set(rules.slots)) != len(rules.slots)
        or rules.period_start.utcoffset() is None
        or rules.period_end.utcoffset() is None
        or not rules.period_start <= as_of <= rules.period_end
    ):
        raise ValueError("Invalid scoring period/roster constraints.")
    league_timezone = ZoneInfo(rules.timezone)
    for counts in observed:
        validate_counts(counts)
    if (
        not rules.version
        or rules.scoring not in ("at_least_five", "category_majority")
        or rules.category_ties not in ("zero", "half")
        or rules.matchup_ties not in ("loss", "half", "win")
        or rules.zero_attempts not in ("zero", "tie")
        or any(type(cap) is not int or cap < 0 for cap in rules.remaining_game_caps)
    ):
        raise ValueError("Explicit valid fixture rules required.")
    expected = sample_scenarios(forecasts, seed=bank.seed, scenarios=1)
    if expected.input_hash != bank.input_hash or expected.game_keys != bank.game_keys:
        raise ValueError("Scenario bank does not match forecasts.")
    if bank.values.shape[1:] != (len(bank.game_keys), 11) or bank.values.shape[0] < 1:
        raise ValueError("Invalid scenario bank shape.")
    if bank.values.dtype != np.int64 or bank.values.ndim != 3:
        raise ValueError("Scenario bank requires an int64 game cube.")
    if np.any(bank.values < 0) or np.any(bank.values > MAX_COUNT):
        raise ValueError("Invalid scenario counts.")
    c = bank.values
    if (
        np.any(c[:, :, 0] > c[:, :, 1])
        or np.any(c[:, :, 2] > c[:, :, 3])
        or np.any(c[:, :, 4] > c[:, :, 0])
        or np.any(c[:, :, 5] != 2 * c[:, :, 0] + c[:, :, 4] + c[:, :, 2])
    ):
        raise ValueError("Inconsistent scenario counts.")
    games = {g.game_key: g for g in forecasts}
    if len({s.game_key for s in selections}) != len(selections):
        raise ValueError("Game selected more than once.")
    if any(lock not in selections for lock in rules.locked):
        raise ValueError("Locked assignments must be preserved.")
    indices, teams = [], []
    occupied: set[tuple[int, str, str]] = set()
    for selection in selections:
        game = games.get(selection.game_key)
        if game is None or selection.team not in (0, 1):
            raise ValueError("Unknown game/team.")
        if game.player_key not in rules.rosters[selection.team]:
            raise ValueError("Player is not on the selected roster.")
        if (
            selection.slot not in rules.slots
            or selection.slot not in game.eligible_slots
        ):
            raise ValueError("Ineligible slot.")
        if not rules.period_start <= game.starts_at < game.ends_at <= rules.period_end:
            raise ValueError("Game lies outside the scoring period.")
        if game.ends_at <= as_of:
            continue  # Already included in the caller's observed totals.
        if game.starts_at <= as_of:
            raise ValueError("Partially played games need remaining-count forecasts.")
        key = (
            selection.team,
            game.starts_at.astimezone(league_timezone).date().isoformat(),
            selection.slot,
        )
        if key in occupied:
            raise ValueError("Occupied daily lineup slot.")
        occupied.add(key)
        indices.append(bank.game_keys.index(selection.game_key))
        teams.append(selection.team)
    for team in (0, 1):
        if teams.count(team) > rules.remaining_game_caps[team]:
            raise ValueError("Remaining games cap exceeded.")
        for stat in range(11):
            # Bound aggregate products so native int64 ratio comparisons are exact.
            upper = observed[team][stat] + sum(
                int(bank.values[:, i, stat].max())
                for i, t in zip(indices, teams, strict=True)
                if t == team
            )
            if upper > MAX_COUNT:
                raise ValueError("Aggregate count exceeds exact-arithmetic bound.")
    return (
        np.ascontiguousarray(bank.values[:, indices, :]),
        np.asarray(teams, dtype=np.int64),
        np.asarray(observed, dtype=np.int64),
    )


def reference_outcomes(
    values: NDArray[np.int64],
    teams: NDArray[np.int64],
    observed: NDArray[np.int64],
    zero_tie: bool,
) -> NDArray[np.int8]:
    """Small explicit reference: integer cross-products avoid rounding ties."""
    output = np.empty((len(values), 9), dtype=np.int8)
    for scenario in range(len(values)):
        games = values[scenario].tolist()
        totals = [[int(x) for x in row] for row in observed]
        for counts, team in zip(games, teams, strict=True):
            for stat, count in enumerate(counts):
                totals[int(team)][stat] += int(count)
        for category, stat in enumerate((0, 2, 4, 5, 6, 7, 8, 9, 10)):
            a, b = totals[0][stat], totals[1][stat]
            if category < 2:
                da, db = totals[0][stat + 1], totals[1][stat + 1]
                if zero_tie and (da == 0 or db == 0):
                    a, b = 0, 0
                else:
                    a, b = a * max(db, 1), b * max(da, 1)
            outcome = (a > b) - (a < b)
            output[scenario, category] = -outcome if category == 8 else outcome
    return output


def evaluate_scenarios(
    forecasts: tuple[GameForecast, ...],
    bank: ScenarioBank,
    selections: tuple[Selection, ...],
    rules: Rules,
    as_of: datetime,
    observed: tuple[Counts, Counts],
    *,
    backend: Literal["python", "cpp"] = "python",
) -> tuple[NDArray[np.int8], NDArray[np.float64]]:
    values, teams, totals = prepare(forecasts, bank, selections, rules, as_of, observed)
    if backend == "python":
        outcomes = reference_outcomes(
            values, teams, totals, rules.zero_attempts == "tie"
        )
    elif backend == "cpp":
        native = importlib.import_module("_matchup")
        outcomes = native.outcomes(values, teams, totals, rules.zero_attempts == "tie")
    else:
        raise ValueError("Unknown simulation backend.")
    wins = (outcomes == 1).sum(axis=1)
    ties = (outcomes == 0).sum(axis=1)
    scores = wins + (0.5 * ties if rules.category_ties == "half" else 0)
    if rules.scoring == "at_least_five":
        utility = (scores >= 5).astype(float)
    else:
        losses = (outcomes == -1).sum(axis=1)
        utility = (wins > losses).astype(float)
        utility += (wins == losses) * {"loss": 0, "half": 0.5, "win": 1}[
            rules.matchup_ties
        ]
    return outcomes, utility


def simulate(
    forecasts: tuple[GameForecast, ...],
    bank: ScenarioBank,
    selections: tuple[Selection, ...],
    rules: Rules,
    as_of: datetime,
    observed: tuple[Counts, Counts],
    *,
    backend: Literal["python", "cpp"] = "python",
) -> dict[str, object]:
    outcomes, utility = evaluate_scenarios(
        forecasts, bank, selections, rules, as_of, observed, backend=backend
    )
    wins = (outcomes == 1).sum(axis=1)
    n = len(utility)
    outright_wins = (utility == 1).astype(float)
    return {
        "fixture_only": True,
        "simulator_version": "joint-matchup-v1",
        "python_code_hash": sha256(Path(__file__).read_bytes()).hexdigest(),
        "numpy_version": np.__version__,
        "model_versions": sorted({game.model_version for game in forecasts}),
        "as_of": as_of.isoformat(),
        "missing_inputs": sorted(
            {item for game in forecasts for item in game.missing_inputs}
        ),
        "seed": bank.seed,
        "scenarios": n,
        "forecast_input_hash": bank.input_hash,
        "run_input_hash": sha256(
            repr((selections, rules, as_of, observed)).encode()
        ).hexdigest(),
        "scenario_hash": sha256(bank.values.tobytes()).hexdigest(),
        "rules_version": rules.version,
        "win_probability": float(outright_wins.mean()),
        "monte_carlo_se": sqrt(float(outright_wins.var(ddof=1)) / n) if n > 1 else None,
        "expected_matchup_credit": float(utility.mean()),
        "matchup_credit_mc_se": sqrt(float(utility.var(ddof=1)) / n) if n > 1 else None,
        "category_win_probability": dict(
            zip(CATEGORIES, (outcomes == 1).mean(axis=0).tolist(), strict=True)
        ),
        "category_tie_probability": dict(
            zip(CATEGORIES, (outcomes == 0).mean(axis=0).tolist(), strict=True)
        ),
        "expected_category_wins": float(wins.mean()),
        "warnings": [
            "Synthetic inputs; probabilities are not calibrated.",
            "Whole game vectors preserve within-game dependence; "
            "games are sampled independently.",
            "Monte Carlo SE measures sampling precision, not forecast uncertainty.",
        ],
    }
