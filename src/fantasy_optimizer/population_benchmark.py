"""Full-population chronological evaluation of existing NBA empirical baselines."""

import argparse
import json
import resource
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from fantasy_optimizer.forecasting import STATS, ForecastConfig
from fantasy_optimizer.historical import load_history
from fantasy_optimizer.historical_benchmark import scored
from fantasy_optimizer.learning import interval_calibration, metrics
from fantasy_optimizer.nba_forecasting import (
    Population,
    code_hash,
    game_records,
    load_games,
)
from fantasy_optimizer.registry import Registry, atomic_write
from fantasy_optimizer.storage import canonical, digest, timestamp


def replay(
    records: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    model: str,
    half: float,
    protocol: dict[str, Any],
    *,
    samples: int,
) -> list[dict[str, Any]]:
    targets: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        if start <= r["origin"] < end and max(r["end"], r["available"]) <= end:
            targets[r["origin"]].append(r)
    cases = []
    for origin, rows in sorted(targets.items()):
        scoped = (
            records
            if model != "long_run"
            else [r for r in records if r["season"] == rows[0]["season"]]
        )
        population = Population(scoped, origin, ForecastConfig(half_life_days=half))
        for target in sorted(rows, key=lambda r: r["player"]):
            origin_own = [
                r
                for r in population.groups.get(target["player"], [])
                if r["season"] == target["season"]
            ]
            if len(origin_own) < protocol["minimum_history_observations"]:
                continue
            p = population.predict(
                target["player"], model, seed=protocol["seed"], samples=samples
            )
            own = origin_own
            thresholds = dict(
                zip(
                    STATS,
                    np.floor(np.mean([r["counts"] for r in own], axis=0)).tolist(),
                    strict=True,
                )
            )
            draws = np.array([[d[s] for s in STATS] for d in p["joint_samples"]])
            probabilities = dict(
                zip(
                    STATS,
                    (draws > np.array(list(thresholds.values()))).mean(axis=0).tolist(),
                    strict=True,
                )
            )
            case = {
                "player_key": target["player"],
                "as_of": origin.isoformat(),
                "input_hash": p["input_hash"],
                "outcome_hash": digest(
                    canonical([target["player"], target["id"], target["counts"]])
                ),
                "expected": p["expected_counts"],
                "intervals_80": p["intervals_80"],
                "actual": dict(zip(STATS, target["counts"], strict=True)),
                "thresholds": thresholds,
                "probabilities": probabilities,
                "segment": p["segment"],
                "history_observations": len(own),
                "ratios": {},
            }
            for name, i, j in (("FG%", 0, 1), ("FT%", 2, 3)):
                # Percentage validation excludes target zero-attempt observations;
                # sample zero attempts follows simulator's explicit zero policy.
                if target["counts"][j] == 0:
                    continue
                expected = (
                    p["expected_counts"][STATS[i]] / p["expected_counts"][STATS[j]]
                    if p["expected_counts"][STATS[j]]
                    else 0.0
                )
                ratios = np.divide(
                    draws[:, i],
                    draws[:, j],
                    out=np.zeros(samples),
                    where=draws[:, j] != 0,
                )
                baseline_counts = np.mean([r["counts"] for r in own], axis=0)
                threshold = (
                    float(baseline_counts[i] / baseline_counts[j])
                    if baseline_counts[j]
                    else 0.0
                )
                case["ratios"][name] = {
                    "expected": expected,
                    "actual": target["counts"][i] / target["counts"][j],
                    "interval": np.quantile(ratios, [0.1, 0.9]).tolist(),
                    "probability": float((ratios > threshold).mean()),
                    "threshold": threshold,
                }
            cases.append(case)
    return cases


def summarize(
    cases: list[dict[str, Any]], widths: dict[str, float | None], samples: int
) -> dict[str, Any]:
    result = scored(cases, widths, samples)
    result["unique_players"] = len({c["player_key"] for c in cases})
    for s in STATS:
        result["per_stat"][s]["bias"] = (
            float(np.mean([c["expected"][s] - c["actual"][s] for c in cases]))
            if cases
            else None
        )
    ratios = {}
    for name in ("FG%", "FT%"):
        rows = [c["ratios"][name] for c in cases if name in c["ratios"]]
        ratios[name] = {
            "n": len(rows),
            "mae": float(np.mean([abs(r["expected"] - r["actual"]) for r in rows]))
            if rows
            else None,
            "bias": float(np.mean([r["expected"] - r["actual"] for r in rows]))
            if rows
            else None,
            "raw_coverage_80": float(
                np.mean(
                    [r["interval"][0] <= r["actual"] <= r["interval"][1] for r in rows]
                )
            )
            if rows
            else None,
            "raw_mean_width_80": float(
                np.mean([r["interval"][1] - r["interval"][0] for r in rows])
            )
            if rows
            else None,
            "brier": float(
                np.mean(
                    [
                        (r["probability"] - (r["actual"] > r["threshold"])) ** 2
                        for r in rows
                    ]
                )
            )
            if rows
            else None,
            "zero_target_attempts": "excluded; sample zeros use explicit zero policy",
        }
    result["shooting_ratios"] = ratios
    return result


