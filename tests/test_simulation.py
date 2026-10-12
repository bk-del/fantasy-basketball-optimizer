"""Arithmetic, shared scenarios, constraints and native parity gates."""

import importlib
import json
from dataclasses import replace
from datetime import timedelta
from math import sqrt

import numpy as np
import pytest

from fantasy_optimizer.cli import main
from fantasy_optimizer.matchup_fixture import fixture
from fantasy_optimizer.simulation import (
    Rules,
    Selection,
    prepare,
    reference_outcomes,
    sample_scenarios,
    simulate,
    validate_counts,
)

ZERO = (0,) * 11


def tiny():
    games, _, _, origin = fixture()
    game = replace(
        games[0],
        game_key="a",
        player_key="a",
        eligible_slots=("G",),
        joint_samples=((1, 1, 1, 1, 0, 3, 1, 1, 1, 1, 1),),
    )
    rules = Rules(
        "handmade",
        (("a",), ("b",)),
        ("G",),
        (1, 1),
        "UTC",
        origin,
        origin + timedelta(days=7),
    )
    return (game,), (Selection("a", 0, "G"),), rules, origin


def test_weighted_percentages_turnovers_and_five_wins():
    games, selections, rules, origin = tiny()
    observed = ((0, 9, 0, 9, 0, 0, 0, 0, 0, 0, 0), (4, 10, 4, 10, 0, 12, 0, 0, 0, 0, 2))
    bank = sample_scenarios(games, seed=1, scenarios=2)
    arrays = prepare(games, bank, selections, rules, origin, observed)
    expected = [[-1, -1, 0, -1, 1, 1, 1, 1, 1]] * 2
    assert reference_outcomes(*arrays, False).tolist() == expected
    native = importlib.import_module("_matchup")
    assert native.outcomes(*arrays, False).tolist() == expected
    result = simulate(games, bank, selections, rules, origin, observed)
    assert result["win_probability"] == 1
    assert result["expected_category_wins"] == 5
    assert result["monte_carlo_se"] == 0


@pytest.mark.parametrize("backend", ["python", "cpp"])
def test_ties_zero_attempts_and_league_rules(backend):
    games, _, rules, origin = tiny()
    bank = sample_scenarios(games, seed=2, scenarios=4)
    assert (
        simulate(games, bank, (), rules, origin, (ZERO, ZERO), backend=backend)[
            "win_probability"
        ]
        == 0
    )
    for tie, expected in (("loss", 0), ("half", 0.5), ("win", 1)):
        majority = replace(rules, scoring="category_majority", matchup_ties=tie)
        result = simulate(
            games, bank, (), majority, origin, (ZERO, ZERO), backend=backend
        )
        assert result["expected_matchup_credit"] == expected
        assert result["win_probability"] == (1 if tie == "win" else 0)
        assert all(x == 1 for x in result["category_tie_probability"].values())
    counts = (1, 1, 1, 1, 0, 3, 0, 0, 0, 0, 0)
    for policy, expected in (("zero", 1), ("tie", 0)):
        arrays = prepare(
            games,
            bank,
            (),
            replace(rules, zero_attempts=policy),
            origin,
            (counts, ZERO),
        )
        outcomes = reference_outcomes(*arrays, policy == "tie")
        assert outcomes[0, 0] == expected
        assert outcomes[0, 1] == expected


def test_completed_games_not_double_counted_and_partial_game_rejected():
    games, selections, rules, origin = tiny()
    bank = sample_scenarios(games, seed=1, scenarios=2)
    end = games[0].ends_at
    result = simulate(games, bank, selections, rules, end, (ZERO, ZERO))
    assert result["expected_category_wins"] == 0
    with pytest.raises(ValueError, match="Partially"):
        simulate(games, bank, selections, rules, games[0].starts_at, (ZERO, ZERO))
    assert origin < end


@pytest.mark.parametrize(
    "change,message",
    [
        ({"remaining_game_caps": (0, 1)}, "cap"),
        ({"rosters": ((), ("b",))}, "roster"),
        ({"slots": ("C",)}, "slot"),
        ({"locked": (Selection("a", 1, "G"),)}, "Locked"),
        ({"scoring": "unknown"}, "rules"),
    ],
)
def test_constraints(change, message):
    games, selections, rules, origin = tiny()
    bank = sample_scenarios(games, seed=1, scenarios=2)
    with pytest.raises(ValueError, match=message):
        simulate(
            games, bank, selections, replace(rules, **change), origin, (ZERO, ZERO)
        )


