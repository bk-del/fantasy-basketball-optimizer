"""Decision arithmetic and point-in-time boundaries without expensive fitting."""

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from fantasy_optimizer.advanced_features import counts_from_primitives
from fantasy_optimizer.decision_replay import (
    candidate_actions,
    choose_action,
    compare_totals,
    credits,
    realized_counts,
    roster_after,
    weekly_banks,
)


def row(origin: datetime, offset: int = -1) -> dict[str, Any]:
    primitive = np.array([4, 5, 2, 4, 3, 1, 6, 5, 1, 2, 3], dtype=float)
    day = origin + timedelta(days=offset)
    return {
        "player": "nba:1",
        "day": day,
        "end": day + timedelta(days=1),
        "available": day + timedelta(days=1),
        "primitive": primitive,
        "counts": counts_from_primitives(primitive),
    }


def test_same_feasible_actions_and_hold_tie() -> None:
    actions = candidate_actions(["a", "b"], ["c", "d"])
    assert len(actions) == 5 and actions[0] == ("", "")
    rosters = [roster_after(["a", "b"], a) for a in actions]
    banks = {p: np.zeros((3, 11), dtype=np.int64) for p in "abcdo"}
    best, _ = choose_action(rosters, ["o"], banks)
    assert best == 0
    with pytest.raises(ValueError):
        candidate_actions(["a"], ["a"])
    with pytest.raises(ValueError):
        roster_after(["a"], ("b", "c"))


def test_aggregate_shooting_ratios_turnovers_and_zero_attempt_ties() -> None:
    # Better FG% despite fewer makes; FT zero attempts ties; lower TO wins.
    a = np.array([[5, 10, 0, 0, 2, 12, 6, 3, 1, 1, 1]], dtype=np.int64)
    b = np.array([[6, 20, 1, 1, 2, 12, 6, 3, 1, 1, 5]], dtype=np.int64)
    outcomes = compare_totals(a, b)
    assert outcomes.tolist() == [[1, 0, 0, 0, 0, 0, 0, 0, 1]]
    matchup, category = credits(outcomes)
    assert matchup.tolist() == [1] and category.tolist() == [5.5]


def test_sampler_deterministic_valid_and_future_refused() -> None:
    origin = datetime(2025, 11, 10, tzinfo=UTC)
    rows = [row(origin, -i) for i in range(1, 20)]
    mean = np.asarray([rows[0]["primitive"]])
    a = weekly_banks({"nba:1": rows}, ["nba:1"], origin, mean, 42, 32)
    b = weekly_banks({"nba:1": rows}, ["nba:1"], origin, mean, 42, 32)
    assert np.array_equal(a["nba:1"], b["nba:1"])
    counts = a["nba:1"]
    assert np.all(counts[:, 0] <= counts[:, 1])
    assert np.all(counts[:, 2] <= counts[:, 3])
    assert np.all(counts[:, 4] <= counts[:, 0])
    assert np.array_equal(counts[:, 5], 2 * counts[:, 0] + counts[:, 4] + counts[:, 2])
    with pytest.raises(ValueError, match="Future row"):
        weekly_banks(
            {"nba:1": rows + [row(origin, 1)]}, ["nba:1"], origin, mean, 42, 32
        )


def test_outcome_only_horizon_and_missing_rows() -> None:
    origin = datetime(2025, 11, 10, tzinfo=UTC)
    records = [row(origin, offset) for offset in (-1, 0, 6, 7)]
    totals = realized_counts(records, ["nba:1", "nba:2"], origin)
    assert np.array_equal(totals["nba:1"], 2 * records[0]["counts"])
    assert totals["nba:2"].sum() == 0
    # Modifying outcomes cannot mutate the source historical sample bank.
    history = [row(origin, -1)]
    means = np.asarray([history[0]["primitive"]])
    before = weekly_banks({"nba:1": history}, ["nba:1"], origin, means, 2, 8)
    records[1]["counts"] *= 100
    after = weekly_banks({"nba:1": history}, ["nba:1"], origin, means, 2, 8)
    assert np.array_equal(before["nba:1"], after["nba:1"])
