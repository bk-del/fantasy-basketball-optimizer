"""End-to-end fixture safety, caching and meaningful historical CLI boundaries."""

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from fantasy_optimizer.cli import main
from fantasy_optimizer.forecast_fixture import fixture_history
from fantasy_optimizer.learning_fixture import train_fixture
from fantasy_optimizer.operations import OperationError, instance_lock, run_fixture
from fantasy_optimizer.registry import Registry


def paths(root: Path) -> tuple[Path, Path, Registry]:
    return root / "fixture.duckdb", root / "runs", Registry(root / "models.json")


def test_fresh_run_and_cache_reuse(tmp_path: Path) -> None:
    database, output, registry = paths(tmp_path)
    first = run_fixture(database, output, registry)
    assert first["optimization"]["recommended_action"] == "ADD:target/DROP:streamer"
    assert first["weekly"]["active_baseline"] == "recency"
    assert first["sync"]["changed_rows"] == 51
    assert not registry.path.exists()
    artifact = Path(first["artifact"])
    original = artifact.read_bytes()
    with (
        patch(
            "fantasy_optimizer.operations.forecast",
            side_effect=AssertionError("recomputed"),
        ),
        patch(
            "fantasy_optimizer.operations.optimize",
            side_effect=AssertionError("recomputed"),
        ),
    ):
        second = run_fixture(database, output, registry)
    assert second["cache"] == {"weekly_hit": True, "decision_hit": True}
    assert second["run_id"] == first["run_id"]
    assert second["optimization"] == first["optimization"]
    assert second["seed"] == first["seed"] == 42
    assert second["sync"]["changed_rows"] == 0
    assert artifact.read_bytes() == original
    assert not second["league_rules"]["live_verified"]
    assert "category_win_deltas" in second["optimization"]["ranked_actions"][0]


def test_transaction_only_invalidates_decision(tmp_path: Path) -> None:
    _, origin = fixture_history()
    args = paths(tmp_path)
    first = run_fixture(*args, as_of=origin + timedelta(minutes=10))
    changed = run_fixture(
        *args, scenario="transaction", as_of=origin + timedelta(minutes=10)
    )
    assert changed["cache"] == {"weekly_hit": True, "decision_hit": False}
    assert changed["weekly"] == first["weekly"]
    assert changed["run_id"] != first["run_id"]
    assert changed["optimization"]["recommended_action"] == "HOLD"


def test_stats_only_refreshes_weekly_inputs(tmp_path: Path) -> None:
    _, origin = fixture_history()
    args = paths(tmp_path)
    first = run_fixture(*args, as_of=origin + timedelta(minutes=10))
    changed = run_fixture(
        *args, scenario="new_stats", as_of=origin + timedelta(minutes=10)
    )
    assert changed["cache"] == {"weekly_hit": False, "decision_hit": True}
    assert changed["weekly"] != first["weekly"]
    assert changed["optimization"] == first["optimization"]
    assert changed["input_watermark"] != first["input_watermark"]


def test_seed_and_model_invalidation(tmp_path: Path) -> None:
    args = paths(tmp_path)
    run_fixture(*args)
    changed = run_fixture(*args, seed=17)
    assert not any(changed["cache"].values())
    train_fixture(args[2])
    original = args[2].path.read_bytes()
    active = run_fixture(*args)
    assert active["registry_active"] is not None
    assert not active["cache"]["weekly_hit"]
    assert args[2].path.read_bytes() == original


def test_code_and_configuration_invalidation(tmp_path: Path) -> None:
    args = paths(tmp_path)
    run_fixture(*args)
    with patch(
        "fantasy_optimizer.operations.code_watermark", return_value="changed-code"
    ):
        changed = run_fixture(*args)
    assert changed["cache"] == {"weekly_hit": True, "decision_hit": False}
    adjusted = run_fixture(*args, screening_samples=128, finalist_samples=1024)
    assert adjusted["cache"] == {"weekly_hit": True, "decision_hit": False}


def test_partial_ingestion_never_serves_old_result(tmp_path: Path) -> None:
    args = paths(tmp_path)
    first = run_fixture(*args)
    with pytest.raises(OperationError, match="ingestion failed"):
        run_fixture(*args, scenario="partial_ingestion")
    assert list(args[1].glob("*.json")) == [Path(first["artifact"])]
    fresh = tmp_path / "fresh"
    with pytest.raises(OperationError):
        run_fixture(*paths(fresh), scenario="partial_ingestion")
    assert not (fresh / "runs").exists()
    assert run_fixture(*paths(fresh))["saved"]


def test_lock_and_crash_release(tmp_path: Path) -> None:
    args = paths(tmp_path)
    with instance_lock(args[0]):
        with pytest.raises(OperationError, match="Another sync/run"):
            run_fixture(*args)
    assert run_fixture(*args)["saved"]
    try:
        with instance_lock(args[0]):
            raise RuntimeError("interrupted")
    except RuntimeError:
        pass
    with instance_lock(args[0]):
        pass


