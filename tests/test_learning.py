"""Chronological replay and atomic lifecycle regressions using handmade data."""

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from fantasy_optimizer.cli import main
from fantasy_optimizer.forecast_fixture import fixture_history
from fantasy_optimizer.forecasting import STATS, known_windows
from fantasy_optimizer.learning import TrainingBudget, interval_calibration, replay
from fantasy_optimizer.learning_fixture import (
    backtest_fixture,
    fixture_plan,
    run_fixture,
    train_fixture,
)
from fantasy_optimizer.registry import Registry, RegistryError


def test_replay_as_of_and_late_revisions() -> None:
    windows, _ = fixture_history()
    plan = fixture_plan()
    baseline = replay(
        windows, "recency", plan.calibration_end, plan.validation_end, TrainingBudget()
    )
    first = baseline[0]
    assert first["as_of"] == plan.calibration_end.isoformat()
    old = next(row for row in windows if row.player_key == first["player_key"])
    counts = list(old.counts)
    counts[STATS.index("FGA")] += 100
    future = replace(
        old,
        counts=tuple(counts),
        observed_at=plan.holdout_end,
        ingested_at=plan.holdout_end,
    )
    assert (
        replay(
            windows + [future],
            "recency",
            plan.calibration_end,
            plan.validation_end,
            TrainingBudget(),
        )
        == baseline
    )
    late = replace(
        old,
        observed_at=plan.calibration_end + timedelta(days=1),
        ingested_at=plan.calibration_end + timedelta(days=1),
        counts=tuple(counts),
    )
    revised = replay(
        windows + [late],
        "recency",
        plan.calibration_end,
        plan.validation_end,
        TrainingBudget(),
    )
    assert revised[0] == first
    assert revised[1]["input_hash"] != baseline[1]["input_hash"]
    assert (
        replay(
            list(reversed(windows)),
            "recency",
            plan.calibration_end,
            plan.validation_end,
            TrainingBudget(),
        )
        == baseline
    )


def test_training_does_not_inspect_final_outcomes() -> None:
    windows, _ = fixture_history()
    plan = fixture_plan()
    before = replay(
        windows, "recency", plan.calibration_end, plan.validation_end, TrainingBudget()
    )
    without_final = [row for row in windows if row.start < plan.validation_end]
    assert (
        replay(
            without_final,
            "recency",
            plan.calibration_end,
            plan.validation_end,
            TrainingBudget(),
        )
        == before
    )
    assert all(
        row.start < plan.calibration_end
        for row in known_windows(windows, plan.calibration_end)
    )


def test_calibration_is_later_and_fixed(tmp_path: Path) -> None:
    windows, _ = fixture_history()
    plan = fixture_plan()
    calibration = replay(
        windows, "recency", plan.training_cutoff, plan.calibration_end, TrainingBudget()
    )
    widths = interval_calibration(calibration)
    assert len(calibration) == 8
    errors = sorted(
        abs(case["expected"]["PTS"] - case["actual"]["PTS"]) for case in calibration
    )
    assert widths["PTS"] == errors[7]  # ceil(9 * .8) = 8
    assert interval_calibration(calibration[:7])["PTS"] is None
    report = backtest_fixture(Registry(tmp_path / "unused.json"))
    assert report["models"]["recency"]["widths"] == widths
    assert report["models"]["recency"]["metrics"]["cases"] == 8
    assert (
        min(row["as_of"] for row in report["models"]["recency"]["replay"])
        >= plan.calibration_end.isoformat()
    )
    assert report["probability_calibration"] is None
    assert "incomplete" in report["decision_replay"]


def test_train_run_and_worse_candidate(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "models.json")
    run_fixture(registry)
    assert not registry.path.exists()
    result = train_fixture(registry, model="long_run")
    assert result["training_seconds"] > 0
    assert result["registry_bytes"] == registry.path.stat().st_size
    original = registry.path.read_bytes()
    assert run_fixture(registry) == run_fixture(registry)
    assert registry.path.read_bytes() == original
    repeated = train_fixture(registry, model="long_run")
    assert repeated["candidate"] == result["candidate"]
    assert registry.path.read_bytes() == original
    with pytest.raises(RegistryError, match="does not beat"):
        registry.promote(result["candidate"])
    assert registry.path.read_bytes() == original
    assert registry.read()["active"] != result["candidate"]


