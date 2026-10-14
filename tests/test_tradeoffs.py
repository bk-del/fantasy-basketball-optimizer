"""Exact dominance, eligibility, uncertainty, invariance and CLI boundaries."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from fantasy_optimizer.cli import main
from fantasy_optimizer.optimization_fixture import optimize_fixture
from fantasy_optimizer.simulation import CATEGORIES
from fantasy_optimizer.tradeoffs import TradeoffError, render_text, tradeoff_view


def row(
    action: str, credit: float, loss: float, pts: float, reb: float
) -> dict[str, Any]:
    effects = dict.fromkeys(CATEGORIES, 0.0) | {"PTS": pts, "REB": reb}
    return {
        "action": action,
        "matchup_credit_after": credit,
        "win_probability_after": credit,
        "matchup_credit_gain": credit - 0.5,
        "win_probability_mc_se": 0.01,
        "paired_gain_mc_se": 0.02,
        "long_term_value_loss": loss,
        "category_win_deltas": effects,
        "category_tie_deltas": dict.fromkeys(CATEGORIES, 0.0),
        "feasibility": "feasible",
        "refined": True,
        "samples": 4096,
        "recommendable": action == "HOLD",
        "explanation": "Handmade comparison only.",
    }


def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "fixture_only": True,
        "read_only": True,
        "ranked_actions": rows,
        "finalist_samples": 4096,
        "recommended_action": "HOLD",
        "seed": 42,
        "input_hash": "handmade",
    }


def test_crossing_dominated_and_equal_points() -> None:
    source = report(
        [
            row("HOLD", 0.5, 0, 0, 0),
            row("gain", 0.7, 1, 0.2, -0.1),
            row("dominated", 0.4, 2, -0.2, -0.2),
            row("rebound", 0.6, 0, -0.1, 0.2),
            row("equal-rebound", 0.6, 0, -0.1, 0.2),
        ]
    )
    original = copy.deepcopy(source)
    view = tradeoff_view(source)
    assert view["utility_frontier"] == ["equal-rebound", "gain", "rebound"]
    assert view["category_frontier"] == ["HOLD", "equal-rebound", "gain", "rebound"]
    assert source == original and view["recommended_action"] == "HOLD"
    assert view["actions"][3]["recommendable"] is False


def test_category_axes_are_display_only_and_turnovers_already_oriented() -> None:
    source = report([row("HOLD", 0.5, 0, 0, 0), row("points", 0.6, 0, 0.2, -0.1)])
    source["ranked_actions"][1]["category_win_deltas"]["TO"] = -0.3
    original = copy.deepcopy(source)
    all_axes = tradeoff_view(source)
    points = tradeoff_view(source, ("PTS",))
    turnovers = tradeoff_view(source, ("TO",))
    assert all_axes["category_frontier"] == ["HOLD", "points"]
    assert points["category_frontier"] == ["points"]
    assert turnovers["category_frontier"] == ["HOLD"]
    assert all_axes["utility_frontier"] == points["utility_frontier"]
    assert source == original
    text = render_text(all_axes)
    assert "REB -0.1000" in text and "TO -0.3000" in text
    assert "paired SE 0.0200" in text


@pytest.mark.parametrize(
    "change",
    [
        {"refined": False},
        {"samples": 256},
        {"feasibility": "unverified"},
        {"long_term_value_loss": None},
        {"paired_gain_mc_se": None},
        {"win_probability_after": float("nan")},
        {"matchup_credit_after": True},
        {"category_win_deltas": {"PTS": 0.1}},
    ],
)
def test_incomparable_or_missing_rows_excluded(change: dict[str, Any]) -> None:
    candidate = row("bad", 0.8, 0, 0.1, 0.1) | change
    view = tradeoff_view(report([row("HOLD", 0.5, 0, 0, 0), candidate]))
    assert view["utility_frontier"] == ["HOLD"]
    assert view["excluded"][0]["action"] == "bad"
    assert len(view["actions"]) == 1


def test_empty_reordered_input_and_duplicate_identity() -> None:
    assert tradeoff_view(report([]))["category_frontier"] == []
    rows = [row("b", 0.7, 1, 0.2, -0.1), row("a", 0.5, 0, 0, 0)]
    assert tradeoff_view(report(rows)) == tradeoff_view(report(list(reversed(rows))))
    with pytest.raises(TradeoffError, match="unique"):
        tradeoff_view(report([rows[0], rows[0]]))
    with pytest.raises(TradeoffError, match="256"):
        tradeoff_view(report([row(str(i), 0.5, 0, 0, 0) for i in range(257)]))


@pytest.mark.parametrize("categories", [(), ("PTS", "PTS"), ("usage",)])
def test_invalid_axes(categories: tuple[str, ...]) -> None:
    with pytest.raises(TradeoffError, match="category"):
        tradeoff_view(report([]), categories)


def test_real_fixture_invariance_and_screening_exclusion() -> None:
    source = optimize_fixture(seed=42, screening_samples=256, finalist_samples=4096)
    original = copy.deepcopy(source)
    view = tradeoff_view(source)
    assert source == original
    assert view["recommended_action"] == source["recommended_action"]
    assert view["seed"] == source["seed"]
    assert view["utility_frontier"] == ["ADD:target/DROP:streamer"]
    assert {entry["action"] for entry in view["excluded"]} == {
        "ADD:bad-target/DROP:streamer"
    }
    assert all(entry["samples"] == 4096 for entry in view["actions"])
    assert tradeoff_view({"optimization": source}) == view


def test_cli_opt_in_and_saved_view(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["optimize", "--fixture"]) == 0
    normal = json.loads(capsys.readouterr().out)
    assert main(["optimize", "--fixture", "--tradeoffs"]) == 0
    decorated = json.loads(capsys.readouterr().out)
    view = decorated.pop("tradeoffs")
    assert (
        decorated == normal
        and view["recommended_action"] == normal["recommended_action"]
    )
    saved = tmp_path / "result.json"
    saved.write_text(json.dumps(normal))
    original = saved.read_bytes()
    assert (
        main(
            [
                "tradeoffs",
                "--fixture",
                "--input",
                str(saved),
                "--format",
                "json",
                "--categories",
                "PTS,REB",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["categories"] == ["PTS", "REB"]
    assert main(["tradeoffs", "--fixture", "--input", str(saved)]) == 0
    assert "Category win deltas" in capsys.readouterr().out
    assert saved.read_bytes() == original
    assert main(["tradeoffs", "--input", str(saved)]) == 1
    assert "live tradeoff" in capsys.readouterr().err
    saved.write_text("broken")
    assert main(["tradeoffs", "--fixture", "--input", str(saved)]) == 1
    assert "provide saved fixture JSON" in capsys.readouterr().err


def test_nonfixture_report_refused() -> None:
    with pytest.raises(TradeoffError, match="fixture"):
        tradeoff_view(report([]) | {"fixture_only": False})


def test_vectorized_frontier_matches_independent_pairwise_reference() -> None:
    from random import Random

    from fantasy_optimizer.tradeoffs import frontier

    rng = Random(42)
    points = {
        str(index): tuple(float(rng.randrange(5)) for _ in range(10))
        for index in range(64)
    }
    points["duplicate"] = points["0"]
    expected = sorted(
        key
        for key, value in points.items()
        if not any(
            other != key
            and all(a >= b for a, b in zip(candidate, value, strict=True))
            and any(a > b for a, b in zip(candidate, value, strict=True))
            for other, candidate in points.items()
        )
    )
    assert frontier(points) == expected


def test_run_opt_in_keeps_saved_artifact_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [
        "run",
        "--fixture",
        "--database",
        str(tmp_path / "db.duckdb"),
        "--output",
        str(tmp_path / "runs"),
        "--registry",
        str(tmp_path / "models.json"),
    ]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    artifact = Path(first["artifact"])
    original = artifact.read_bytes()
    assert main([*args, "--tradeoffs"]) == 0
    viewed = json.loads(capsys.readouterr().out)
    assert (
        viewed["tradeoffs"]["recommended_action"]
        == first["optimization"]["recommended_action"]
    )
    assert viewed["optimization"] == first["optimization"]
    assert viewed["run_id"] == first["run_id"]
    assert artifact.read_bytes() == original
    assert not (tmp_path / "models.json").exists()
