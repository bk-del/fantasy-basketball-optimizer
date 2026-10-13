"""Identity, real game conversion, origin knowledge and season-scoped replay."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fantasy_optimizer.forecasting import (
    ForecastConfig,
    ForecastError,
    RunningAggregate,
    forecast,
    known_windows,
)
from fantasy_optimizer.historical import (
    GameObservation,
    IdentityLink,
    IdentityMap,
    aggregate_games,
    forecast_historical,
    load_history,
)
from fantasy_optimizer.historical_benchmark import historical_replay, select_cohort

RETRIEVED = datetime(2026, 10, 12, tzinfo=UTC)
# Actual first downloaded 2025 playerlog row, joined to gamelog by game/team IDs.
COUNTS = (9, 14, 1, 1, 4, 23, 3, 5, 1, 0, 2)


def game(
    day: date = date(2024, 11, 16),
    *,
    player: int = 1627752,
    team: int = 1610612749,
    identifier: str = "0022400229",
    season: int = 2025,
) -> GameObservation:
    return GameObservation(
        player, team, identifier, season, day, COUNTS, "35:04", None, RETRIEVED
    )


def history(season: int = 2025) -> list[GameObservation]:
    first = date(season - 1, 11, 4)
    return [
        game(
            first + timedelta(weeks=i),
            season=season,
            identifier=f"002{season - 1:02d}{i:03d}",
        )
        for i in range(6)
    ]


def test_identity_evidence_and_cutoff(tmp_path: Path) -> None:
    link = IdentityLink(
        "454.p.1234", 1627752, 2025, RETRIEVED, RETRIEVED, "verified ID sample"
    )
    mapping = IdentityMap([link, link])
    assert mapping.nba_id("454.p.1234", 2025, RETRIEVED) == 1627752
    for key, season, origin in [
        ("454.p.1234", 2025, RETRIEVED - timedelta(seconds=1)),
        ("454.p.1234", 2026, RETRIEVED),
        ("Taurean Prince", 2025, RETRIEVED),
    ]:
        with pytest.raises(ValueError, match="No verified"):
            mapping.nba_id(key, season, origin)
    with pytest.raises(ValueError, match="Conflicting"):
        IdentityMap([link, replace(link, nba_player_id=999)])
    with pytest.raises(ValueError, match="Ambiguous"):
        IdentityMap([link, replace(link, yahoo_player_key="454.p.999")])
    with pytest.raises(ValueError, match="evidence"):
        replace(link, evidence="")
    path = tmp_path / "identities.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "links": [
                    {
                        "yahoo_player_key": link.yahoo_player_key,
                        "nba_player_id": link.nba_player_id,
                        "season": link.season,
                        "observed_at": RETRIEVED.isoformat(),
                        "ingested_at": RETRIEVED.isoformat(),
                        "evidence": link.evidence,
                    }
                ],
            }
        )
    )
    assert (
        IdentityMap.load(path).nba_id(link.yahoo_player_key, 2025, RETRIEVED) == 1627752
    )


def test_real_row_conversion_preserves_counts_ids_and_trades() -> None:
    first = game()
    traded = replace(
        first, game_date=date(2024, 11, 17), game_id="0022400230", team_id=1610612747
    )
    rows = aggregate_games([first, first, traded], "retrospective_next_day")
    assert len(rows) == 1
    row = rows[0]
    assert row.window.player_key == "nba:1627752"
    assert row.window.counts == tuple(2 * v for v in COUNTS)
    assert row.game_ids == ("0022400229", "0022400230")
    assert row.team_ids == (1610612747, 1610612749)
    assert row.source_retrieved_at == RETRIEVED
    assert first.game_date == date(2024, 11, 16) and first.minutes_raw == "35:04"
    assert first.observed_at is None
    with pytest.raises(ValueError, match="Conflicting"):
        aggregate_games([first, replace(first, team_id=1610612747)], "strict")
    with pytest.raises(ForecastError, match="Points"):
        replace(first, counts=COUNTS[:5] + (100,) + COUNTS[6:])
    with pytest.raises(ValueError, match="season"):
        replace(first, season=2026)


def test_retrieval_is_not_historical_publication_and_late_records_are_excluded() -> (
    None
):
    strict = aggregate_games([game()], "strict")[0].window
    retrospective = aggregate_games([game()], "retrospective_next_day")[0].window
    origin = retrospective.end
    assert known_windows([strict], origin) == []
    assert known_windows([strict], RETRIEVED) == [strict]
    assert known_windows([retrospective], origin - timedelta(seconds=1)) == []
    assert known_windows([retrospective], origin) == [retrospective]
    published = replace(game(), observed_at=origin + timedelta(days=2))
    late = aggregate_games([published], "retrospective_next_day")[0].window
    assert known_windows([late], origin) == []
    assert known_windows([late], published.observed_at) == [late]


def test_season_reset_yahoo_mapping_and_future_revision_invariance() -> None:
    old = aggregate_games(history(2025), "retrospective_next_day")
    new = aggregate_games(history(2026), "retrospective_next_day")
    origin = new[-1].window.start
    key = new[0].window.player_key
    first = forecast_historical(
        new, key, origin, season=2026, model="shrinkage", samples=32
    )
    assert (
        forecast_historical(
            old + new, key, origin, season=2026, model="shrinkage", samples=32
        )
        == first
    )
    future = replace(
        new[-1], window=replace(new[-1].window, counts=tuple(100 * v for v in COUNTS))
    )
    assert (
        forecast_historical(
            new[:-1] + [future], key, origin, season=2026, model="shrinkage", samples=32
        )
        == first
    )
    assert first.assumptions["source"].startswith("historical NBA")
    link = IdentityLink(
        "454.p.1234", 1627752, 2026, origin, origin, "verified ID sample"
    )
    mapped = forecast_historical(
        new,
        link.yahoo_player_key,
        origin,
        season=2026,
        identities=IdentityMap([link]),
        samples=32,
    )
    assert mapped.player_key == link.yahoo_player_key
    assert mapped.expected_counts == first.expected_counts
    with pytest.raises(ValueError, match="identity map"):
        forecast_historical(new, link.yahoo_player_key, origin, season=2026)


@pytest.mark.parametrize("half", [7, 14, 28, 56, 112])
def test_configurable_decay_and_aggregate_agree(half: float) -> None:
    rows = aggregate_games(history(), "retrospective_next_day")
    old, recent = rows[0].window, rows[4].window
    recent = replace(recent, counts=tuple(3 * v for v in COUNTS))
    config = ForecastConfig(half_life_days=half)
    result = forecast(
        [old, recent], old.player_key, recent.end, config=config, samples=32
    )
    ratio = 2 ** (-28 / half)
    aggregate = RunningAggregate(config=config)
    aggregate.update(old)
    aggregate.update(recent)
    expected = COUNTS[5] * (ratio + 3) / (ratio + 1)
    assert result.expected_counts["PTS"] == pytest.approx(expected)
    assert aggregate.decayed_totals[5] / aggregate.decayed_weights[5] == pytest.approx(
        expected
    )
    assert (
        result.config_hash
        != forecast(
            [old, recent],
            old.player_key,
            recent.end,
            config=ForecastConfig(half_life_days=half + 1),
            samples=32,
        ).config_hash
    )
    assert forecast([old, recent], old.player_key, recent.end, samples=32) == forecast(
        [old, recent], old.player_key, recent.end, config=ForecastConfig(), samples=32
    )


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, 366])
def test_invalid_decay_rejected(value: float) -> None:
    with pytest.raises(ForecastError):
        ForecastConfig(half_life_days=value)


def test_replay_origin_and_cohort_cannot_see_future_outcomes() -> None:
    rows = aggregate_games(history(), "retrospective_next_day")
    origin, end = rows[4].window.start, rows[-1].window.end
    protocol = {
        "seed": 42,
        "samples": 32,
        "minimum_history_windows": 4,
        "max_cases_per_split": 10,
    }
    cohort = select_cohort(rows, origin, 1, 42, 4)
    first = historical_replay(
        rows, cohort, origin, end, "recency", ForecastConfig(), protocol
    )
    assert len(first) == 2
    changed = replace(
        rows[4], window=replace(rows[4].window, counts=tuple(5 * v for v in COUNTS))
    )
    modified = rows[:4] + [changed] + rows[5:]
    second = historical_replay(
        modified, cohort, origin, end, "recency", ForecastConfig(), protocol
    )
    assert select_cohort(modified, origin, 1, 42, 4) == cohort
    assert second[0]["expected"] == first[0]["expected"]
    assert second[0]["input_hash"] == first[0]["input_hash"]
    assert second[0]["outcome_hash"] != first[0]["outcome_hash"]
    assert second[1]["expected"] != first[1]["expected"]
    equal = historical_replay(
        rows, cohort, origin, end, "long_run", ForecastConfig(), protocol
    )
    assert [r["thresholds"] for r in equal] == [r["thresholds"] for r in first]
    late = replace(
        rows[-1],
        window=replace(rows[-1].window, observed_at=RETRIEVED, ingested_at=RETRIEVED),
    )
    assert (
        len(
            historical_replay(
                rows[:-1] + [late],
                cohort,
                origin,
                end,
                "recency",
                ForecastConfig(),
                protocol,
            )
        )
        == 1
    )


def test_local_real_history_cache_and_inference() -> None:
    root = Path("data/nba_data")
    if not (root / "manifest.json").exists():
        pytest.skip(
            "Owner-authorized ignored NBA snapshot is unavailable in this checkout"
        )
    rows, metadata = load_history(root, policy="retrospective_next_day")
    cached, second = load_history(root, policy="retrospective_next_day")
    assert rows == cached and metadata == second
    assert metadata["seasons"]["2025"]["player_rows"] == 32516
    assert metadata["seasons"]["2026"]["regular_season_games"] == 1230
    target = next(
        r for r in rows if r.window.player_key == "nba:1627752" and r.season == 2025
    )
    origin = target.window.end
    result = forecast_historical(
        rows, target.window.player_key, origin, season=2025, samples=32
    )
    assert result.expected_counts == dict(
        zip(
            (
                "FGM",
                "FGA",
                "FTM",
                "FTA",
                "3PM",
                "PTS",
                "REB",
                "AST",
                "STL",
                "BLK",
                "TO",
            ),
            target.window.counts,
            strict=True,
        )
    )