def test_duplicate_slot_game_and_bank_mismatch():
    games, selections, rules, origin = tiny()
    extra = replace(games[0], game_key="b", player_key="b")
    rules = replace(rules, rosters=(("a", "b"), ()), remaining_game_caps=(2, 0))
    bank = sample_scenarios(games + (extra,), seed=1, scenarios=2)
    with pytest.raises(ValueError, match="Occupied"):
        simulate(
            games + (extra,),
            bank,
            selections + (Selection("b", 0, "G"),),
            rules,
            origin,
            (ZERO, ZERO),
        )
    with pytest.raises(ValueError, match="more than once"):
        simulate(games + (extra,), bank, selections * 2, rules, origin, (ZERO, ZERO))
    with pytest.raises(ValueError, match="does not match"):
        simulate(games, bank, selections, rules, origin, (ZERO, ZERO))
    with pytest.raises(ValueError, match="timezone"):
        simulate(
            games,
            sample_scenarios(games, seed=1, scenarios=2),
            selections,
            rules,
            origin.replace(tzinfo=None),
            (ZERO, ZERO),
        )


def test_seed_order_reuse_and_stochastic_parity():
    games, selections, rules, origin = fixture()
    bank = sample_scenarios(games, seed=42, scenarios=1000)
    reordered = sample_scenarios(games[::-1], seed=42, scenarios=1000)
    np.testing.assert_array_equal(bank.values, reordered.values)
    assert bank.input_hash == reordered.input_hash
    assert not bank.values.flags.writeable
    arrays = prepare(games, bank, selections, rules, origin, (ZERO, ZERO))
    native = importlib.import_module("_matchup")
    reference = reference_outcomes(*arrays, False)
    np.testing.assert_array_equal(native.outcomes(*arrays, False), reference)
    np.testing.assert_array_equal(
        native.outcomes(*arrays, False), native.outcomes(*arrays, False)
    )
    assert simulate(games, bank, selections, rules, origin, (ZERO, ZERO)) == simulate(
        games, bank, selections, rules, origin, (ZERO, ZERO), backend="cpp"
    )
    # Re-evaluate a roster with the same bank: unchanged games reuse identical vectors.
    prepare(games, bank, selections[:-1], rules, origin, (ZERO, ZERO))
    np.testing.assert_array_equal(bank.values, reordered.values)
    for index, key in enumerate(bank.game_keys):
        game = next(g for g in games if g.game_key == key)
        assert all(tuple(row) in game.joint_samples for row in bank.values[:, index])


def test_joint_win_probability_se_and_convergence():
    games, selections, rules, origin = tiny()
    good = (1, 1, 1, 1, 1, 4, 1, 1, 1, 1, 0)
    games = (replace(games[0], joint_samples=(ZERO, good)),)
    for n in (1000, 10000, 20000):
        bank = sample_scenarios(games, seed=19, scenarios=n)
        result = simulate(
            games, bank, selections, rules, origin, (ZERO, ZERO), backend="cpp"
        )
        p = result["win_probability"]
        assert abs(p - 0.5) < 4 * sqrt(0.25 / n)
        assert result["monte_carlo_se"] == pytest.approx(sqrt(p * (1 - p) / (n - 1)))
        # All winning categories move together, not independent Bernoulli flags.
        assert result["category_win_probability"]["PTS"] == p


@pytest.mark.parametrize(
    "counts",
    [
        (0,) * 10,
        (1, 0) + (0,) * 9,
        (0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0),
        (-1,) + (0,) * 10,
    ],
)
def test_bad_counts(counts):
    with pytest.raises(ValueError):
        validate_counts(counts)


def test_native_rejects_unsafe_shapes_indices_bounds():
    native = importlib.import_module("_matchup")
    values = np.zeros((1, 1, 11), dtype=np.int64)
    teams = np.array([0], dtype=np.int64)
    totals = np.zeros((2, 11), dtype=np.int64)
    with pytest.raises(ValueError, match="shapes"):
        native.outcomes(values[:, :, :10].copy(), teams, totals, False)
    with pytest.raises(ValueError, match="team"):
        native.outcomes(values, teams + 2, totals, False)
    with pytest.raises(ValueError, match="bound"):
        native.outcomes(values - 1, teams, totals, False)
    with pytest.raises(ValueError, match="Aggregate"):
        native.outcomes(values + 10000000, teams, totals + 1, False)


