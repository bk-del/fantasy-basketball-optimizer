"""Budgeted weekly replay: calibration precedes validation; holdout stays sealed."""

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import mean
from typing import Any

from fantasy_optimizer.forecasting import (
    MODELS,
    STATS,
    Window,
    forecast,
    known_windows,
)
from fantasy_optimizer.storage import canonical, digest, timestamp


@dataclass(frozen=True)
class TrainingBudget:
    seed: int = 42
    samples: int = 256
    max_cases: int = 32
    max_candidates: int = 3

    def __post_init__(self) -> None:
        if not 32 <= self.samples <= 1024 or not 8 <= self.max_cases <= 128:
            raise ValueError("Training budget requires 32..1024 samples, 8..128 cases.")
        if not 1 <= self.max_candidates <= 3:
            raise ValueError("Candidate budget must be 1..3; no unbounded tuning.")


@dataclass(frozen=True)
class ReplayPlan:
    training_cutoff: datetime
    calibration_end: datetime
    validation_end: datetime
    holdout_end: datetime

    def __post_init__(self) -> None:
        times = [timestamp(value.isoformat()) for value in asdict(self).values()]
        if times != sorted(set(times)):
            raise ValueError("Replay boundaries must be strictly chronological.")

    def payload(self) -> dict[str, str]:
        return {key: value.isoformat() for key, value in asdict(self).items()}


def replay(
    windows: list[Window],
    model: str,
    start: datetime,
    end: datetime,
    budget: TrainingBudget,
) -> list[dict[str, Any]]:
    """Outcomes known by end; each forecast sees only origin-known observations."""
    start, end = timestamp(start.isoformat()), timestamp(end.isoformat())
    if start >= end or model not in MODELS:
        raise ValueError("Invalid replay range/model.")
    targets = [row for row in known_windows(windows, end) if start <= row.start < end]
    if len(targets) > budget.max_cases:
        raise ValueError("Replay case budget exceeded; no silent truncation.")
    results = []
    for target in targets:
        available = known_windows(windows, target.start)
        history = [row for row in available if row.player_key == target.player_key]
        if len(history) < 2 or history[-1].end != target.start:
            continue
        prediction = forecast(
            available,
            target.player_key,
            target.start,
            model=model,
            seed=budget.seed,
            samples=budget.samples,
        )
        results.append(
            {
                "player_key": target.player_key,
                "as_of": target.start.isoformat(),
                "input_hash": digest(canonical([row.payload() for row in available])),
                "outcome_hash": digest(canonical(target.payload())),
                "expected": prediction.expected_counts,
                "intervals_80": prediction.intervals_80,
                "actual": dict(zip(STATS, target.counts, strict=True)),
            }
        )
    return results


def interval_calibration(cases: list[dict[str, Any]]) -> dict[str, float | None]:
    """Fixed 80% absolute-residual quantiles, fitted only on calibration origins.

    Marginal count intervals are diagnostics, not a new joint scenario sampler.
    Small/repeated-player synthetic samples cannot establish live calibration.
    """
    result: dict[str, float | None] = {}
    for stat in STATS:
        errors = sorted(
            abs(case["expected"][stat] - case["actual"][stat])
            for case in cases
            if case["expected"][stat] is not None and case["actual"][stat] is not None
        )
        rank = math.ceil((len(errors) + 1) * 0.8)
        result[stat] = (
            errors[rank - 1] if len(errors) >= 8 and rank <= len(errors) else None
        )
    return result


def metrics(
    cases: list[dict[str, Any]], widths: dict[str, float | None]
) -> dict[str, Any]:
    per_stat = {}
    for stat in STATS:
        usable = [
            case
            for case in cases
            if case["expected"][stat] is not None and case["actual"][stat] is not None
        ]
        errors = [abs(case["expected"][stat] - case["actual"][stat]) for case in usable]
        original = [
            int(
                case["intervals_80"][stat][0]
                <= case["actual"][stat]
                <= case["intervals_80"][stat][1]
            )
            for case in usable
        ]
        width = widths[stat]
        per_stat[stat] = {
            "n": len(errors),
            "mae": mean(errors) if errors else None,
            "raw_coverage_80": mean(original) if original else None,
            "calibrated_coverage_80": mean([int(error <= width) for error in errors])
            if errors and width is not None
            else None,
            "calibrated_half_width": width,
        }
    return {"cases": len(cases), "per_stat": per_stat}


def evaluate(
    windows: list[Window],
    plan: ReplayPlan,
    budget: TrainingBudget,
    *,
    final: bool = False,
) -> dict[str, Any]:
    comparisons = {}
    for model in MODELS:
        calibration = replay(
            windows, model, plan.training_cutoff, plan.calibration_end, budget
        )
        widths = interval_calibration(calibration)
        start = plan.validation_end if final else plan.calibration_end
        end = plan.holdout_end if final else plan.validation_end
        cases = replay(windows, model, start, end, budget)
        comparisons[model] = {
            "calibration_cases": len(calibration),
            "widths": widths,
            "metrics": metrics(cases, widths),
            "replay": cases,
        }
    return {
        "scope": "weekly forecasting only",
        "synthetic": True,
        "decision_replay": "incomplete: historical waiver/ownership snapshots absent",
        "split": "final_holdout" if final else "validation",
        "plan": plan.payload(),
        "budget": asdict(budget),
        "models": comparisons,
        "probability_calibration": None,
        "probability_calibration_reason": "No verified matchup/breakout outcomes.",
        "ensemble": "not fitted: no sufficient out-of-time live evidence",
        "limitations": [
            "Marginal intervals are diagnostic; joint sampler is unchanged.",
            "Origin histories use only already known observations.",
            "Repeated fictional players are not independent calibration evidence.",
            "Counterfactual transactions are approximations; none are evaluated here.",
        ],
    }