def test_dry_run_does_not_write_configured_paths(tmp_path: Path) -> None:
    args = paths(tmp_path)
    result = run_fixture(*args, dry_run=True)
    assert result["dry_run"] and not result["saved"]
    assert result["artifact"] is None
    assert not list(tmp_path.iterdir())
    normal = run_fixture(*args)
    original = {
        file: file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()
    }
    result = run_fixture(*args, dry_run=True)
    assert result["optimization"] == normal["optimization"]
    assert original == {file: file.read_bytes() for file in original}


def test_corrupt_cache_and_result_repaired(tmp_path: Path) -> None:
    args = paths(tmp_path)
    first = run_fixture(*args)
    for cached in args[1].glob("cache/*/*.json"):
        cached.write_text('{"key":"wrong"}')
    Path(first["artifact"]).write_text("broken")
    repaired = run_fixture(*args)
    assert not any(repaired["cache"].values())
    assert repaired["optimization"] == first["optimization"]
    assert (
        json.loads(Path(repaired["artifact"]).read_text())["run_id"] == first["run_id"]
    )


def test_historical_ownership_and_model_guard(tmp_path: Path) -> None:
    args = paths(tmp_path)
    _, origin = fixture_history()
    with pytest.raises(OperationError, match="earlier as-of"):
        run_fixture(*args, as_of=origin - timedelta(days=1))
    assert not list(tmp_path.iterdir())
    train_fixture(args[2])
    state = args[2].read()
    state["models"][state["active"]]["training_cutoff"] = (
        origin + timedelta(days=1)
    ).isoformat()
    args[2].path.write_text(json.dumps(state))
    with pytest.raises(OperationError, match="trained after"):
        run_fixture(*args)


def test_structured_logs_are_redacted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with patch.dict(
        "os.environ",
        {"YAHOO_ACCESS_TOKEN": "private-sentinel", "YAHOO_TOKEN_FILE": "secret-path"},
    ):
        run_fixture(*paths(tmp_path))
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name.endswith("operations")
    ]
    assert [entry["event"] for entry in events] == [
        "run_start",
        "sync_complete",
        "run_complete",
    ]
    assert "private-sentinel" not in caplog.text and "secret-path" not in caplog.text
    assert all("players" not in entry and "path" not in entry for entry in events)


def test_cli_as_of_status_and_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "run",
                "--fixture",
                "--dry-run",
                "--database",
                str(tmp_path / "db"),
                "--output",
                str(tmp_path / "runs"),
                "--registry",
                str(tmp_path / "models"),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["dry_run"]
    assert not list(tmp_path.iterdir())
    assert main(["status", "--fixture", "--registry", str(tmp_path / "models")]) == 0
    assert "Owner validation required" in capsys.readouterr().out
    assert (
        main(
            [
                "backtest",
                "--fixture",
                "--as-of",
                "2026-06-01T00:00:00Z",
                "--registry",
                str(tmp_path / "models"),
            ]
        )
        == 1
    )
    assert "not yet known" in capsys.readouterr().err
    with pytest.raises(SystemExit) as error:
        main(["run", "--fixture", "--as-of", "2026-08-24"])
    assert error.value.code == 2
    capsys.readouterr()
    assert (
        main(["forecast", "--fixture", "--as-of", "2026-07-13T00:00:00Z", "--dry-run"])
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["as_of"] == "2026-07-13T00:00:00+00:00"
    assert all(row["as_of"] == report["as_of"] for row in report["forecasts"])


def test_unknown_rules_and_late_asof_fail_safely(tmp_path: Path) -> None:
    report = run_fixture(*paths(tmp_path), scenario="unknown_settings")
    assert report["optimization"]["recommended_action"] == "HOLD"
    assert report["optimization"]["filtered_actions"]
    _, origin = fixture_history()
    with pytest.raises(OperationError, match="observed game totals"):
        run_fixture(*paths(tmp_path / "later"), as_of=origin + timedelta(days=2))
    assert not (tmp_path / "later").exists()


def test_revoked_live_run_and_sync_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch.dict(
        "os.environ",
        {
            "YAHOO_ACCESS_APPROVED": "1",
            "YAHOO_TOKEN_FILE": str(tmp_path / "revoked-secret"),
        },
    ):
        assert (
            main(
                [
                    "run",
                    "--database",
                    str(tmp_path / "db"),
                    "--output",
                    str(tmp_path / "runs"),
                ]
            )
            == 1
        )
    assert "live_learning_unavailable" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
    assert (
        main(["sync", "--fixture", "--dry-run", "--database", str(tmp_path / "db")])
        == 0
    )
    assert not json.loads(capsys.readouterr().out)["saved"]
    assert not list(tmp_path.iterdir())
