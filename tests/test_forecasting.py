"""No leakage, joint-count integrity, shrinkage and artifact contracts."""

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from fantasy_optimizer.cli import main
from fantasy_optimizer.forecast_fixture import (
    benchmark,
    fixture_history,
    forecast_fixture,
)
from fantasy_optimizer.forecasting import (
    STATS,
    Forecast,
    ForecastError,
    RunningAggregate,
    forecast,
    known_windows,
)


def test_future_observation_ingestion_and_correction_do_not_leak() -> None:
    windows, _ = fixture_history()
    origin = windows[2].end
    base = forecast(windows, "fixture.p.1", origin)
    old = windows[0]
    later = replace(
        old,
        observed_at=origin + timedelta(days=1),
        ingested_at=origin + timedelta(days=1),
        counts=tuple(value * 5 for value in old.counts),
    )
    late_ingest = replace(windows[2], ingested_at=origin + timedelta(days=1))
    assert forecast(windows + [later], "fixture.p.1", origin) == base
    assert late_ingest not in known_windows([late_ingest], origin)
    assert forecast(list(reversed(windows)), "fixture.p.1", origin) == base
    selected = known_windows(windows + [later], origin + timedelta(days=1))
    assert later in selected and old not in selected


def test_missing_counts_and_zero_attempts_preserve_missingness() -> None:
    windows, _ = fixture_history()
    first = windows[0]
    counts = list(first.counts)
    counts[STATS.index("FTA")] = None
    counts[STATS.index("REB")] = None
    row = replace(first, counts=tuple(counts))
    result = forecast([row], row.player_key, row.end)
    assert result.expected_counts["FTM"] is None
    assert result.expected_counts["FTA"] is None
    assert result.expected_counts["REB"] is None
    assert result.assumptions["availability_probability"] is None
    assert result.assumptions["game_count"] is None
    assert any("Small sample" in warning for warning in result.warnings)
    zero = replace(first, counts=(0,) * len(STATS))
    prediction = forecast([zero], zero.player_key, zero.end)
    assert all(value == 0 for value in prediction.expected_counts.values())
    assert all(draw["FGA"] == draw["FGM"] == 0 for draw in prediction.joint_samples)
    assert "FG%" not in prediction.expected_counts


def test_invalid_makes_attempts_points_and_counts() -> None:
    windows, _ = fixture_history()
    row = windows[0]
    for index, value in ((0, 999), (4, 999), (5, 0), (6, -1), (7, 1.5)):
        counts = list(row.counts)
        counts[index] = value
        with pytest.raises(ForecastError):
            replace(row, counts=tuple(counts))
    with pytest.raises(ForecastError, match="seven-day"):
        replace(row, start=row.start - timedelta(days=1))
    with pytest.raises(ForecastError, match="ordering"):
        replace(row, ingested_at=row.start)
    with pytest.raises(ForecastError, match="timezones"):
        replace(row, start=row.start.replace(tzinfo=None))


def test_no_data_overlaps_and_conflicting_revisions() -> None:
    windows, as_of = fixture_history()
    with pytest.raises(ForecastError, match="No player"):
        forecast([], "unknown", as_of)
    row = windows[0]
    overlap = replace(
        row,
        start=row.start + timedelta(days=1),
        end=row.end + timedelta(days=1),
        observed_at=row.end + timedelta(days=1),
        ingested_at=row.end + timedelta(days=1),
    )
    with pytest.raises(ForecastError, match="Overlapping"):
        known_windows([row, overlap], as_of)
    conflicting = replace(row, counts=tuple(value * 2 for value in row.counts))
    with pytest.raises(ForecastError, match="Conflicting"):
        known_windows([row, conflicting], as_of)


def test_shrinkage_mean_is_between_player_and_contemporaneous_prior() -> None:
    windows, as_of = fixture_history()
    own = [row for row in windows if row.player_key == "fixture.p.1"]
    sparse = own[:1] + [row for row in windows if row.player_key != "fixture.p.1"]
    origin = own[0].end
    base = forecast(sparse, "fixture.p.1", origin, model="recency")
    shrunk = forecast(sparse, "fixture.p.1", origin, model="shrinkage")
    assert 0 < shrunk.feature_snapshot["own_weight"] < 1
    assert shrunk.expected_counts["PTS"] > base.expected_counts["PTS"]
    assert 2 <= shrunk.feature_snapshot["prior_strength"] <= 20
    later = forecast(windows, "fixture.p.1", as_of, model="shrinkage")
    assert later.feature_snapshot["own_weight"] > shrunk.feature_snapshot["own_weight"]
    fallback = forecast(own, "fixture.p.1", as_of, model="shrinkage")
    assert (
        fallback.expected_counts == forecast(own, "fixture.p.1", as_of).expected_counts
    )
    assert any("No contemporaneous" in warning for warning in fallback.warnings)


