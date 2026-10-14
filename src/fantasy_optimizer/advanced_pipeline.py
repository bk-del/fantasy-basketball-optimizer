"""Explicit advanced research candidates through the existing simulation contract."""

import importlib
import json
import resource
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from fantasy_optimizer import nba_pipeline
from fantasy_optimizer.advanced_features import (
    FEATURE_NAMES,
    RATE_NAMES,
    FeatureState,
    observations,
    prepare_dataset,
)
from fantasy_optimizer.advanced_models import joint_draws, predict_model
from fantasy_optimizer.forecasting import STATS
from fantasy_optimizer.operations import cached, code_watermark, instance_lock
from fantasy_optimizer.optimization import SearchConfig, optimize
from fantasy_optimizer.registry import Registry, atomic_write
from fantasy_optimizer.storage import canonical, digest, timestamp


def train(
    root: Path,
    registry: Registry,
    baseline_registry: Registry,
    report_path: Path,
    as_of: datetime,
) -> dict[str, Any]:
    from fantasy_optimizer.advanced_benchmark import advanced_code_hash, restore, store
    from fantasy_optimizer.advanced_models import fit_model

    start = time.perf_counter()
    report = json.loads(report_path.read_text())
    if report["state"] != "completed" or report["code_hash"] != advanced_code_hash():
        raise ValueError("Completed matching frozen advanced evaluation required.")
    if timestamp(report["protocol"]["holdout_end"]) > as_of:
        raise ValueError("Evaluation evidence is later than prediction cutoff.")
    data = prepare_dataset(root)
    strict, provenance = observations(root, "strict")
    if (
        provenance["source_hash"] != report["data"]["source_hash"]
        or not strict
        or max(r["available"] for r in strict) > as_of
    ):
        raise ValueError(
            "Validated snapshot must be strictly available at fitting cutoff."
        )
    indices = np.array(
        [
            i
            for i, c in enumerate(data["cases"])
            if timestamp(c["outcome_available"]) <= as_of
        ],
        dtype=int,
    )
    baseline_state = baseline_registry.read()
    original = baseline_state["models"].get(baseline_state["active"])
    if (
        original is None
        or original.get("scope") != "nba_research"
        or original["model"] != "recency"
    ):
        raise ValueError("Existing approved NBA recency baseline is required.")
    selected = report["selected"]
    configuration = report["protocol"]["candidates"][selected]
    key = digest(
        canonical(
            [
                report["freeze_hash"],
                data["identity"],
                as_of.isoformat(),
                indices.tolist(),
                configuration,
            ]
        )
    )
    path = Path("models/advanced") / f"production-{key}.json"
    fit_started = time.perf_counter()
    hit = path.exists()
    if hit:
        learner = json.loads(path.read_text())
    else:
        learner = fit_model(
            data,
            indices,
            configuration,
            seed=report["protocol"]["seed"],
            threads=report["protocol"]["threads"],
        )
        store(path, learner)
    fitting = time.perf_counter() - fit_started
    evidence = report["holdout"]
    scales = report["scales"]

    def loss(label: str) -> float:
        return float(
            np.mean(
                [
                    evidence[label]["per_category"][s]["mae"] / scales[i]
                    for i, s in enumerate(STATS)
                ]
            )
        )

    common = {
        "scope": "nba_research",
        "selection_metric": "normalized_all_count_mae",
        "code_hash": advanced_code_hash(),
        "dataset_watermark": provenance["source_hash"],
        "evaluation_hash": report["freeze_hash"],
        "training_cutoff": as_of.isoformat(),
        "selection_cutoff": report["protocol"]["calibration_end"],
        "benchmark": str(report_path),
        "baseline_scores": {
            k: loss(k) for k in ["recency_raw", "season_to_date", "shrinkage"]
        },
        "automatic_retraining": False,
        "scope_label": "advanced NBA conditional research; no Yahoo",
        "production_refit_warning": (
            "All-history weights fitted after configuration validation; new refit "
            "has no separate future evaluation."
        ),
    }
    with instance_lock(registry.path):
        baseline = registry.register(
            {
                **common,
                "kind": "incumbent",
                "model": "recency",
                "validation_score": loss("recency_raw"),
                "nba_baseline_model_id": baseline_state["active"],
            },
            max_candidates=16,
        )
        candidate = registry.register(
            {
                **common,
                "kind": "candidate",
                "model": configuration["kind"],
                "learner_label": selected,
                "config": configuration,
                "validation_score": loss(selected),
                "learner_artifact": store(path, learner),
                "calibration_artifact": report["calibration"][selected]["artifact"],
                "training_cases": len(indices),
                "training_players": len(
                    {data["cases"][i]["player_key"] for i in indices}
                ),
                "training_observations_available": len(strict),
                "promotion_gate": report["promotion_gate"],
            },
            max_candidates=16,
        )
        promoted = False
        reason = "Frozen holdout gate failed; original recency retained."
        if (
            report["promotion_gate"]["passed"]
            and registry.read()["active"] != candidate
        ):
            from fantasy_optimizer.registry import RegistryError

            try:
                registry.promote(candidate)
                promoted = True
                reason = (
                    "Frozen multi-category gate and existing all-count registry "
                    "validation passed."
                )
            except RegistryError as error:
                reason = f"Existing all-count lifecycle retained recency: {error}"
        elif registry.read()["active"] == candidate:
            reason = "Previously approved selected configuration retained."
    restore(report["calibration"][selected]["artifact"])
    return {
        "baseline_id": baseline,
        "candidate_id": candidate,
        "active_id": registry.read()["active"],
        "selected": selected,
        "promoted": promoted,
        "reason": reason,
        "available_observations": len(strict),
        "fitted_cases": len(indices),
        "fitted_players": len({data["cases"][i]["player_key"] for i in indices}),
        "cache_hit": hit,
        "model_fitting_seconds": fitting,
        "total_seconds": time.perf_counter() - start,
        "learner_bytes": path.stat().st_size,
        "registry_bytes": registry.path.stat().st_size,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }


def forecast(
    root: Path,
    registry: Registry,
    baseline_registry: Registry,
    output: Path,
    as_of: datetime,
    *,
    seed: int = 42,
    samples: int = 256,
    candidate: bool = False,
) -> dict[str, Any]:
    from fantasy_optimizer.advanced_benchmark import advanced_code_hash, restore

    start = time.perf_counter()
    state = registry.read()
    chosen = state["active"]
    if candidate:
        matches = [
            (k, v)
            for k, v in state["models"].items()
            if v.get("learner_label") and v["state"] != "archived"
        ]
        if len(matches) != 1:
            raise ValueError("Exactly one current advanced candidate required.")
        chosen = matches[0][0]
    active = state["models"].get(chosen)
    if (
        not active
        or active["code_hash"] != advanced_code_hash()
        or max(timestamp(active[k]) for k in ["training_cutoff", "selection_cutoff"])
        > as_of
    ):
        raise ValueError(
            "Advanced registry code/time mismatch; fit validated configuration first."
        )
    if not 32 <= samples <= 10000 or seed < 0:
        raise ValueError("Invalid sample count or seed.")
    if active["model"] == "recency":
        if baseline_registry.read()["active"] != active["nba_baseline_model_id"]:
            raise ValueError("Original approved recency identity changed.")
        inferred = nba_pipeline.forecasts(
            root,
            baseline_registry,
            Path("data/nba-runs"),
            as_of,
            seed=seed,
            samples=samples,
        )
        return {**inferred, "active_selection_id": chosen, "using_candidate": False}
    records, data = observations(root, "strict")
    if data["source_hash"] != active["dataset_watermark"]:
        raise ValueError(
            "Advanced model dataset changed; explicit validated refit required."
        )
    key = digest(
        canonical(
            [data, chosen, as_of.isoformat(), seed, samples, advanced_code_hash()]
        )
    )

    def infer() -> dict[str, Any]:
        feature_state = FeatureState(records)
        feature_state.advance(as_of)
        snapshots: dict[str, dict[str, Any]] = {}
        for player in sorted(feature_state.history):
            snapshot = feature_state.snapshot(player, as_of)
            if snapshot is None:
                raise ValueError("Known player has no origin-known feature history.")
            snapshots[player] = snapshot
        players = sorted(snapshots)
        prepared = {
            k: np.array([snapshots[p][k] for p in players])
            for k in ["x", "base", "recency_primitive", "shot_population"]
        }
        predictions = predict_model(
            restore(active["learner_artifact"]), prepared, np.arange(len(players))
        )
        calibrator = restore(active["calibration_artifact"])
        rows = []
        for i, p in enumerate(players):
            snapshot = snapshots[p]
            case = {
                "player_key": p,
                "as_of": as_of.isoformat(),
                "minutes_group": snapshot["minutes_group"],
                "history": snapshot["history"],
            }
            draws = joint_draws(
                predictions["primitive"][i],
                case,
                calibrator,
                seed=seed,
                samples=samples,
                stream=as_of.isoformat(),
            )
            components = predictions["components"][i]
            minute_mean = float(np.clip(components[1], 0, 80))
            residuals = calibrator.get("minute_residuals", {})
            minute_interval = None
            if residuals:
                cell = residuals.get(case["minutes_group"], residuals["pooled"])
                minute_interval = np.clip(
                    minute_mean + np.quantile(cell, [0.1, 0.9]), 0, 80
                ).tolist()
            rows.append(
                {
                    "player_key": p,
                    "nba_player_id": int(p.split(":")[1]),
                    "prediction_timestamp": as_of.isoformat(),
                    "data_cutoff": as_of.isoformat(),
                    "latest_observation": snapshot["latest"],
                    "model_id": chosen,
                    "model_version": "nba-advanced-v1",
                    "model": active["learner_label"],
                    "dataset_version": data["source_hash"],
                    "code_hash": advanced_code_hash(),
                    "input_hash": snapshot["input_hash"],
                    "seed": seed,
                    "horizon": "next_recorded_player_game_conditional",
                    "expected_counts": dict(
                        zip(STATS, predictions["counts"][i].tolist(), strict=True)
                    ),
                    "joint_samples": [
                        dict(zip(STATS, d.astype(int).tolist(), strict=True))
                        for d in draws
                    ],
                    "intervals_80": dict(
                        zip(
                            STATS,
                            np.quantile(draws, [0.1, 0.9], axis=0).T.tolist(),
                            strict=True,
                        )
                    ),
                    "sample_mean": dict(
                        zip(STATS, draws.mean(axis=0).tolist(), strict=True)
                    ),
                    "sample_sd": dict(
                        zip(STATS, draws.std(axis=0, ddof=1).tolist(), strict=True)
                    ),
                    "history_observations": snapshot["history"],
                    "minutes_group": case["minutes_group"],
                    "minutes_given_nonzero_record": {
                        "mean": minute_mean,
                        "interval_80": minute_interval,
                    },
                    "per_minute_production": dict(
                        zip(
                            RATE_NAMES,
                            np.maximum(components[2:10], 0).tolist(),
                            strict=True,
                        )
                    ),
                    "shooting_probabilities": dict(
                        zip(
                            ["2P", "3P", "FT"],
                            np.clip(components[10:13], 0, 1).tolist(),
                            strict=True,
                        )
                    ),
                    "nonzero_record_probability": float(np.clip(components[0], 0, 1)),
                    "assumptions": {
                        "availability_probability": None,
                        "expected_minutes_unconditional": None,
                        "game_count": None,
                        "context": (
                            "last observed team history, not confirmed upcoming matchup"
                        ),
                    },
                    "warnings": [
                        (
                            "Conditional statistical estimates, not verified "
                            "playing-time/availability assumptions."
                        ),
                        (
                            "Snapshot newest games April 2026; current roster and "
                            "role unknown."
                        ),
                        (
                            "Joint count calibration has no guaranteed "
                            "player-specific coverage or live matchup calibration."
                        ),
                    ],
                }
            )
        return {
            "mode": "NBA advanced conditional research forecasts",
            "as_of": as_of.isoformat(),
            "model_id": chosen,
            "data": data,
            "input_hash": digest(canonical([r["input_hash"] for r in rows])),
            "player_count": len(rows),
            "feature_names": FEATURE_NAMES,
            "forecasts": rows,
            "seven_day_projection": {
                "available": False,
                "game_count": None,
                "reason": "Verified future schedule/participation unavailable.",
            },
        }

    with instance_lock(output / "advanced-forecast"):
        result, hit = cached(output / "cache" / "advanced-forecasts", key, infer)
        artifact = output / f"forecast-{key}.json"
        if not artifact.exists():
            atomic_write(artifact, result)
    return {
        "report": result,
        "artifact": str(artifact),
        "cache_hit": hit,
        "inference_seconds": time.perf_counter() - start,
        "active_selection_id": chosen,
        "using_candidate": candidate,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }


def run(
    root: Path,
    registry: Registry,
    baseline_registry: Registry,
    output: Path,
    as_of: datetime,
    *,
    config: SearchConfig,
    samples: int = 256,
    candidate: bool = False,
) -> dict[str, Any]:
    from fantasy_optimizer.advanced_benchmark import advanced_code_hash

    start = time.perf_counter()
    inferred = forecast(
        root,
        registry,
        baseline_registry,
        output,
        as_of,
        seed=config.seed,
        samples=samples,
        candidate=candidate,
    )
    native = importlib.import_module("_matchup")
    if native.__file__ is None:
        raise ValueError("Native binary path unavailable.")
    binary = digest(Path(native.__file__).read_bytes().hex())
    distribution = inferred["report"]
    key = digest(
        canonical(
            [
                distribution["input_hash"],
                distribution["model_id"],
                as_of.isoformat(),
                asdict(config),
                code_watermark(),
                advanced_code_hash(),
                binary,
                seed_identity(distribution),
            ]
        )
    )

    def decide() -> dict[str, Any]:
        predictions = {p["player_key"]: p for p in distribution["forecasts"]}
        decision = optimize(
            *nba_pipeline.league_inputs(predictions, as_of), config=config
        )
        return {
            "mode": (
                "fixture league simulation with actual NBA advanced-research "
                "distributions"
            ),
            "live_yahoo_recommendation": False,
            "using_candidate": inferred["using_candidate"],
            "model_id": distribution["model_id"],
            "active_selection_id": inferred["active_selection_id"],
            "forecast_artifact": inferred["artifact"],
            "as_of": as_of.isoformat(),
            "data": distribution["data"],
            "fixture_identity_bindings": nba_pipeline.FIXTURE_IDS,
            "optimization": decision,
            "scope": (
                "Hypothetical schedule/ownership/eligibility/value proxies; no "
                "verified real seven-day games."
            ),
            "limitations": [
                "Candidate evaluation is explicit and does not promote a model.",
                (
                    "Joint distributions are real-data-derived; simulated win odds "
                    "are not calibrated live odds."
                ),
            ],
        }

    timer = time.perf_counter()
    with instance_lock(output / "advanced-run"):
        result, hit = cached(output / "cache" / "advanced-decisions", key, decide)
        artifact = output / f"run-{key}.json"
        if not artifact.exists():
            atomic_write(artifact, result)
    return {
        "report": result,
        "artifact": str(artifact),
        "forecast_cache_hit": inferred["cache_hit"],
        "decision_cache_hit": hit,
        "inference_seconds": inferred["inference_seconds"],
        "optimization_seconds": time.perf_counter() - timer,
        "total_seconds": time.perf_counter() - start,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }


def seed_identity(distribution: dict[str, Any]) -> str:
    return digest(
        canonical(
            [[p["player_key"], p["joint_samples"]] for p in distribution["forecasts"]]
        )
    )