def comparison(
    cases: dict[str, list[dict[str, Any]]], selected: str, seed: int, repeats: int
) -> dict[str, Any]:
    # Paired player clusters retain every week/game for each resampled player.
    groups: dict[str, list[list[float]]] = defaultdict(list)
    base, candidate = cases["season_to_date"], cases[selected]
    if [(c["player_key"], c["as_of"], c["outcome_hash"]) for c in base] != [
        (c["player_key"], c["as_of"], c["outcome_hash"]) for c in candidate
    ]:
        raise ValueError("Comparisons must share target identities and outcomes.")
    for a, b in zip(base, candidate, strict=True):
        groups[a["player_key"]].append(
            [
                abs(b["expected"][s] - b["actual"][s])
                - abs(a["expected"][s] - a["actual"][s])
                for s in STATS
            ]
        )
    totals = np.array([np.sum(g, axis=0) for g in groups.values()])
    counts = np.array([len(g) for g in groups.values()])
    rng = np.random.default_rng(seed)
    indices = rng.integers(len(groups), size=(repeats, len(groups)))
    draws = totals[indices].sum(axis=1) / counts[indices].sum(axis=1)[:, None]
    return {
        "scope": (
            "paired player-cluster bootstrap; common calendar shocks not removed; "
            "descriptive uncertainty"
        ),
        "players": len(groups),
        "repetitions": repeats,
        "mae_delta_selected_minus_season_to_date": {
            s: {
                "delta": float(totals[:, i].sum() / counts.sum()),
                "interval_95": np.quantile(draws[:, i], [0.025, 0.975]).tolist(),
            }
            for i, s in enumerate(STATS)
        },
    }


