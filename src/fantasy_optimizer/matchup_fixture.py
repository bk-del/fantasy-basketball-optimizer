"""Handmade game forecasts; never derived from weekly/season aggregates."""

from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Literal

from fantasy_optimizer.simulation import (
    GameForecast,
    Rules,
    Selection,
    prepare,
    reference_outcomes,
    sample_scenarios,
    simulate,
)


def fixture() -> tuple[
    tuple[GameForecast, ...], tuple[Selection, ...], Rules, datetime
]:
    origin = datetime(2026, 1, 5, tzinfo=UTC)
    samples = (
        (4, 10, 2, 3, 1, 11, 5, 3, 1, 0, 2),
        (8, 15, 4, 5, 3, 23, 8, 5, 2, 1, 3),
        (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    )
    games = tuple(
        GameForecast(
            f"game-{team}-{day}-{slot}",
            f"player-{team}-{slot}",
            origin + timedelta(days=day, hours=18),
            origin + timedelta(days=day, hours=21),
            (f"slot-{slot}",),
            samples if team == 0 else samples[::-1],
            "handmade-games-v1",
        )
        for team in range(2)
        for day in range(1, 5)
        for slot in range(5)
    )
    selections = tuple(
        Selection(g.game_key, int(g.player_key.split("-")[1]), g.eligible_slots[0])
        for g in games
    )
    rules = Rules(
        "synthetic-rules-v1",
        (
            tuple(f"player-0-{i}" for i in range(5)),
            tuple(f"player-1-{i}" for i in range(5)),
        ),
        tuple(f"slot-{i}" for i in range(5)),
        (20, 20),
        "UTC",
        origin,
        origin + timedelta(days=7),
    )
    return games, selections, rules, origin


def matchup_fixture(
    *, seed: int, scenarios: int, backend: Literal["python", "cpp"], benchmark: bool
) -> dict[str, object]:
    games, selections, rules, origin = fixture()
    observed = ((0,) * 11, (0,) * 11)
    bank = sample_scenarios(games, seed=seed, scenarios=scenarios)
    result = simulate(games, bank, selections, rules, origin, observed, backend=backend)
    if benchmark:
        import importlib
        from statistics import median

        native = importlib.import_module("_matchup")
        rows = []
        for size in (1000, 10000, 20000):
            started = perf_counter()
            batch = sample_scenarios(games, seed=seed, scenarios=size)
            arrays = prepare(games, batch, selections, rules, origin, observed)
            preparation = perf_counter() - started
            timings: dict[str, float] = {}
            for name, function in (
                ("python", reference_outcomes),
                ("cpp", native.outcomes),
            ):
                function(*arrays, False)  # Warm-up excluded.
                durations = []
                for _ in range(3):
                    started = perf_counter()
                    function(*arrays, False)
                    durations.append(perf_counter() - started)
                timings[name] = median(durations)
            rows.append(
                {
                    "scenarios": size,
                    "preparation_seconds": preparation,
                    "median_kernel_seconds": timings,
                    "repetitions": 3,
                }
            )
        result["benchmark"] = rows
    return result
