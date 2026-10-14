"""Full-population CPU refit/inference and native-kernel diagnostics; no selection."""

import importlib
import json
import resource
import time
from functools import partial
from pathlib import Path

import numpy as np

from fantasy_optimizer.advanced_benchmark import (
    add_minute_calibration,
    minute_metrics,
    restore,
    store,
    subset,
)
from fantasy_optimizer.advanced_features import (
    FeatureState,
    observations,
    prepare_dataset,
)
from fantasy_optimizer.advanced_models import fit_model, joint_draws, predict_model
from fantasy_optimizer.forecasting import STATS
from fantasy_optimizer.nba_pipeline import FIXTURE_IDS, league_inputs
from fantasy_optimizer.registry import Registry, atomic_write
from fantasy_optimizer.simulation import (
    Selection,
    prepare,
    reference_outcomes,
    sample_scenarios,
)
from fantasy_optimizer.storage import digest, timestamp

started = time.perf_counter()
origin = timestamp("2026-10-13T03:40:00Z")
report = json.loads(Path("docs/benchmarks/nba-advanced.json").read_text())
if report["state"] != "completed":
    raise ValueError("Complete frozen advanced evaluation required.")
timer = time.perf_counter()
data = prepare_dataset(Path("data/nba_data"))
load_seconds = time.perf_counter() - timer
indices = subset(
    data,
    report["protocol"]["holdout_start"],
    report["protocol"]["holdout_end"],
    labels_by_end=False,
)
calibration = subset(
    data, report["protocol"]["fit_end"], report["protocol"]["calibration_end"]
)
baseline_prediction = {
    "components": data["base"][indices],
    "counts": data["recency"][indices],
}
calibrator = restore(report["calibration"]["recency"]["artifact"])
add_minute_calibration(
    calibrator, {"components": data["base"][calibration]}, data, calibration
)
component_diagnostics = {
    "recency_components": minute_metrics(baseline_prediction, data, indices, calibrator)
}
for label in report["final_labels"]:
    prediction = predict_model(restore(report["models"][label]), data, indices)
    calibrator = restore(report["calibration"][label]["artifact"])
    component_diagnostics[label] = minute_metrics(prediction, data, indices, calibrator)

# Refit the predeclared neural challenger on all eligible history for timing/current
# inference only. Never score these new weights on the historical held-out period.
timer = time.perf_counter()
neural = fit_model(
    data,
    np.arange(len(data["cases"])),
    report["protocol"]["candidates"]["mlp_small"],
    seed=42,
    threads=2,
)
neural_fit_seconds = time.perf_counter() - timer
neural_reference = store(
    Path("models/advanced") / f"full-population-mlp-{report['freeze_hash']}.json",
    neural,
)
records, provenance = observations(Path("data/nba_data"), "strict")
if max(r["available"] for r in records) > origin:
    raise ValueError("Source not strictly available at current inference cutoff.")
timer = time.perf_counter()
state = FeatureState(records)
state.advance(origin)
players = sorted(state.history)
snapshots = {p: state.snapshot(p, origin) for p in players}
current = {
    k: np.array([snapshots[p][k] for p in players])
    for k in ["x", "base", "shot_population", "recency_primitive"]
}
current_feature_seconds = time.perf_counter() - timer
timer = time.perf_counter()
neural_current = predict_model(neural, current, np.arange(len(players)))
neural_inference_seconds = time.perf_counter() - timer
assert np.isfinite(neural_current["counts"]).all()

# Use the actual all-history selected candidate, not the neural refit, for kernels.
registry = Registry(Path("models/advanced-registry.json"))
candidates = [
    v
    for v in registry.read()["models"].values()
    if v.get("learner_label") == report["selected"]
]
if len(candidates) != 1:
    raise ValueError("Run fantasy advanced train first.")
selected = candidates[0]
timer = time.perf_counter()
chosen_current = predict_model(
    restore(selected["learner_artifact"]), current, np.arange(len(players))
)
selected_inference_seconds = time.perf_counter() - timer

calibrator = restore(selected["calibration_artifact"])
predictions = {}