@pytest.mark.parametrize("model", ["long_run", "recency", "shrinkage"])
def test_joint_samples_integrity_and_serialization(model: str) -> None:
    windows, as_of = fixture_history()
    result = forecast(windows, "fixture.p.1", as_of, model=model)
    for sample in result.joint_samples:
        assert 0 <= sample["FGM"] <= sample["FGA"]
        assert 0 <= sample["FTM"] <= sample["FTA"]
        assert 0 <= sample["3PM"] <= sample["FGM"]
        assert sample["PTS"] == 2 * sample["FGM"] + sample["3PM"] + sample["FTM"]
    assert Forecast(**json.loads(json.dumps(result.payload()))) == result
    assert result == forecast(windows + windows, "fixture.p.1", as_of, model=model)
    changed_seed = forecast(windows, "fixture.p.1", as_of, model=model, seed=99)
    assert changed_seed.expected_counts == result.expected_counts
    assert changed_seed.joint_samples != result.joint_samples
    assert result.feature_snapshot["as_of"] == result.as_of
    assert result.input_hash == result.feature_snapshot["input_hash"]


def test_resampling_preserves_vectors_instead_of_independent_categories() -> None:
    windows, as_of = fixture_history()
    own = [row for row in windows if row.player_key == "fixture.p.1"]
    vectors = set()
    for row in own:
        for shock in (0.75, 1.0, 1.25):
            values = [round(value * shock) for value in row.counts]
            values[5] = 2 * values[0] + values[4] + values[2]
            vectors.add(tuple(values))
    result = forecast(own, "fixture.p.1", as_of, model="long_run")
    assert all(
        tuple(sample[stat] for stat in STATS) in vectors
        for sample in result.joint_samples
    )


def test_running_aggregate_matches_daily_rebuild() -> None:
    windows, as_of = fixture_history()
    own = [row for row in windows if row.player_key == "fixture.p.1"]
    aggregate = RunningAggregate()
    for row in own:
        aggregate.update(row)
    result = forecast(windows, "fixture.p.1", as_of)
    assert result.feature_snapshot["aggregate"] == aggregate.features()
    assert aggregate.totals[0] == sum(row.counts[0] for row in own)
    assert result.expected_counts["FGM"] == pytest.approx(
        aggregate.decayed_totals[0] / aggregate.decayed_weights[0]
    )
    with pytest.raises(ForecastError, match="chronological"):
        aggregate.update(own[-1])


def test_rolling_origin_metrics_and_monte_carlo_error() -> None:
    windows, as_of = fixture_history()
    report = benchmark(windows, samples=64)
    assert all(result["forecast_cases"] == 40 for result in report["models"].values())
    for result in report["models"].values():
        for metrics in result["per_stat"].values():
            assert metrics["n"] == 40
            assert metrics["mae"] >= 0
            assert 0 <= metrics["coverage_80"] <= 1
            assert 0 <= metrics["threshold_brier"] <= 1
    forecasted = forecast(windows, "fixture.p.1", as_of)
    assert forecasted.mean_mc_standard_error["PTS"] > 0
    assert report["synthetic"] is True


def test_artifact_determinism_and_code_and_input_hashes(tmp_path: Path) -> None:
    first = forecast_fixture(output=tmp_path)
    serialized = Path(first["artifact"]).read_bytes()
    second = forecast_fixture(output=tmp_path)
    assert first == second
    assert serialized == Path(second["artifact"]).read_bytes()
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert len(first["code_hash"]) == 64
    assert first["active_baseline"] == "recency"
    windows, as_of = fixture_history()
    changed = replace(
        windows[0], counts=tuple(value * 2 for value in windows[0].counts)
    )
    assert (
        forecast([changed] + windows[1:], "fixture.p.1", as_of).input_hash
        != first["forecasts"][0]["input_hash"]
    )


def test_cli_live_gate_and_invalid_samples(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["forecast", "--output", str(tmp_path)]) == 1
    assert "live_forecast_unavailable" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
    assert (
        main(["forecast", "--fixture", "--samples", "1", "--output", str(tmp_path)])
        == 1
    )
    assert "forecast_failed" in capsys.readouterr().err
    assert main(["forecast", "--fixture", "--output", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["synthetic"] is True


def test_daily_aggregate_does_not_mutate_saved_feature_snapshot() -> None:
    windows, _ = fixture_history()
    aggregate = RunningAggregate()
    aggregate.update(windows[0])
    snapshot = aggregate.features()
    aggregate.update(windows[1])
    assert snapshot["count"] == 1
    assert snapshot["totals"][0] == windows[0].counts[0]
    assert aggregate.features()["count"] == 2
