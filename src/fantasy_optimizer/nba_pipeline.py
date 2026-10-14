"""Local NBA predictions and explicitly hypothetical fixture recommendations."""

import json
import resource
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from fantasy_optimizer.forecasting import STATS, ForecastConfig
from fantasy_optimizer.nba_forecasting import (
    VERSION,
    Population,
    code_hash,
    game_records,
    load_games,
)
from fantasy_optimizer.operations import cached, code_watermark, instance_lock
from fantasy_optimizer.optimization import (
    PlayerSnapshot,
    SearchConfig,
    TransactionRules,
    optimize,
)
from fantasy_optimizer.optimization_fixture import fixture_inputs
from fantasy_optimizer.registry import Registry, atomic_write
from fantasy_optimizer.simulation import Counts, GameForecast, Rules, Selection
from fantasy_optimizer.storage import canonical, digest, timestamp

# These are fixture aliases bound to exact IDs observed in the cached player logs,
# not Yahoo mappings or real ownership/eligibility/long-term value assertions.
FIXTURE_IDS = {
    "anchor": 2544,
    "streamer": 201145,
    "opponent-g": 101108,
    "opponent-f": 201142,
    "target": 201143,
    "bad-target": 200768,
    "waiver-target": 201144,
    "wrong-position": 201572,
}


def train(
    root: Path, registry: Registry, benchmark: Path, as_of: datetime
) -> dict[str, Any]:
    started = time.perf_counter()
    evidence = json.loads(benchmark.read_text())
    if evidence["code_hash"] != code_hash() or not evidence.get("holdout_id"):
        raise ValueError(
            "A completed frozen population benchmark matching current code is required."
        )
    if as_of < timestamp(evidence["protocol"]["replication_end"]):
        raise ValueError("Model selection/evaluation evidence is later than cutoff.")
    games, data = load_games(root)
    if data["source_hash"] != evidence["data"]["source_hash"]:
        raise ValueError(
            "Dataset differs from validated benchmark; rerun a "
            "new chronological protocol."
        )
    result = evidence["results"]["per_game"]
    selected = result["selected"]
    configuration = result["configurations"][selected]
    config = ForecastConfig(half_life_days=configuration["half_life_days"])
    population = Population(game_records(games, "strict"), as_of, config)
    if not population.players:
        raise ValueError("No strictly available NBA observations at cutoff.")

    def loss(label: str) -> float:
        values = result["calibration"][label]["metrics"]["per_stat"]
        return float(
            sum(values[s]["mae"] / result["scales"][i] for i, s in enumerate(STATS))
            / len(STATS)
        )

    # Register the development-selected research configuration. Evidence from all
    # eleven counts is retained; normal inference never changes active selection.
    record = {
        "kind": "incumbent",
        "scope": "nba_research",
        "model": configuration["model"],
        "model_version": VERSION,
        "config": asdict(config),
        "code_hash": code_hash(),
        "dataset_watermark": data["source_hash"],
        "training_cutoff": as_of.isoformat(),
        "selection_cutoff": evidence["protocol"]["calibration_end"],
        "evaluation_hash": evidence["freeze_hash"],
        "selection_metric": "normalized_all_count_mae",
        "validation_score": loss(selected),
        "baseline_scores": {k: loss(k) for k in result["configurations"]},
        "calibration": result["calibration"][selected]["widths"],
        "training_observations": sum(len(g) for g in population.groups.values()),
        "players": len(population.players),
        "input_hash": population.hash,
        "benchmark": str(benchmark),
        "learning_policy": {
            "automatic_retraining": False,
            "automatic_promotion": False,
            "daily_update": (
                "newly known counts; frozen model configuration and calibration"
            ),
        },
        "fitted_summaries": {
            p: {
                "n": len(population.groups[p]),
                "mean": population.means[population.indices[p]].tolist(),
                "prior_strength": population.strength(p),
                "latest": population.groups[p][-1]["end"].isoformat(),
            }
            for p in population.players
        },
    }
    with instance_lock(registry.path):
        state = registry.read()
        match = next(
            (
                entry
                for entry in state["models"].values()
                if all(entry.get(k) == v for k, v in record.items() if k != "kind")
            ),
            None,
        )
        record["kind"] = (
            match["kind"]
            if match
            else ("incumbent" if state["active"] is None else "candidate")
        )
        identity = registry.register(record, max_candidates=16)
    return {
        "model_id": identity,
        "state": registry.read()["models"][identity]["state"],
        "scope": "NBA research configuration; no live Yahoo activation",
        "selected": selected,
        "training_observations": record["training_observations"],
        "players": record["players"],
        "fit_seconds": time.perf_counter() - started,
        "registry_bytes": registry.path.stat().st_size,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }


