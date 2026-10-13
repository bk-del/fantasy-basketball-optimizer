"""Known-at-origin diagnostics, future labels, missing sources and baseline gate."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from fantasy_optimizer.cli import main
from fantasy_optimizer.context import (
    PROTOCOL,
    BreakoutProtocol,
    ExposureEvidence,
    breakout_label,
    shift_features,
)
from fantasy_optimizer.context_fixture import context_fixture
from fantasy_optimizer.forecast_fixture import fixture_history
from fantasy_optimizer.forecasting import forecast


def history():
    rows, _ = fixture_history()
    first = rows[0]
    values = [10] * 4 + [20] * 4
    windows = []
    for week, pts in enumerate(values):
        start = first.start + timedelta(weeks=week)
        end = start + timedelta(days=7)
        windows.append(
            replace(
                first,
                start=start,
                end=end,
                observed_at=end,
                ingested_at=end,
                counts=(pts // 2, pts, 0, 0, 0, pts, 0, 0, 0, 0, 0),
            )
        )
    origin = windows[5].end
    exposures = tuple(
        ExposureEvidence(first.player_key, r.start, 2, 2, r.end, r.end, "handmade-test")
        for r in windows[6:]
    )
    return windows, origin, exposures


def test_sustained_shift_and_no_probabilities_or_cause():
    windows, origin, _ = history()
    result = shift_features(windows, windows[0].player_key, origin)
    assert result["shift_detected"] is True
    assert result["baseline_points"] == 10
    assert result["recent_points"] == 20
    assert result["relative_gain"] == 1
    assert result["shift_standard_errors"] == 10
    assert result["breakout_probability"] is None
    assert "teammate_injury_on_off" in result["skipped_features"]
    assert "no role/injury cause" in result["ambiguity"]
    assert all(
        v == "unverified" for k, v in result["coverage"].items() if k != "weekly_counts"
    )


def test_noise_single_spike_and_decline_are_not_sustained_shifts():
    windows, origin, _ = history()
    for counts in ((10, 30), (5, 5), (10, 10)):
        changed = windows.copy()
        for index, pts in zip((4, 5), counts, strict=True):
            changed[index] = replace(
                changed[index],
                counts=(pts // 2, pts, 0, 0, pts % 2, pts, 0, 0, 0, 0, 0),
            )
        assert (
            shift_features(changed, windows[0].player_key, origin)["shift_detected"]
            is False
        )


def test_future_correction_late_ingest_and_input_order_do_not_leak():
    windows, origin, _ = history()
    base = shift_features(windows, windows[0].player_key, origin)
    corrected = replace(
        windows[0],
        observed_at=origin + timedelta(days=1),
        ingested_at=origin + timedelta(days=1),
        counts=(100, 200, 0, 0, 0, 200, 0, 0, 0, 0, 0),
    )
    assert shift_features(windows + [corrected], windows[0].player_key, origin) == base
    assert shift_features(windows[::-1], windows[0].player_key, origin) == base
    late = replace(windows[5], ingested_at=origin + timedelta(days=1))
    result = shift_features(windows[:5] + [late], windows[0].player_key, origin)
    assert result["shift_detected"] is None
    assert "Insufficient" in result["skip_reason"]


def test_missing_counts_gaps_and_zero_baseline_skip_without_imputation():
    windows, origin, _ = history()
    missing = list(windows[0].counts)
    missing[5] = None
    result = shift_features(
        [replace(windows[0], counts=tuple(missing))] + windows[1:],
        windows[0].player_key,
        origin,
    )
    assert result["shift_detected"] is None
    assert result["usable_points_windows"] == 5
    assert "Missing" in result["skip_reason"]
    assert (
        shift_features(windows[1:], windows[0].player_key, origin)["shift_detected"]
        is None
    )
    zeros = [replace(w, counts=(0,) * 11) for w in windows]
    result = shift_features(zeros, windows[0].player_key, origin)
    assert result["relative_gain"] is None
    assert result["shift_detected"] is False


def test_future_label_separation_horizon_and_exposure_minimums():
    windows, origin, exposures = history()
    key = windows[0].player_key
    end = windows[-1].end
    base = shift_features(windows, key, origin)
    label = breakout_label(windows, exposures, key, origin, end)
    assert label["label"] is True
    assert label["feature_input_hash"] == base["input_hash"]
    assert label["outcome_input_hash"] is not None
    incomplete = breakout_label(windows, exposures, key, origin, origin)
    assert incomplete["label"] is None
    assert "incomplete" in incomplete["skip_reason"]
    assert breakout_label(windows, (), key, origin, end)["label"] is None
    low = tuple(replace(e, games_played=1) for e in exposures)
    assert breakout_label(windows, low, key, origin, end)["label"] is None
    unavailable = tuple(replace(e, scheduled_games=4) for e in exposures)
    assert breakout_label(windows, unavailable, key, origin, end)["label"] is None
    assert (
        breakout_label(
            windows,
            exposures,
            key,
            origin,
            end,
            replace(PROTOCOL, minimum_future_games=5),
        )["label"]
        is None
    )
    late = tuple(replace(e, ingested_at=end + timedelta(days=1)) for e in exposures)
    assert breakout_label(windows, late, key, origin, end)["label"] is None
    future = windows.copy()
    future[7] = replace(windows[7], counts=(5, 10, 0, 0, 0, 10, 0, 0, 0, 0, 0))
    assert breakout_label(future, exposures, key, origin, end)["label"] is False
    assert shift_features(future, key, origin) == base
    with pytest.raises(ValueError, match="precedes"):
        breakout_label(windows, exposures, key, origin, origin - timedelta(days=1))


def test_conflicting_exposure_and_invalid_protocol_reject():
    windows, origin, exposures = history()
    with pytest.raises(ValueError, match="Conflicting"):
        breakout_label(
            windows,
            exposures + (replace(exposures[0], games_played=1),),
            windows[0].player_key,
            origin,
            windows[-1].end,
        )
    for kwargs in (
        {"horizon_weeks": 0},
        {"sustained_gain": 0},
        {"minimum_availability": 2},
        {"shift_standard_errors": float("nan")},
    ):
        with pytest.raises(ValueError):
            BreakoutProtocol(**kwargs)
    with pytest.raises(ValueError):
        replace(exposures[0], games_played=3)
    assert replace(PROTOCOL, sustained_gain=0.5) != PROTOCOL


def test_report_skips_training_calibration_and_uplift_baseline_unchanged():
    windows, origin = fixture_history()
    before = forecast(windows, "fixture.p.1", origin)
    report = context_fixture()
    assert report == context_fixture()
    assert report["model_promoted"] is False
    assert report["active_baseline"] == "recency"
    assert report["evaluation"]["usable_labels"] == 0
    assert all(
        report["evaluation"][metric] is None
        for metric in (
            "precision",
            "recall",
            "calibration",
            "decision_uplift_vs_stage03",
        )
    )
    assert "Games and scheduled-availability" in " ".join(
        report["evaluation"]["label_skip_reasons"]
    )
    assert report["context_uncertainty"]["additional_role_multiplier"] is None
    assert forecast(windows, "fixture.p.1", origin) == before


def test_context_cli_offline_repeatability_and_live_gate(capsys):
    assert main(["context"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "live_context_unavailable"
    assert main(["context", "--fixture"]) == 0
    first = capsys.readouterr().out
    assert main(["context", "--fixture"]) == 0
    assert capsys.readouterr().out == first
