"""Reproducible bounded chronological research benchmark using existing baselines."""

import argparse
import json
import math
import resource
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from fantasy_optimizer.forecasting import (
    STATS,
    ForecastConfig,
    count,
    known_windows,
)
from fantasy_optimizer.historical import (
    HistoricalWindow,
    forecast_historical,
    load_history,
)
from fantasy_optimizer.learning import interval_calibration, metrics
from fantasy_optimizer.registry import Registry, atomic_write
from fantasy_optimizer.storage import canonical, digest, timestamp


def select_cohort(
    rows: list[HistoricalWindow], cutoff: datetime, size: int, seed: int, minimum: int
) -> list[str]:
    known = known_windows(
        [r.window for r in rows if r.season == cutoff.year + int(cutoff.month >= 7)],
        cutoff,
    )
    players = sorted(
        {r.player_key for r in known}, key=lambda p: digest(canonical([seed, p]))
    )
    return [
        p
        for p in players
        if sum(r.player_key == p for r in known) >= minimum
        and sum(count(r.counts[5]) for r in known if r.player_key == p) > 0
    ][:size]


def historical_replay(
    rows: list[HistoricalWindow],
    cohort: list[str],
    start: datetime,
    end: datetime,
    model: str,
    config: ForecastConfig,
    protocol: dict[str, Any],
) -> list[dict[str, Any]]:
    selected = [r for r in rows if r.window.player_key in cohort]
    cases: list[dict[str, Any]] = []
    # Group origins once; season boundaries also restrict the peer prior.
    targets = sorted(
        [
            r
            for r in selected
            if start <= r.window.start < end
            and max(r.window.end, r.window.observed_at, r.window.ingested_at) <= end
        ],
        key=lambda r: (r.window.start, r.window.player_key),
    )
    for target in targets:
        origin = target.window.start
        available = known_windows(
            [r.window for r in selected if r.season == target.season], origin
        )
        own = [r for r in available if r.player_key == target.window.player_key]
        if len(own) < protocol["minimum_history_windows"] or own[-1].end != origin:
            continue
        if len(cases) >= protocol["max_cases_per_split"]:
            raise ValueError("Historical replay case budget exceeded.")
        prediction = forecast_historical(
            [r for r in selected if r.season == target.season],
            target.window.player_key,
            origin,
            season=target.season,
            model=model,
            seed=protocol["seed"],
            samples=protocol["samples"],
            config=config,
        )
        # Identical origin-known event threshold for every model/configuration.
        thresholds = {
            s: math.floor(mean(count(r.counts[i]) for r in own))
            for i, s in enumerate(STATS)
        }
        probabilities = {
            s: mean(count(draw[s]) > thresholds[s] for draw in prediction.joint_samples)
            for s in STATS
        }
        cases.append(
            {
                "player_key": target.window.player_key,
                "as_of": origin.isoformat(),
                "season": target.season,
                "input_hash": prediction.input_hash,
                "outcome_hash": digest(canonical(target.window.payload())),
                "expected": prediction.expected_counts,
                "intervals_80": prediction.intervals_80,
                "actual": dict(zip(STATS, target.window.counts, strict=True)),
                "thresholds": thresholds,
                "probabilities": probabilities,
                "games": list(target.game_ids),
                "teams": list(target.team_ids),
            }
        )
    return cases


def scored(
    cases: list[dict[str, Any]], widths: dict[str, float | None], samples: int
) -> dict[str, Any]:
    result = metrics(cases, widths)
    for stat in STATS:
        info = result["per_stat"][stat]
        raw_widths, scores, briers, mc = [], [], [], []
        bins: list[list[tuple[float, int]]] = [[] for _ in range(5)]
        for case in cases:
            lo, hi = case["intervals_80"][stat]
            actual = case["actual"][stat]
            raw_widths.append(hi - lo)
            scores.append(hi - lo + 10 * max(lo - actual, 0) + 10 * max(actual - hi, 0))
            p = case["probabilities"][stat]
            event = int(actual > case["thresholds"][stat])
            briers.append((p - event) ** 2)
            mc.append(math.sqrt(p * (1 - p) / samples))
            bins[min(4, int(p * 5))].append((p, event))
        info.update(
            raw_mean_width_80=mean(raw_widths) if cases else None,
            raw_interval_score_80=mean(scores) if cases else None,
            common_event_brier=mean(briers) if cases else None,
            mean_probability_mc_se=mean(mc) if cases else None,
            reliability=[
                {
                    "n": len(b),
                    "mean_probability": mean(p for p, _ in b) if b else None,
                    "observed_rate": mean(y for _, y in b) if b else None,
                }
                for b in bins
            ],
        )
    return result


