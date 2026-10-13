"""Audit existing decay, prior time boundaries and identifier semantics."""

from dataclasses import replace
from datetime import timedelta

import pytest

from fantasy_optimizer.forecast_fixture import fixture_history
from fantasy_optimizer.forecasting import STATS, RunningAggregate, forecast


@pytest.mark.parametrize("age_days,old_weight", [(7, 2**-0.25), (28, 0.5), (56, 0.25)])
def test_existing_exponential_decay_matches_hand_calculation(
    age_days: int, old_weight: float
) -> None:
    windows, origin = fixture_history()
    template = windows[0]
    recent = replace(
        template,
        start=origin - timedelta(days=7),
        end=origin,
        observed_at=origin,
        ingested_at=origin,
        counts=tuple(3 * v for v in template.counts),
    )
    older = replace(
        template,
        start=recent.start - timedelta(days=age_days),
        end=origin - timedelta(days=age_days),
        observed_at=origin - timedelta(days=age_days),
        ingested_at=origin - timedelta(days=age_days),
    )
    result = forecast([recent, older], template.player_key, origin)
    equal = forecast([older, recent], template.player_key, origin, model="long_run")
    aggregate = RunningAggregate()
    aggregate.update(older)
    aggregate.update(recent)
    for index, stat in enumerate(STATS):
        expected = template.counts[index] * (old_weight + 3) / (old_weight + 1)
        assert result.expected_counts[stat] == pytest.approx(expected)
        assert aggregate.decayed_totals[index] / aggregate.decayed_weights[
            index
        ] == pytest.approx(expected)
        assert equal.expected_counts[stat] == pytest.approx(2 * template.counts[index])
    assert result.expected_counts["PTS"] > equal.expected_counts["PTS"]


@pytest.mark.parametrize("model", ["long_run", "recency", "shrinkage"])
def test_identifier_relabeling_does_not_change_predictive_means(model: str) -> None:
    windows, origin = fixture_history()
    keys = sorted({row.player_key for row in windows})
    mapping = {key: f"nba:{9000000 - i}" for i, key in enumerate(keys)}
    renamed = [replace(row, player_key=mapping[row.player_key]) for row in windows]
    for key in keys:
        first = forecast(windows, key, origin, model=model)
        second = forecast(renamed, mapping[key], origin, model=model)
        assert second.expected_counts == pytest.approx(first.expected_counts)
        assert (
            second.feature_snapshot["own_weight"]
            == first.feature_snapshot["own_weight"]
        )
    # IDs deliberately seed separate RNG streams and provenance; means use counts only.


def test_late_peer_revision_cannot_change_shrinkage_prior() -> None:
    windows, origin = fixture_history()
    peer = next(row for row in windows if row.player_key == "fixture.p.2")
    future = replace(
        peer,
        counts=tuple(100 * v for v in peer.counts),
        observed_at=origin + timedelta(days=1),
        ingested_at=origin + timedelta(days=2),
    )
    first = forecast(windows, "fixture.p.1", origin, model="shrinkage")
    assert (
        forecast(windows + [future], "fixture.p.1", origin, model="shrinkage") == first
    )
    assert (
        forecast(
            windows + [future],
            "fixture.p.1",
            origin + timedelta(days=1),
            model="shrinkage",
        ).expected_counts
        == forecast(
            windows, "fixture.p.1", origin + timedelta(days=1), model="shrinkage"
        ).expected_counts
    )
    admitted = forecast(
        windows + [future], "fixture.p.1", origin + timedelta(days=2), model="shrinkage"
    )
    assert admitted.input_hash != first.input_hash
    assert admitted.expected_counts["PTS"] > first.expected_counts["PTS"]