for identifier in FIXTURE_IDS.values():
    player = f"nba:{identifier}"
    i = players.index(player)
    case = {
        "player_key": player,
        "history": snapshots[player]["history"],
        "minutes_group": snapshots[player]["minutes_group"],
    }
    draws = joint_draws(
        chosen_current["primitive"][i],
        case,
        calibrator,
        seed=42,
        samples=256,
        stream=origin.isoformat(),
    )
    predictions[player] = {
        "model_id": report["selected"],
        "joint_samples": [
            dict(zip(STATS, d.astype(int).tolist(), strict=True)) for d in draws
        ],
    }
inputs = league_inputs(predictions, origin)
rules, forecasts, observed = inputs[2], inputs[3], inputs[5]
selected_games = tuple(
    Selection(
        g.game_key, 0 if g.player_key in rules.rosters[0] else 1, g.eligible_slots[0]
    )
    for g in forecasts
    if g.player_key in rules.rosters[0] + rules.rosters[1]
)
native = importlib.import_module("_matchup")
simulation = {}
for scenarios in (1000, 10000, 20000):
    timer = time.perf_counter()
    bank = sample_scenarios(forecasts, seed=42, scenarios=scenarios)
    values, teams, totals = prepare(
        forecasts, bank, selected_games, rules, origin, observed
    )
    preparation_seconds = time.perf_counter() - timer
    kernels = {}
    for name, call in [
        ("cpp", partial(native.outcomes, values, teams, totals, False)),
        ("python", partial(reference_outcomes, values, teams, totals, False)),
    ]:
        call()
        times = []
        for _ in range(3):
            timer = time.perf_counter()
            call()
            times.append(time.perf_counter() - timer)
        kernels[name] = float(np.median(times))
    assert np.array_equal(
        native.outcomes(values, teams, totals, False),
        reference_outcomes(values, teams, totals, False),
    )
    moments = True
    if scenarios == 20000:
        for j, game in enumerate(sorted(forecasts, key=lambda g: g.game_key)):
            support = np.asarray(game.joint_samples)
            se = support.std(axis=0) / np.sqrt(scenarios)
            moments &= bool(
                (
                    abs(bank.values[:, j].mean(axis=0) - support.mean(axis=0))
                    <= 5 * se + 1e-10
                ).all()
            )
        assert moments
    simulation[str(scenarios)] = {
        "preparation_seconds": preparation_seconds,
        "kernel_median_seconds": kernels,
        "exact_category_parity": True,
        "input_moments_within_five_mc_se": moments if scenarios == 20000 else None,
        "raw_bank_bytes": bank.values.nbytes,
        "scenario_hash": digest(bank.values.tobytes().hex()),
    }
result = {
    "scope": (
        "CPU-only local diagnostic; actual NBA learners/distributions, "
        "hypothetical fixture schedule; no model selection or promotion"
    ),
    "as_of": origin.isoformat(),
    "freeze_hash": report["freeze_hash"],
    "source_hash": provenance["source_hash"],
    "all_observations": len(records),
    "eligible_training_cases": len(data["cases"]),
    "eligible_training_players": len({c["player_key"] for c in data["cases"]}),
    "current_supported_players": len(players),
    "cached_data_preparation_seconds": load_seconds,
    "current_all_player_features_seconds": current_feature_seconds,
    "neural_full_population_fit_seconds": neural_fit_seconds,
    "neural_all_player_inference_seconds": neural_inference_seconds,
    "neural_fitted_model": neural_reference,
    "neural_parameters": sum(np.asarray(w).size for w in neural["weights"].values()),
    "selected_all_player_inference_seconds": selected_inference_seconds,
    "component_diagnostics": component_diagnostics,
    "simulation": simulation,
    "total_seconds": time.perf_counter() - started,
    "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    "limits": [
        (
            "Component baseline diagnostics are descriptive post-evaluation "
            "analysis, not model selection."
        ),
        (
            "Full-history neural refit is not evaluated on prior held-out "
            "outcomes or promoted."
        ),
        (
            "Pure model inference excludes data loading, feature preparation, "
            "sampling and JSON persistence."
        ),
        "Specific owner laptop/GPU not benchmarked.",
    ],
}
atomic_write(Path("docs/benchmarks/nba-advanced-performance.json"), result)
print(json.dumps(result, indent=2))
