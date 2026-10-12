"""Small handmade waiver situations; no live ownership or transactions."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from fantasy_optimizer.optimization import (
    PlayerSnapshot,
    SearchConfig,
    TransactionRules,
    optimize,
)
from fantasy_optimizer.simulation import Counts, GameForecast, Rules, Selection

SCENARIOS = (
    "baseline",
    "none_available",
    "acquisition_cap",
    "bad_moves",
    "impossible_comeback",
    "unknown_settings",
)


def fixture_inputs(
    scenario: str = "baseline",
) -> tuple[
    tuple[PlayerSnapshot, ...],
    TransactionRules,
    Rules,
    tuple[GameForecast, ...],
    tuple[Selection, ...],
    tuple[Counts, Counts],
    datetime,
]:
    if scenario not in SCENARIOS:
        raise ValueError("Unknown optimization fixture scenario.")
    origin = datetime(2026, 1, 5, tzinfo=UTC)
    definitions = (
        ("anchor", "ours", True, 10.0, ("G",), (4, 8, 2, 3, 1, 11, 4, 4, 2, 1, 1)),
        ("streamer", "ours", False, 1.0, ("F",), (2, 5, 1, 2, 0, 5, 2, 1, 0, 0, 2)),
        (
            "opponent-g",
            "opponent",
            False,
            5.0,
            ("G",),
            (5, 11, 4, 5, 2, 16, 5, 5, 2, 1, 3),
        ),
        (
            "opponent-f",
            "opponent",
            False,
            5.0,
            ("F",),
            (4, 8, 3, 4, 1, 12, 5, 3, 1, 1, 2),
        ),
        ("target", "free", False, 2.0, ("F",), (6, 10, 4, 5, 2, 18, 8, 4, 1, 3, 1)),
        ("bad-target", "free", False, 0.5, ("F",), (1, 7, 0, 2, 0, 2, 1, 0, 0, 0, 5)),
        (
            "waiver-target",
            "free",
            False,
            4.0,
            ("F",),
            (6, 10, 4, 5, 2, 18, 8, 4, 1, 3, 1),
        ),
        (
            "wrong-position",
            "free",
            False,
            3.0,
            ("C",),
            (6, 10, 4, 5, 2, 18, 8, 4, 1, 3, 1),
        ),
    )
    players = tuple(
        PlayerSnapshot(
            key,
            cast(Literal["ours", "opponent", "free"], owner),
            owner == "free",
            "waiver" if key == "waiver-target" else "free_agent",
            True,
            slots,
            False,
            protected,
            value,
            origin,
            origin,
            "handmade-ownership-v1",
        )
        for key, owner, protected, value, slots, _ in definitions
    )
    games = tuple(
        GameForecast(
            f"{key}-{day}",
            key,
            origin + timedelta(days=day, hours=18),
            origin + timedelta(days=day, hours=21),
            slots,
            (counts, (0,) * 11) if key == "target" else (counts,),
            "handmade-waiver-games-v1",
        )
        for key, _, _, _, slots, counts in definitions
        for day in (1, 2, 3)
    )
    rules = Rules(
        "handmade-matchup-rules-v1",
        (("anchor", "streamer"), ("opponent-g", "opponent-f")),
        ("G", "F"),
        (6, 6),
        "UTC",
        origin,
        origin + timedelta(days=7),
    )
    transactions = TransactionRules(
        "handmade-transaction-rules-v1",
        "fixture",
        origin,
        origin,
        2,
        2,
        10,
        1,
        "free_agents_only",
        False,
        origin,
        "daily",
    )
    opponent = tuple(
        Selection(g.game_key, 1, g.eligible_slots[0])
        for g in games
        if g.player_key.startswith("opponent-")
    )
    observed: tuple[Counts, Counts] = ((0,) * 11, (0,) * 11)
    if scenario == "none_available":
        players = tuple(
            replace(p, addable=False) if p.owner == "free" else p for p in players
        )
    elif scenario == "acquisition_cap":
        transactions = replace(transactions, acquisitions_remaining=0)
    elif scenario == "bad_moves":
        players = tuple(
            replace(p, addable=p.key == "bad-target") if p.owner == "free" else p
            for p in players
        )
    elif scenario == "unknown_settings":
        transactions = replace(transactions, acquisitions_remaining=None)
    elif scenario == "impossible_comeback":
        observed = (
            (0,) * 11,
            (1000, 2000, 1000, 2000, 500, 3500, 1000, 1000, 1000, 1000, 0),
        )
    return players, transactions, rules, games, opponent, observed, origin


def optimize_fixture(
    *,
    seed: int,
    screening_samples: int,
    finalist_samples: int,
    scenario: str = "baseline",
    backend: Literal["python", "cpp"] = "cpp",
) -> dict[str, object]:
    return optimize(
        *fixture_inputs(scenario),
        config=SearchConfig(
            seed=seed,
            screening_samples=screening_samples,
            finalist_samples=finalist_samples,
            backend=backend,
        ),
    )
