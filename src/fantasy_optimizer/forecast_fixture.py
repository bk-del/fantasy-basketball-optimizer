"""Synthetic benchmark, artifacts and the offline forecast entry point."""

import json
import math
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from statistics import mean
from typing import Any

from fantasy_optimizer.forecasting import (
    CONFIG,
    MODEL_VERSION,
    MODELS,
    STATS,
    Window,
    count,
    forecast,
    known_windows,
)
from fantasy_optimizer.storage import canonical, digest, timestamp


def fixture_history() -> tuple[list[Window], datetime]:
    content = json.loads(
        files("fantasy_optimizer").joinpath("fixtures", "forecast.json").read_text()
    )
    rows = [
        Window(
            row["player_key"],
            timestamp(row["start"]),
            timestamp(row["end"]),
            timestamp(row["observed_at"]),
            timestamp(row["ingested_at"]),
            tuple(row["counts"].get(stat) for stat in STATS),
        )
        for row in content["windows"]
    ]
    return rows, timestamp(content["as_of"])


def benchmark(
    windows: list[Window], *, seed: int = 42, samples: int = 256
) -> dict[str, Any]:
    """Rolling one-window-ahead evaluation; priors are refit at each origin."""
    results: dict[str, Any] = {}
    targets = known_windows(windows, max(row.ingested_at for row in windows))
    for model in MODELS:
        errors: dict[str, list[float]] = {stat: [] for stat in STATS}
        coverage: dict[str, list[int]] = {stat: [] for stat in STATS}
        brier: dict[str, list[float]] = {stat: [] for stat in STATS}
        probability_mc_se: dict[str, list[float]] = {stat: [] for stat in STATS}
        cases = 0
        for target in targets:
            origin = target.start
            available = known_windows(windows, origin)
            history = [row for row in available if row.player_key == target.player_key]
            if len(history) < 2 or history[-1].end != origin:
                continue
            prediction = forecast(
                available,
                target.player_key,
                origin,
                model=model,
                seed=seed,
                samples=samples,
            )
            cases += 1
            for index, stat in enumerate(STATS):
                actual = target.counts[index]
                expected = prediction.expected_counts[stat]
                interval = prediction.intervals_80[stat]
                if actual is None or expected is None or interval is None:
                    continue
                errors[stat].append(abs(expected - actual))
                coverage[stat].append(int(interval[0] <= actual <= interval[1]))
                # Threshold fixed from each origin's mean, never its held-out value.
                threshold = math.floor(expected)
                probability = (
                    sum(
                        count(draw[stat]) > threshold
                        for draw in prediction.joint_samples
                    )
                    / samples
                )
                brier[stat].append((probability - int(actual > threshold)) ** 2)
                probability_mc_se[stat].append(
                    math.sqrt(probability * (1 - probability) / samples)
                )
        results[model] = {
            "forecast_cases": cases,
            "per_stat": {
                stat: {
                    "n": len(errors[stat]),
                    "mae": mean(errors[stat]) if errors[stat] else None,
                    "coverage_80": mean(coverage[stat]) if coverage[stat] else None,
                    "coverage_binomial_se": math.sqrt(
                        mean(coverage[stat])
                        * (1 - mean(coverage[stat]))
                        / len(coverage[stat])
                    )
                    if coverage[stat]
                    else None,
                    "mean_probability_mc_se": mean(probability_mc_se[stat])
                    if probability_mc_se[stat]
                    else None,
                    "threshold_brier": mean(brier[stat]) if brier[stat] else None,
                }
                for stat in STATS
            },
        }
    return {
        "evaluation": "time-ordered rolling origins; completed weekly targets",
        "synthetic": True,
        "models": results,
        "limitations": [
            "Toy windows are not evidence of real-world calibration.",
            "Coverage SE assumes independent cases; shared players violate this.",
            "Threshold Brier is a diagnostic, not a fitted calibration curve.",
        ],
    }


def forecast_fixture(
    *,
    seed: int = 42,
    samples: int = 256,
    model: str = "recency",
    output: Path | None = None,
    evaluate: bool = False,
) -> dict[str, Any]:
    windows, as_of = fixture_history()
    forecasts = [
        forecast(windows, key, as_of, seed=seed, samples=samples, model=model).payload()
        for key in sorted({row.player_key for row in windows})
    ]
    code = files("fantasy_optimizer").joinpath("forecasting.py").read_text()
    report: dict[str, Any] = {
        "mode": "fixture",
        "synthetic": True,
        "contract_version": 1,
        "active_baseline": model,
        "model_version": MODEL_VERSION,
        "as_of": as_of.isoformat(),
        "config": CONFIG,
        "code_hash": digest(code),
        "seed": seed,
        "samples": samples,
        "forecasts": forecasts,
        "promotion": "provisional fixture baseline; no live quality claim",
    }
    if evaluate:
        report["benchmark"] = benchmark(windows, seed=seed, samples=samples)
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        artifact_id = digest(canonical(report))
        destination = output / f"{artifact_id}.json"
        # Deterministic content-addressed artifact carries features and joint samples.
        destination.write_text(
            json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )
        report["artifact"] = str(destination)
    return report
