"""Offline registry lifecycle using existing handmade weekly windows only."""

from dataclasses import asdict
from datetime import timedelta
from importlib.resources import files
from time import perf_counter
from typing import Any

from fantasy_optimizer.forecast_fixture import fixture_history, forecast_fixture
from fantasy_optimizer.forecasting import CONFIG, MODEL_VERSION, MODELS, known_windows
from fantasy_optimizer.learning import ReplayPlan, TrainingBudget, evaluate
from fantasy_optimizer.registry import Registry, RegistryError
from fantasy_optimizer.storage import canonical, digest

DEFAULT_BUDGET = TrainingBudget()


def fixture_plan() -> ReplayPlan:
    windows, _ = fixture_history()
    start = min(row.start for row in windows)
    return ReplayPlan(*(start + timedelta(weeks=n) for n in (6, 8, 10, 12)))


def dataset_watermark() -> str:
    windows, _ = fixture_history()
    # Training/selection never hashes or inspects final-holdout outcomes.
    return digest(
        canonical(
            [
                row.payload()
                for row in known_windows(windows, fixture_plan().validation_end)
            ]
        )
    )


def holdout_identity() -> str:
    return digest(
        canonical({"dataset": dataset_watermark(), "plan": fixture_plan().payload()})
    )


def learning_code_hash() -> str:
    return digest(
        canonical(
            {
                name: files("fantasy_optimizer").joinpath(name).read_text()
                for name in (
                    "forecasting.py",
                    "forecast_fixture.py",
                    "learning.py",
                    "learning_fixture.py",
                    "registry.py",
                )
            }
        )
    )


def train_fixture(
    registry: Registry,
    *,
    model: str = "recency",
    budget: TrainingBudget = DEFAULT_BUDGET,
) -> dict[str, Any]:
    if model not in MODELS:
        raise RegistryError("Unknown candidate baseline.")
    before = registry.read()
    if holdout_identity() in before["holdouts"]:
        raise RegistryError("Final holdout consumed: no more training on this period.")
    started = perf_counter()
    windows, _ = fixture_history()
    plan = fixture_plan()
    evaluation = evaluate(windows, plan, budget)
    scores = {
        key: value["metrics"]["per_stat"]["PTS"]["mae"]
        for key, value in evaluation["models"].items()
    }
    if any(value is None for value in scores.values()):
        raise RegistryError("Insufficient validation observations.")
    code_hash = learning_code_hash()
    common = {
        "model_version": MODEL_VERSION,
        "dataset_watermark": dataset_watermark(),
        "training_cutoff": plan.training_cutoff.isoformat(),
        "evaluation_hash": digest(
            canonical(
                {
                    "plan": plan.payload(),
                    "budget": asdict(budget),
                    "code_hash": code_hash,
                }
            )
        ),
        "code_hash": code_hash,
        "budget": asdict(budget),
        "plan": plan.payload(),
        "baseline_pts_mae": scores,
        "synthetic": True,
        "selection_metric": "later validation PTS MAE (fixed before evaluation)",
        "training": "baseline running-stat refits at chronological origins; no ML fit",
    }

    def record(key: str, kind: str) -> dict[str, Any]:
        return {
            **common,
            "model": key,
            "kind": kind,
            "config_hash": digest(
                canonical({"model": key, "config": CONFIG, "budget": asdict(budget)})
            ),
            "validation_pts_mae": scores[key],
            "metrics": evaluation["models"][key]["metrics"],
            "calibration_widths": evaluation["models"][key]["widths"],
        }

    if before["active"] is None:
        registry.register(
            record("recency", "incumbent"), max_candidates=budget.max_candidates
        )
    identity = registry.register(
        record(model, "candidate"), max_candidates=budget.max_candidates
    )
    return {
        "mode": "fixture",
        "candidate": identity,
        "active": registry.read()["active"],
        "auto_promoted": False,
        "comparison": scores,
        "training_seconds": perf_counter() - started,
        "registry_bytes": registry.path.stat().st_size,
        "training_budget": asdict(budget),
        "periodic_full_retrain": "skipped: insufficient verified data for LightGBM",
        "policy_tuning": "disabled; fixed metric and candidate budget, no Optuna",
        "early_stopping": "not applicable to closed-form running statistics",
        "promotion_reason": "Incumbent retained pending explicit validation promotion",
    }


def backtest_fixture(
    registry: Registry,
    *,
    final: bool = False,
    budget: TrainingBudget = DEFAULT_BUDGET,
) -> dict[str, Any]:
    if final:
        state = registry.read()
        if state["active"] is None:
            raise RegistryError(
                "Train/freeze an active model before opening the holdout."
            )
        active = state["models"][state["active"]]
        if (
            active["code_hash"] != learning_code_hash()
            or active["dataset_watermark"] != dataset_watermark()
            or active["plan"] != fixture_plan().payload()
        ):
            raise RegistryError(
                "Final evaluation requires unchanged code/data/protocol."
            )
        if active["budget"] != asdict(budget):
            raise RegistryError("Final evaluation must use the frozen training budget.")
        # Reserve before exposing any final outcomes; no retry after inspection.
        registry.consume_holdout(holdout_identity())
    windows, _ = fixture_history()
    report = evaluate(windows, fixture_plan(), budget, final=final)
    report.update(
        registry_active=registry.read()["active"],
        dataset_watermark=dataset_watermark(),
        holdout_consumed=final,
    )
    return report


def run_fixture(registry: Registry) -> dict[str, Any]:
    state = registry.read()
    active = state["models"].get(state["active"])
    model = active["model"] if active else "recency"
    budget = active["budget"] if active else asdict(DEFAULT_BUDGET)
    report = forecast_fixture(
        model=model, seed=budget["seed"], samples=budget["samples"], output=None
    )
    report.update(
        registry_active=state["active"],
        training_requested=False,
        registry_modified=False,
        daily_update="existing running-stat baseline; no full retrain",
    )
    return report