def model_record(model: str, kind: str, score: float) -> dict:
    return {
        "model": model,
        "kind": kind,
        "dataset_watermark": "fixture-dataset",
        "evaluation_hash": "same-later-validation",
        "validation_pts_mae": score,
        "baseline_pts_mae": {"long_run": 2.0, "recency": 1.0},
    }


def test_promotion_rollback_and_atomic_failure(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.json")
    old = registry.register(
        model_record("long_run", "incumbent", 2.0), max_candidates=3
    )
    new = registry.register(model_record("recency", "candidate", 1.0), max_candidates=3)
    original = registry.path.read_bytes()
    with patch(
        "fantasy_optimizer.registry.os.replace", side_effect=OSError("interrupted")
    ):
        with pytest.raises(OSError):
            registry.promote(new)
    assert registry.path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [registry.path]
    promoted = registry.promote(new)
    assert promoted["active"] == new
    assert promoted["models"][old]["state"] == "archived"
    assert promoted["models"][new]["promotion_reason"]
    rolled = registry.rollback()
    assert rolled["active"] == old
    assert rolled["models"][new]["state"] == "archived"
    with pytest.raises(RegistryError, match="No previous"):
        registry.rollback()


def test_budget_and_comparable_evaluation(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.json")
    registry.register(model_record("long_run", "incumbent", 2.0), max_candidates=1)
    changed = {**model_record("recency", "candidate", 1.0), "evaluation_hash": "other"}
    identity = registry.register(changed, max_candidates=1)
    with pytest.raises(RegistryError, match="same chronological"):
        registry.promote(identity)
    with pytest.raises(RegistryError, match="budget exhausted"):
        registry.register(model_record("recency", "candidate", 0.5), max_candidates=1)
    with pytest.raises(ValueError, match="budget"):
        TrainingBudget(samples=10000)
    windows, _ = fixture_history()
    plan = fixture_plan()
    with pytest.raises(ValueError, match="case budget"):
        replay(
            windows,
            "recency",
            plan.training_cutoff,
            plan.validation_end,
            TrainingBudget(max_cases=8),
        )
    with pytest.raises(ValueError, match="chronological"):
        replace(plan, calibration_end=plan.training_cutoff)


def test_holdout_single_use_and_freezes_tuning(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.json")
    trained = train_fixture(registry)
    report = backtest_fixture(registry, final=True)
    assert report["split"] == "final_holdout"
    assert report["models"]["recency"]["metrics"]["cases"] == 8
    with pytest.raises(RegistryError, match="already consumed"):
        backtest_fixture(registry, final=True)
    with pytest.raises(RegistryError, match="no more training"):
        train_fixture(registry, model="shrinkage")
    with pytest.raises(RegistryError, match="frozen"):
        registry.promote(trained["candidate"])
    assert run_fixture(registry)["active_baseline"] == "recency"


def test_outcomes_do_not_promote_and_preserve_uncertainty(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.json")
    train_fixture(registry)
    active = registry.read()["active"]
    outcome = {
        "decision_run_id": "handmade-run",
        "model_id": active,
        "as_of": "2026-08-01T00:00:00+00:00",
        "evaluated_at": "2026-08-08T00:00:00+00:00",
        "predicted_utility": 0.6,
        "mc_se": 0.01,
        "model_uncertainty": "uncalibrated toy counts",
        "observed_outcome": "loss",
        "confounders": ["availability unknown"],
        "counterfactual": True,
    }
    assert registry.log_outcome(outcome) == "handmade-run"
    original = registry.path.read_bytes()
    registry.log_outcome(outcome)
    assert registry.path.read_bytes() == original
    assert registry.read()["active"] == active
    with pytest.raises(RegistryError, match="revision"):
        registry.log_outcome({**outcome, "observed_outcome": "win"})
    with pytest.raises(RegistryError, match="follow"):
        registry.log_outcome({**outcome, "evaluated_at": outcome["as_of"]})


@pytest.mark.parametrize("command", ["train", "backtest", "run", "model"])
def test_live_learning_gated(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [command, "--registry", str(tmp_path / "unused.json")]
    if command == "model":
        args.append("status")
    assert main(args) == 1
    assert "live_learning_unavailable" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_cli_lifecycle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shared = ["--fixture", "--registry", str(tmp_path / "registry.json")]
    assert main(["train", *shared, "--model", "long_run"]) == 0
    candidate = json.loads(capsys.readouterr().out)["candidate"]
    assert main(["model", "promote", *shared, "--id", candidate]) == 1
    capsys.readouterr()
    assert main(["model", "status", *shared]) == 0
    active = json.loads(capsys.readouterr().out)["active"]
    assert active
    assert main(["backtest", *shared]) == 0
    assert json.loads(capsys.readouterr().out)["scope"] == "weekly forecasting only"
    before = (tmp_path / "registry.json").read_bytes()
    assert (
        main(
            [
                "run",
                *shared,
                "--database",
                str(tmp_path / "run.duckdb"),
                "--output",
                str(tmp_path / "runs"),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (tmp_path / "registry.json").read_bytes() == before


def test_invalid_registry_is_not_overwritten(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.json")
    registry.path.write_text('{"version": 100}')
    with pytest.raises(RegistryError, match="Invalid registry"):
        train_fixture(registry)
    assert registry.path.read_text() == '{"version": 100}'


def test_final_values_cannot_change_training_artifacts(tmp_path: Path) -> None:
    windows, as_of = fixture_history()
    truncated = [row for row in windows if row.start < fixture_plan().validation_end]
    first = Registry(tmp_path / "first.json")
    second = Registry(tmp_path / "second.json")
    result = train_fixture(first)
    with patch(
        "fantasy_optimizer.learning_fixture.fixture_history",
        return_value=(truncated, as_of),
    ):
        other = train_fixture(second)
    assert result["candidate"] == other["candidate"]
    assert first.path.read_bytes() == second.path.read_bytes()


def test_run_uses_frozen_seed_and_final_budget(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.json")
    budget = TrainingBudget(seed=17, samples=32)
    train_fixture(registry, budget=budget)
    report = run_fixture(registry)
    assert report["seed"] == 17 and report["samples"] == 32
    original = registry.path.read_bytes()
    with pytest.raises(RegistryError, match="frozen training budget"):
        backtest_fixture(registry, final=True)
    assert registry.path.read_bytes() == original


def test_cli_promotion_and_rollback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = Registry(tmp_path / "models.json")
    old = registry.register(
        model_record("long_run", "incumbent", 2.0), max_candidates=3
    )
    new = registry.register(model_record("recency", "candidate", 1.0), max_candidates=3)
    args = ["--fixture", "--registry", str(registry.path)]
    assert main(["model", "promote", *args, "--id", new]) == 0
    assert json.loads(capsys.readouterr().out)["active"] == new
    assert main(["model", "rollback", *args]) == 0
    assert json.loads(capsys.readouterr().out)["active"] == old


def test_changed_code_cannot_open_final_holdout(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.json")
    train_fixture(registry)
    original = registry.path.read_bytes()
    with patch(
        "fantasy_optimizer.learning_fixture.learning_code_hash", return_value="changed"
    ):
        with pytest.raises(RegistryError, match="unchanged code"):
            backtest_fixture(registry, final=True)
    assert registry.path.read_bytes() == original


def test_invalid_budget_cli_and_nonfinite_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = Registry(tmp_path / "registry.json")
    assert (
        main(
            [
                "train",
                "--fixture",
                "--registry",
                str(registry.path),
                "--samples",
                "10000",
            ]
        )
        == 1
    )
    assert "Training budget" in capsys.readouterr().err
    assert not registry.path.exists()
    registry.path.write_text('{"version": 1, "models": {}, "active": NaN}')
    with pytest.raises(RegistryError, match="Invalid registry"):
        registry.read()