def test_cli_fixture_gate_and_repeatability(capsys):
    assert main(["simulate"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "live_simulation_unavailable"
    args = ["simulate", "--fixture", "--scenarios", "32"]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert main(args) == 0
    assert capsys.readouterr().out == first
    assert main(args + ["--scenarios", "0"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "simulation_failed"


def test_half_category_credit_changes_threshold():
    games, _, rules, origin = tiny()
    bank = sample_scenarios(games, seed=1, scenarios=8)
    # A wins PTS/REB/AST/STL; ties FG%/FT%/3PM/BLK; loses TO.
    a = (1, 2, 1, 2, 0, 3, 1, 1, 1, 0, 2)
    b = (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1)
    rules = replace(rules, zero_attempts="tie")
    assert simulate(games, bank, (), rules, origin, (a, b))["win_probability"] == 0
    rules = replace(rules, category_ties="half")
    assert (
        simulate(games, bank, (), rules, origin, (a, b), backend="cpp")[
            "win_probability"
        ]
        == 1
    )


def test_period_roster_and_scenario_validation():
    games, selections, rules, origin = tiny()
    bank = sample_scenarios(games, seed=1, scenarios=2)
    with pytest.raises(ValueError, match="scoring period"):
        simulate(
            games, bank, selections, rules, origin - timedelta(days=1), (ZERO, ZERO)
        )
    with pytest.raises(ValueError, match="outside"):
        simulate(
            games,
            bank,
            selections,
            replace(rules, period_end=origin + timedelta(hours=1)),
            origin,
            (ZERO, ZERO),
        )
    with pytest.raises(ValueError, match="roster"):
        simulate(
            games,
            bank,
            selections,
            replace(rules, rosters=(("a",), ("a",))),
            origin,
            (ZERO, ZERO),
        )
    with pytest.raises(ValueError, match="scenario counts"):
        simulate(
            games,
            replace(bank, values=bank.values - 10),
            selections,
            rules,
            origin,
            (ZERO, ZERO),
        )
    invalid = bank.values.copy()
    invalid[:, :, 5] += 1
    with pytest.raises(ValueError, match="Inconsistent scenario"):
        simulate(
            games,
            replace(bank, values=invalid),
            selections,
            rules,
            origin,
            (ZERO, ZERO),
        )
    with pytest.raises(ValueError, match="memory budget"):
        sample_scenarios(fixture()[0], seed=1, scenarios=1000000)


def test_percentage_native_parity_with_zero_attempts_policy():
    games, _, rules, origin = tiny()
    bank = sample_scenarios(games, seed=1, scenarios=2)
    native = importlib.import_module("_matchup")
    a = (1, 3, 2, 7, 0, 4, 0, 0, 0, 0, 0)
    b = (3, 9, 1, 7, 0, 7, 0, 0, 0, 0, 0)
    arrays = prepare(games, bank, (), rules, origin, (a, b))
    expected = [[0, 1, 0, -1, 0, 0, 0, 0, 0]] * 2
    assert native.outcomes(*arrays, False).tolist() == expected
    for policy in (True, False):
        arrays = prepare(games, bank, (), rules, origin, (a, ZERO))
        np.testing.assert_array_equal(
            native.outcomes(*arrays, policy), reference_outcomes(*arrays, policy)
        )


def test_empty_remaining_schedule_and_common_streams_when_pool_changes():
    games, selections, rules, origin = tiny()
    bank = sample_scenarios((), seed=1, scenarios=2)
    result = simulate((), bank, (), rules, origin, (ZERO, ZERO), backend="cpp")
    assert result["win_probability"] == 0
    assert result["monte_carlo_se"] == 0
    base = sample_scenarios(games, seed=1, scenarios=100)
    extra = replace(games[0], game_key="z", player_key="z")
    expanded = sample_scenarios(games + (extra,), seed=1, scenarios=100)
    np.testing.assert_array_equal(base.values[:, 0], expanded.values[:, 0])