def forecasts(
    root: Path,
    registry: Registry,
    output: Path,
    as_of: datetime,
    *,
    seed: int,
    samples: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    state = registry.read()
    active = state["models"].get(state["active"])
    if not active or active.get("scope") != "nba_research":
        raise ValueError("Run fantasy nba train with frozen population evidence first.")
    if (
        active["code_hash"] != code_hash()
        or max(timestamp(active[k]) for k in ("training_cutoff", "selection_cutoff"))
        > as_of
    ):
        raise ValueError("Active NBA model code/time does not match inference cutoff.")
    games, data = load_games(root)
    # Snapshot changes are ingested observations, never automatic config promotion.
    config = ForecastConfig(**active["config"])
    key = digest(
        canonical(
            [data, as_of.isoformat(), state["active"], code_hash(), seed, samples]
        )
    )

    def infer() -> dict[str, Any]:
        population = Population(game_records(games, "strict"), as_of, config)
        predictions = []
        for p in population.players:
            result = population.predict(p, active["model"], seed=seed, samples=samples)
            result.update(
                prediction_timestamp=as_of.isoformat(),
                data_cutoff=as_of.isoformat(),
                nba_player_id=int(p.split(":")[1]),
                dataset_version=data["source_hash"],
                model_id=state["active"],
                horizon="next_recorded_player_game_conditional",
                horizon_start=as_of.isoformat(),
                horizon_end=None,
                calibrated_marginal_intervals_80={
                    s: [
                        max(0, result["expected_counts"][s] - w),
                        result["expected_counts"][s] + w,
                    ]
                    if (w := active["calibration"][s]) is not None
                    else None
                    for s in STATS
                },
                warnings=[
                    (
                        "Conditional on a future recorded player-game row; "
                        "no confirmed game/participation/minutes."
                    ),
                    (
                        "Historical DNP/zero rows remain in empirical "
                        "support; no availability probability fitted."
                    ),
                    (
                        "Season/role/context may change; all historically "
                        "supported IDs retained, current membership unknown."
                    ),
                    (
                        "Marginal residual calibration does not "
                        "recalibrate joint draws or matchup probabilities."
                    ),
                ],
            )
            predictions.append(result)
        return {
            "mode": "NBA-derived conditional forecasts",
            "as_of": as_of.isoformat(),
            "model_id": state["active"],
            "model_version": VERSION,
            "data": data,
            "code_hash": code_hash(),
            "input_hash": population.hash,
            "training_observations": sum(len(g) for g in population.groups.values()),
            "player_count": len(population.players),
            "forecasts": predictions,
            "seven_day_projection": {
                "available": False,
                "game_count": None,
                "reason": (
                    "No verified future NBA schedule, roster "
                    "membership or availability; no seven-day totals fabricated."
                ),
            },
        }

    with instance_lock(output / "nba-forecasts"):
        result, hit = cached(output / "cache" / "nba-forecasts", key, infer)
        artifact = output / f"forecast-{key}.json"
        if not artifact.exists() or json.loads(artifact.read_text()) != result:
            atomic_write(artifact, result)
    return {
        "report": result,
        "artifact": str(artifact),
        "cache_hit": hit,
        "inference_seconds": time.perf_counter() - started,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }


def league_inputs(
    predictions: dict[str, dict[str, Any]], as_of: datetime
) -> tuple[
    tuple[PlayerSnapshot, ...],
    TransactionRules,
    Rules,
    tuple[GameForecast, ...],
    tuple[Selection, ...],
    tuple[Counts, Counts],
    datetime,
]:
    players, transactions, rules, games, opponent, observed, origin = fixture_inputs()
    aliases = {alias: f"nba:{nba_id}" for alias, nba_id in FIXTURE_IDS.items()}
    missing = set(aliases.values()) - predictions.keys()
    if missing:
        raise ValueError(f"Missing verified NBA forecast IDs: {sorted(missing)}")
    players = tuple(
        replace(
            p,
            key=aliases[p.key],
            observed_at=as_of,
            ingested_at=as_of,
            version="fixture-nba-id-bindings-v1",
        )
        for p in players
    )
    transactions = replace(
        transactions, observed_at=as_of, ingested_at=as_of, effective_at=as_of
    )
    rules = replace(
        rules,
        rosters=(
            tuple(aliases[p] for p in rules.rosters[0]),
            tuple(aliases[p] for p in rules.rosters[1]),
        ),
        period_start=as_of,
        period_end=as_of + (rules.period_end - origin),
    )
    forecasts = []
    keys = {}
    for game in games:
        key = f"fixture:{aliases[game.player_key]}:{game.game_key}"
        keys[game.game_key] = key
        p = predictions[aliases[game.player_key]]
        counts = tuple(tuple(int(d[s]) for s in STATS) for d in p["joint_samples"])
        forecasts.append(
            GameForecast(
                key,
                aliases[game.player_key],
                as_of + (game.starts_at - origin),
                as_of + (game.ends_at - origin),
                game.eligible_slots,
                counts,
                p["model_id"],
                missing_inputs=(
                    "real_schedule",
                    "availability",
                    "minutes",
                    "live_eligibility",
                ),
            )
        )
    opponent = tuple(Selection(keys[s.game_key], s.team, s.slot) for s in opponent)
    return players, transactions, rules, tuple(forecasts), opponent, observed, as_of


def run(
    root: Path,
    registry: Registry,
    output: Path,
    as_of: datetime,
    *,
    config: SearchConfig,
    samples: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    inferred = forecasts(
        root, registry, output, as_of, seed=config.seed, samples=samples
    )
    report = inferred["report"]
    predictions = {p["player_key"]: p for p in report["forecasts"]}
    inputs = league_inputs(predictions, as_of)
    # Native binary participates in identity; existing operation helper covers it.
    import importlib
    from hashlib import sha256

    native_hash = None
    if config.backend == "cpp":
        native = importlib.import_module("_matchup")
        if native.__file__ is None:
            raise ValueError("Native binary path unavailable.")
        native_hash = sha256(Path(native.__file__).read_bytes()).hexdigest()
    key = digest(
        canonical(
            [
                report["input_hash"],
                report["model_id"],
                as_of.isoformat(),
                FIXTURE_IDS,
                asdict(config),
                code_watermark(),
                native_hash,
                Path(__file__).read_text(),
                digest(canonical([predictions[p] for p in sorted(predictions)])),
            ]
        )
    )

    def decide() -> dict[str, Any]:
        decision = optimize(*inputs, config=config)
        return {
            "mode": ("fixture league simulation with actual NBA-derived distributions"),
            "live_yahoo_recommendation": False,
            "schedule_source": (
                "existing explicitly hypothetical fixture "
                "schedule; not verified NBA games"
            ),
            "fixture_identity_bindings": FIXTURE_IDS,
            "forecast_artifact": inferred["artifact"],
            "as_of": as_of.isoformat(),
            "data": report["data"],
            "model_id": report["model_id"],
            "forecast_input_hash": report["input_hash"],
            "optimization": decision,
            "limitations": [
                (
                    "Ownership, eligibility, transactions, schedule "
                    "and long-term proxies are fixture assumptions."
                ),
                (
                    "Raw joint samples are uncalibrated; simulated win "
                    "odds are not calibrated live odds."
                ),
            ],
        }

    with instance_lock(output / "nba-run"):
        timing = time.perf_counter()
        result, hit = cached(output / "cache" / "nba-decisions", key, decide)
        elapsed = time.perf_counter() - timing
        artifact = output / f"run-{key}.json"
        if not artifact.exists() or json.loads(artifact.read_text()) != result:
            atomic_write(artifact, result)
    return {
        "report": result,
        "artifact": str(artifact),
        "forecast_cache_hit": inferred["cache_hit"],
        "decision_cache_hit": hit,
        "inference_seconds": inferred["inference_seconds"],
        "optimization_seconds": elapsed,
        "total_seconds": time.perf_counter() - started,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }
