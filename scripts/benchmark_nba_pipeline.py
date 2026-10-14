"""Reproduce CPU timings using selected 14-day real NBA per-game distributions."""

import importlib
import json
import resource
import time
from functools import partial
from pathlib import Path

import numpy as np

from fantasy_optimizer.forecasting import ForecastConfig
from fantasy_optimizer.nba_forecasting import Population, game_records, load_games
from fantasy_optimizer.nba_pipeline import FIXTURE_IDS, league_inputs
from fantasy_optimizer.registry import atomic_write
from fantasy_optimizer.simulation import (
    Selection,
    prepare,
    reference_outcomes,
    sample_scenarios,
)
from fantasy_optimizer.storage import digest, timestamp

origin = timestamp("2026-10-13T03:40:00Z")
t = time.perf_counter()
games, data = load_games(Path("data/nba_data"))
load_seconds = time.perf_counter() - t
t = time.perf_counter()
population = Population(
    game_records(games, "strict"), origin, ForecastConfig(half_life_days=14)
)
fit = time.perf_counter() - t
t = time.perf_counter()
p = {
    f"nba:{i}": population.predict(f"nba:{i}", "recency", seed=42, samples=256)
    for i in FIXTURE_IDS.values()
}
inference8 = time.perf_counter() - t
for row in p.values():
    row["model_id"] = "per-game-recency-14-development-selected"
inputs = league_inputs(p, origin)
rules, forecasts, observed = inputs[2], inputs[3], inputs[5]

selected = tuple(
    Selection(
        g.game_key, 0 if g.player_key in rules.rosters[0] else 1, g.eligible_slots[0]
    )
    for g in forecasts
    if g.player_key in rules.rosters[0] + rules.rosters[1]
)
simulations = {}
native = importlib.import_module("_matchup")
for count in (1000, 10000, 20000):
    t = time.perf_counter()
    bank = sample_scenarios(forecasts, seed=42, scenarios=count)
    values, teams, totals = prepare(forecasts, bank, selected, rules, origin, observed)
    preparation = time.perf_counter() - t
    kernel = {}
    for name, call in [
        ("python", partial(reference_outcomes, values, teams, totals, False)),
        ("cpp", partial(native.outcomes, values, teams, totals, False)),
    ]:
        call()
        times = []
        for _ in range(3):
            t = time.perf_counter()
            outcomes = call()
            times.append(time.perf_counter() - t)
        kernel[name] = float(np.median(times))
    py = reference_outcomes(values, teams, totals, False)
    cpp = native.outcomes(values, teams, totals, False)
    assert np.array_equal(py, cpp)
    simulations[str(count)] = {
        "preparation_seconds": preparation,
        "kernel_median_seconds": kernel,
        "raw_bank_bytes": bank.values.nbytes,
        "exact_category_parity": True,
        "scenario_hash": digest(bank.values.tobytes().hex()),
    }
result = {
    "scope": (
        "Real NBA distributions, hypothetical fixture schedule/constraints; "
        "measured local CPU; imports excluded"
    ),
    "as_of": origin.isoformat(),
    "source_hash": data["source_hash"],
    "all_games": len(games),
    "all_players": len(population.players),
    "load_seconds": load_seconds,
    "fit_summary_seconds": fit,
    "inference_eight_players_seconds": inference8,
    "simulation": simulations,
    "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
}
atomic_write(Path("docs/benchmarks/nba-performance.json"), result)
print(json.dumps(result, indent=2))