def run(root: Path, protocol_path: Path, output: Path) -> dict[str, Any]:
    protocol = json.loads(protocol_path.read_text())
    if (
        protocol["version"] != "nba-walk-forward-v1"
        or protocol["cohort_size"] > 32
        or not 32 <= protocol["samples"] <= 1024
        or protocol["max_cases_per_split"] > 1000
    ):
        raise ValueError("Unsupported/unbounded benchmark protocol.")
    cutoff, dev_end, cal_end, final_start, final_end = [
        timestamp(protocol[k])
        for k in (
            "cohort_cutoff",
            "development_end",
            "calibration_end",
            "evaluation_start",
            "evaluation_end",
        )
    ]
    if not cutoff < dev_end < cal_end < final_start < final_end:
        raise ValueError("Chronological benchmark boundaries required.")
    started = time.perf_counter()
    rows, data = load_history(root, policy=protocol["availability_policy"])
    cohort = select_cohort(
        rows,
        cutoff,
        protocol["cohort_size"],
        protocol["seed"],
        protocol["minimum_history_windows"],
    )
    if len(cohort) != protocol["cohort_size"]:
        raise ValueError("Insufficient pre-development cohort.")
    initial = known_windows(
        [
            r.window
            for r in rows
            if r.season == cutoff.year + int(cutoff.month >= 7)
            and r.window.player_key in cohort
        ],
        cutoff,
    )
    scales = {
        s: max(1.0, mean(count(r.counts[i]) for r in initial))
        for i, s in enumerate(STATS)
    }
    code = digest(
        "".join(
            Path(__file__).with_name(name).read_text()
            for name in (
                "historical_benchmark.py",
                "historical.py",
                "forecasting.py",
                "learning.py",
            )
        )
    )
    freeze_hash = digest(canonical([protocol, data, code, cohort, scales]))
    registry = Registry(root / "features" / "benchmark-registry.json")
    holdout_id = digest(
        canonical([protocol["version"], final_start.isoformat(), final_end.isoformat()])
    )
    # Immutable saved output is the reproducible replay after the one-use gate.
    if holdout_id in registry.read()["holdouts"]:
        if output.exists():
            saved: dict[str, Any] = json.loads(output.read_text())
            if saved["freeze_hash"] == freeze_hash:
                return saved
        raise ValueError(
            "Holdout already opened; use the saved frozen report or a new later period."
        )
    development = {}
    for half in protocol["half_lives_days"]:
        config = ForecastConfig(half_life_days=half)
        cases = historical_replay(
            rows, cohort, cutoff, dev_end, "recency", config, protocol
        )
        summary = metrics(cases, dict.fromkeys(STATS))
        if not cases:
            raise ValueError("No development cases.")
        loss = mean(summary["per_stat"][s]["mae"] / scales[s] for s in STATS)
        development[str(half)] = {"normalized_mae": loss, "metrics": summary}
        print(f"development half-life={half}: {loss:.6f}", flush=True)
    selected = min(
        protocol["half_lives_days"],
        key=lambda h: (development[str(h)]["normalized_mae"], h),
    )
    variants = {
        "season_to_date": ("long_run", ForecastConfig()),
        "recency_28": ("recency", ForecastConfig()),
        "recency_selected": ("recency", ForecastConfig(half_life_days=selected)),
        "shrinkage_28": ("shrinkage", ForecastConfig()),
    }
    calibration, widths = {}, {}
    for label, (model, config) in variants.items():
        cases = historical_replay(
            rows, cohort, dev_end, cal_end, model, config, protocol
        )
        widths[label] = interval_calibration(cases)
        calibration[label] = {
            "metrics": scored(cases, widths[label], protocol["samples"]),
            "widths": widths[label],
        }
        print(f"calibrated {label}: {len(cases)} cases", flush=True)
    frozen = {
        "freeze_hash": freeze_hash,
        "protocol": protocol,
        "data": data,
        "code_hash": code,
        "cohort": cohort,
        "scales": scales,
        "selected_half_life_days": selected,
        "configurations": {
            k: {"model": m, "config": asdict(c)} for k, (m, c) in variants.items()
        },
        "development": development,
        "calibration": calibration,
    }
    atomic_write(root / "features" / "benchmark-frozen.json", frozen)
    registry.consume_holdout(holdout_id)
    evaluation = {}
    for label, (model, config) in variants.items():
        cases = historical_replay(
            rows, cohort, final_start, final_end, model, config, protocol
        )
        evaluation[label] = {
            "metrics": scored(cases, widths[label], protocol["samples"]),
            "replay": cases,
        }
        print(f"evaluated {label}: {len(cases)} cases", flush=True)
    report = {
        **frozen,
        "evaluation": evaluation,
        "holdout_id": holdout_id,
        "runtime_seconds": time.perf_counter() - started,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "scope": (
            "retrospective weekly counts; conditional on observed "
            "contiguous player-weeks"
        ),
        "promoted": False,
        "production_default_half_life_days": 28,
    }
    atomic_write(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/nba_data"))
    parser.add_argument(
        "--protocol", type=Path, default=Path("docs/benchmarks/nba-protocol.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("docs/benchmarks/nba-real-data.json")
    )
    args = parser.parse_args()
    run(args.data, args.protocol, args.output)


if __name__ == "__main__":
    main()