def run(
    root: Path, protocol_path: Path, output: Path, *, prepare_only: bool = False
) -> dict[str, Any]:
    protocol = json.loads(protocol_path.read_text())
    if (
        protocol["version"] != "nba-full-population-v1"
        or not 32 <= protocol["samples"] <= 1024
    ):
        raise ValueError("Unsupported protocol.")
    boundaries = [
        timestamp(protocol[k])
        for k in (
            "development_start",
            "development_end",
            "calibration_end",
            "holdout_end",
            "replication_start",
            "replication_end",
        )
    ]
    if boundaries != sorted(set(boundaries)):
        raise ValueError("Strictly chronological boundaries required.")
    started = time.perf_counter()
    games, data = load_games(root, protocol["availability_policy"])
    weekly, _ = load_history(root, policy=protocol["availability_policy"])
    per_game = game_records(games, protocol["availability_policy"])
    for r, g in zip(per_game, games, strict=True):
        r["origin"] = datetime.combine(
            g.game_date, datetime.min.time(), r["end"].tzinfo
        )
    by_game = {(f"nba:{g.nba_player_id}", g.game_id): g for g in games}
    weekly_records = []
    from fantasy_optimizer.nba_forecasting import minutes_value

    for w in weekly:
        mins = [
            m
            for gid in w.game_ids
            if (m := minutes_value(by_game[(w.window.player_key, gid)].minutes_raw))
            is not None
        ]
        weekly_records.append(
            {
                "player": w.window.player_key,
                "id": w.window.start.isoformat(),
                "origin": w.window.start,
                "end": w.window.end,
                "available": w.window.observed_at,
                "counts": w.window.counts,
                "season": w.season,
                "minutes": float(np.mean(mins)) if mins else None,
            }
        )
    freeze = digest(
        canonical([protocol, data, code_hash(), Path(__file__).read_text()])
    )
    registry = Registry(root / "features" / "population-benchmark-registry.json")
    holdout_id = digest(
        canonical(
            [protocol["version"], protocol["calibration_end"], protocol["holdout_end"]]
        )
    )
    if holdout_id in registry.read()["holdouts"]:
        if (
            output.exists()
            and (saved := json.loads(output.read_text()))["freeze_hash"] == freeze
        ):
            return dict(saved)
        raise ValueError(
            "Population holdout already consumed; retain frozen report. No retuning."
        )
    results = {}
    for horizon, records in (("per_game", per_game), ("observed_week", weekly_records)):
        fit_started = time.perf_counter()
        initial = Population(records, boundaries[0], ForecastConfig())
        scales = np.maximum(
            1,
            np.mean(
                [r["counts"] for p in initial.players for r in initial.groups[p]],
                axis=0,
            ),
        )
        variants: dict[str, tuple[str, float]] = {"season_to_date": ("long_run", 28)}
        variants.update(
            {
                f"{model}_{half}": (model, half)
                for model in ("recency", "shrinkage")
                for half in protocol["half_lives_days"]
            }
        )
        development = {}
        for label, (model, half) in variants.items():
            cases = replay(
                records, boundaries[0], boundaries[1], model, half, protocol, samples=32
            )
            score = metrics(cases, dict.fromkeys(STATS))
            development[label] = {
                "normalized_mae": float(
                    np.mean(
                        [
                            score["per_stat"][s]["mae"] / scales[i]
                            for i, s in enumerate(STATS)
                        ]
                    )
                ),
                "metrics": score,
            }
            print(f"{horizon} development {label}: {len(cases)}", flush=True)
        selected = min(
            variants,
            key=lambda label: (
                development[label]["normalized_mae"],
                variants[label][0],
                variants[label][1],
            ),
        )
        # Retain all baselines at the development-selected decay.
        selected_half = variants[selected][1]
        chosen = {
            "season_to_date": ("long_run", 28),
            f"recency_{selected_half}": ("recency", selected_half),
            f"shrinkage_{selected_half}": ("shrinkage", selected_half),
        }
        if selected not in chosen:
            chosen[selected] = variants[selected]
        calibration = {}
        for label, (model, half) in chosen.items():
            cases = replay(
                records,
                boundaries[1],
                boundaries[2],
                model,
                half,
                protocol,
                samples=protocol["samples"],
            )
            widths = interval_calibration(cases)
            calibration[label] = {
                "widths": widths,
                "metrics": summarize(cases, widths, protocol["samples"]),
            }
        results[horizon] = {
            "selected": selected,
            "configurations": {
                label: {"model": m, "half_life_days": h}
                for label, (m, h) in chosen.items()
            },
            "development": development,
            "calibration": calibration,
            "initial_observations": sum(len(g) for g in initial.groups.values()),
            "initial_players": len(initial.players),
            "scales": scales.tolist(),
            "selection_calibration_seconds": time.perf_counter() - fit_started,
        }
    frozen = {
        "freeze_hash": freeze,
        "protocol": protocol,
        "data": data,
        "code_hash": code_hash(),
        "results": results,
    }
    atomic_write(root / "features" / "population-benchmark-frozen.json", frozen)
    if prepare_only:
        return frozen
    registry.consume_holdout(holdout_id)
    for horizon, records in (("per_game", per_game), ("observed_week", weekly_records)):
        result = results[horizon]
        for name, (start, end) in (
            ("holdout", (boundaries[2], boundaries[3])),
            ("replication", (boundaries[4], boundaries[5])),
        ):
            replays = {}
            evaluation = {}
            for label, config in result["configurations"].items():
                cases = replay(
                    records,
                    start,
                    end,
                    config["model"],
                    config["half_life_days"],
                    protocol,
                    samples=protocol["samples"],
                )
                widths = result["calibration"][label]["widths"]
                replays[label] = cases
                evaluation[label] = {
                    "metrics": summarize(cases, widths, protocol["samples"]),
                    "segments": {
                        segment: summarize(
                            [c for c in cases if c["segment"] == segment],
                            widths,
                            protocol["samples"],
                        )
                        for segment in ("high", "medium", "low", "unknown")
                    },
                    "limited_history": summarize(
                        [c for c in cases if c["history_observations"] < 4],
                        widths,
                        protocol["samples"],
                    ),
                    "replay": cases,
                }
                print(f"{horizon} {name} {label}: {len(cases)}", flush=True)
            result[name] = {
                "models": evaluation,
                "comparison": comparison(
                    replays,
                    result["selected"],
                    protocol["seed"],
                    protocol["cluster_bootstrap_repetitions"],
                ),
            }
    report = {
        **frozen,
        "holdout_id": holdout_id,
        "seasons": 2,
        "unique_players": len({g.nba_player_id for g in games}),
        "training_observations_available": len(games),
        "weekly_observations_available": len(weekly),
        "runtime_seconds": time.perf_counter() - started,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "promoted": False,
        "limitations": [
            "Retrospective publication assumption, snapshot revisions unknown.",
            "Conditional on observed rows; no missing weeks/DNP rows invented.",
            (
                "2026 replication period was examined previously; "
                "never used for selection."
            ),
            (
                "Marginal calibration does not change joint draws "
                "or calibrate matchup probabilities."
            ),
        ],
    }
    atomic_write(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/nba_data"))
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("docs/benchmarks/nba-population-protocol.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("docs/benchmarks/nba-population.json")
    )
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    run(args.data, args.protocol, args.output, prepare_only=args.prepare_only)


if __name__ == "__main__":
    main()
