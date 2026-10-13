"""Stage 05 feasibility, matchup objective and no-leakage acceptance gates."""

import json
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from fantasy_optimizer.cli import main
from fantasy_optimizer.optimization import (
    Action,
    SearchConfig,
    assess,
    optimize,
    plan_lineup,
    yahoo_constraints_unverified,
)
from fantasy_optimizer.optimization_fixture import fixture_inputs
from fantasy_optimizer.simulation import Selection

CONFIG = SearchConfig(screening_samples=64, finalist_samples=512)


def run(scenario="baseline", **kwargs):
    return optimize(*fixture_inputs(scenario), config=kwargs.get("config", CONFIG))


def row(result, key):
    return next(item for item in result["ranked_actions"] if item["action"] == key)


def filtered(result, key):
    return next(item for item in result["filtered_actions"] if item["action"] == key)


@pytest.mark.parametrize(
    "scenario",
    [
        "none_available",
        "acquisition_cap",
        "bad_moves",
        "impossible_comeback",
        "unknown_settings",
    ],
)
def test_hold_when_no_beneficial_legal_acquisition(scenario):
    result = run(scenario)
    assert result["recommended_action"] == "HOLD"
    assert result["read_only"] is True
    assert row(result, "HOLD")["matchup_credit_gain"] == 0
    if scenario == "impossible_comeback":
        assert all(
            action["win_probability_after"] == 0 for action in result["ranked_actions"]
        )
    if scenario == "unknown_settings":
        action = filtered(result, "ADD:target/DROP:streamer")
        assert action["feasibility"] == "unverified"
        assert any("acquisitions_remaining" in reason for reason in action["reasons"])


def test_ranked_improvement_separate_from_long_term_cost():
    result = run()
    best = row(result, "ADD:target/DROP:streamer")
    assert result["recommended_action"] == best["action"]
    assert best["win_probability_after"] > best["win_probability_before"]
    assert best["matchup_credit_gain"] > 2 * best["paired_gain_mc_se"]
    assert best["long_term_value_loss"] == 0
    assert best["added_long_term_value"] == 2
    assert best["dropped_long_term_value"] == 1
    assert best["samples"] == 512
    assert row(result, "HOLD")["samples"] == 512
    assert row(result, "ADD:bad-target/DROP:streamer")["refined"] is False
    assert result["evaluated_actions"] == 3
    assert result["refined_actions"] == 2


def test_full_roster_protected_drop_and_position_rejections():
    result = run()
    assert "full" in " ".join(filtered(result, "ADD:target/DROP:-")["reasons"])
    assert "Protected" in " ".join(
        filtered(result, "ADD:target/DROP:anchor")["reasons"]
    )
    assert "position" in " ".join(
        filtered(result, "ADD:wrong-position/DROP:streamer")["reasons"]
    )
    assert "Waiver" in " ".join(
        filtered(result, "ADD:waiver-target/DROP:streamer")["reasons"]
    )


@pytest.mark.parametrize(
    "field,value,status,reason",
    [
        ("acquisitions_remaining", None, "unverified", "Missing setting"),
        ("ir_moves_allowed", None, "unverified", "Missing setting"),
        ("budget_remaining", 0, "rejected", "budget"),
        ("waiver_policy", "priority", "unverified", "Unsupported"),
        ("roster_capacity", None, "unverified", "Missing setting"),
    ],
)
def test_setting_filter(field, value, status, reason):
    players, tx, rules, games, _, _, origin = fixture_inputs()
    action = assess(
        Action("target", "streamer"),
        {p.key: p for p in players},
        replace(tx, **{field: value}),
        rules,
        games,
        origin,
    )
    assert action.status == status
    assert any(reason in message for message in action.reasons)


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("addable", None, "unverified"),
        ("addable", False, "rejected"),
        ("in_ir", True, "rejected"),
        ("in_ir", None, "unverified"),
        ("market", None, "unverified"),
        ("owner", None, "unverified"),
        ("owner", "opponent", "rejected"),
    ],
)
def test_ownership_addability_ir_filter(field, value, status):
    players, tx, rules, games, _, _, origin = fixture_inputs()
    mapping = {p.key: p for p in players}
    mapping["target"] = replace(mapping["target"], **{field: value})
    assert (
        assess(Action("target", "streamer"), mapping, tx, rules, games, origin).status
        == status
    )


def test_lock_protects_drop_and_matching_preserves_assignment():
    players, tx, rules, games, opponent, observed, origin = fixture_inputs()
    rules = replace(rules, locked=(Selection("streamer-1", 0, "F"),))
    result = optimize(players, tx, rules, games, opponent, observed, origin, CONFIG)
    assert result["recommended_action"] == "HOLD"
    assert "locked" in " ".join(filtered(result, "ADD:target/DROP:streamer")["reasons"])
    assert {"game_key": "streamer-1", "team": 0, "slot": "F"} in row(result, "HOLD")[
        "active_lineup"
    ]


def test_vacancy_allows_add_without_drop():
    players, tx, rules, games, opponent, observed, origin = fixture_inputs()
    result = optimize(
        players,
        replace(tx, roster_capacity=3),
        rules,
        games,
        opponent,
        observed,
        origin,
        CONFIG,
    )
    assert row(result, "ADD:target/DROP:-")["feasibility"] == "feasible"
    assert len(row(result, "ADD:target/DROP:-")["roster_after"]) == 3


def marginal_inputs():
    players, tx, rules, games, opponent, _, origin = fixture_inputs()
    wanted = {"anchor", "streamer", "target", "opponent-g", "opponent-f"}
    players = tuple(p for p in players if p.key in wanted)
    games = tuple(
        replace(
            g,
            joint_samples=((0,) * 9 + (2, 0),)
            if g.player_key == "target"
            else ((0,) * 11,),
        )
        for g in games
        if g.player_key in wanted and g.game_key.endswith("-1")
    )
    opponent = tuple(s for s in opponent if s.game_key.endswith("-1"))
    observed = ((1, 2, 1, 2, 1, 4, 10, 10, 10, 0, 2), (1, 2, 1, 2, 1, 4, 1, 1, 1, 1, 3))
    return players, tx, rules, games, opponent, observed, origin


def test_one_marginal_category_improves_five_win_objective():
    result = optimize(*marginal_inputs(), config=CONFIG)
    action = row(result, "ADD:target/DROP:streamer")
    assert action["win_probability_before"] == 0
    assert action["win_probability_after"] == 1
    assert action["paired_gain_mc_se"] == 0
    assert action["category_win_deltas"]["BLK"] == 1
    assert sum(action["category_win_deltas"].values()) == 1
    assert result["recommended_action"] == action["action"]


def test_long_term_loss_blocks_positive_current_week_gain_and_missing_value():
    players, tx, rules, games, opponent, observed, origin = marginal_inputs()
    for value in (0.0, None):
        updated = tuple(
            replace(p, long_term_value=value) if p.key == "target" else p
            for p in players
        )
        result = optimize(updated, tx, rules, games, opponent, observed, origin, CONFIG)
        assert result["recommended_action"] == "HOLD"
        action = row(result, "ADD:target/DROP:streamer")
        assert action["matchup_credit_gain"] == 1
        assert action["recommendable"] is False
        assert action["long_term_value_loss"] == (1 if value == 0 else None)
    result = optimize(
        updated,
        tx,
        rules,
        games,
        opponent,
        observed,
        origin,
        replace(CONFIG, max_value_loss=1),
    )
    assert result["recommended_action"] == "HOLD"  # Missing value remains unknown.


def test_transaction_time_remaining_caps_and_completed_games():
    players, tx, rules, games, opponent, observed, origin = fixture_inputs()
    after = ("anchor", "target")
    rules = replace(
        rules, rosters=(after, rules.rosters[1]), remaining_game_caps=(3, 6)
    )
    mapping = {p.key: p for p in players}
    lineups = plan_lineup(
        games,
        rules,
        mapping,
        origin,
        opponent,
        "target",
        origin + timedelta(days=1, hours=20),
    )
    ours = [s for s in lineups if s.team == 0]
    assert len(ours) == 3
    assert "target-1" not in {s.game_key for s in ours}
    assert "target-2" in {s.game_key for s in ours}
    assert (
        len({s.slot for s in ours}) == 2
        or len({s.game_key.split("-")[-1] for s in ours}) == 2
    )
    later = origin + timedelta(days=1, hours=22)
    lineups = plan_lineup(games, rules, mapping, later, opponent, "target", later)
    assert all(not s.game_key.endswith("-1") for s in lineups if s.team == 0)


def test_daily_matching_reassigns_flexible_player_to_free_slot():
    players, _, rules, games, opponent, _, origin = fixture_inputs()
    players = tuple(
        replace(p, eligible_slots=("G", "F")) if p.key == "anchor" else p
        for p in players
    )
    games = tuple(
        replace(g, eligible_slots=("G", "F")) if g.player_key == "anchor" else g
        for g in games
    )
    lineups = plan_lineup(
        games, rules, {p.key: p for p in players}, origin, opponent, None, None
    )
    assert sum(s.team == 0 for s in lineups) == 6
    assert all(s.slot == "F" for s in lineups if s.game_key.startswith("streamer-"))


@pytest.mark.parametrize("future", ["player_observed", "player_ingested", "settings"])
def test_no_later_known_snapshots(future):
    players, tx, rules, games, opponent, observed, origin = fixture_inputs()
    later = origin + timedelta(days=1)
    if future == "settings":
        tx = replace(tx, observed_at=later, ingested_at=later)
    else:
        change = (
            {"observed_at": later, "ingested_at": later}
            if future == "player_observed"
            else {"ingested_at": later}
        )
        players = (replace(players[0], **change),) + players[1:]
    with pytest.raises(ValueError, match="known at as_of"):
        optimize(players, tx, rules, games, opponent, observed, origin, CONFIG)


def test_unverified_live_adapter_never_fabricates_settings():
    players, _, rules, games, opponent, observed, origin = fixture_inputs()
    result = optimize(
        players,
        yahoo_constraints_unverified(origin),
        rules,
        games,
        opponent,
        observed,
        origin,
        CONFIG,
    )
    assert result["recommended_action"] == "HOLD"
    assert result["ranked_actions"] == []
    assert all(
        a["feasibility"] in ("unverified", "rejected")
        for a in result["filtered_actions"]
    )


def test_reproducibility_input_order_backend_and_paired_precision():
    players, tx, rules, games, opponent, observed, origin = fixture_inputs()
    first = optimize(players, tx, rules, games, opponent, observed, origin, CONFIG)
    second = optimize(
        players[::-1], tx, rules, games[::-1], opponent[::-1], observed, origin, CONFIG
    )
    assert first == second
    reference = optimize(
        players,
        tx,
        rules,
        games,
        opponent,
        observed,
        origin,
        replace(CONFIG, backend="python"),
    )
    assert first["ranked_actions"] == reference["ranked_actions"]
    assert first["scenario_hash"] == reference["scenario_hash"]
    best = row(first, "ADD:target/DROP:streamer")
    p = best["matchup_credit_gain"]
    assert best["paired_gain_mc_se"] == pytest.approx(np.sqrt(p * (1 - p) / (512 - 1)))


def test_cli_fixture_gate_repeated_seed_and_invalid_config(capsys):
    assert main(["optimize"]) == 1
    assert (
        json.loads(capsys.readouterr().err)["error"] == "live_optimization_unavailable"
    )
    args = [
        "optimize",
        "--fixture",
        "--screening-samples",
        "32",
        "--finalist-samples",
        "64",
    ]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert main(args) == 0
    assert capsys.readouterr().out == first
    assert main(args + ["--finalist-samples", "16"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "optimization_failed"


def test_actual_tie_credit_objective_and_empty_candidate_pool():
    players, tx, rules, games, opponent, _, origin = marginal_inputs()
    rules = replace(rules, scoring="category_majority", matchup_ties="half")
    result = optimize(
        players, tx, rules, games, opponent, ((0,) * 11, (0,) * 11), origin, CONFIG
    )
    best = row(result, "ADD:target/DROP:streamer")
    assert best["matchup_credit_before"] == 0.5
    assert best["matchup_credit_after"] == 1
    assert best["matchup_credit_gain"] == 0.5
    assert best["win_probability_before"] == 0
    assert best["win_probability_after"] == 1
    players = tuple(p for p in players if p.owner != "free")
    result = optimize(
        players, tx, rules, games, opponent, ((0,) * 11, (0,) * 11), origin, CONFIG
    )
    assert [a["action"] for a in result["ranked_actions"]] == ["HOLD"]
    assert result["filtered_actions"] == []


def test_explicit_search_budget_and_ownership_consistency():
    inputs = fixture_inputs()
    with pytest.raises(ValueError, match="search budget"):
        optimize(*inputs, config=replace(CONFIG, max_actions=1))
    players, tx, rules, games, opponent, observed, origin = inputs
    players = tuple(
        replace(p, owner="free") if p.key == "streamer" else p for p in players
    )
    with pytest.raises(ValueError, match="disagree"):
        optimize(players, tx, rules, games, opponent, observed, origin, CONFIG)


def test_same_day_duplicate_player_games_and_locked_ir_are_unverified():
    players, tx, rules, games, opponent, observed, origin = fixture_inputs()
    extra = replace(
        games[0],
        game_key="anchor-extra",
        starts_at=games[0].starts_at + timedelta(hours=1),
        ends_at=games[0].ends_at + timedelta(hours=1),
    )
    result = optimize(
        players, tx, rules, games + (extra,), opponent, observed, origin, CONFIG
    )
    assert result["ranked_actions"] == []
    rules = replace(rules, locked=(Selection("anchor-1", 0, "G"),))
    players = tuple(replace(p, in_ir=True) if p.key == "anchor" else p for p in players)
    result = optimize(players, tx, rules, games, opponent, observed, origin, CONFIG)
    assert result["ranked_actions"] == []


def test_sample_screening_refines_close_finalists_and_explicit_value_policy():
    players, tx, rules, games, opponent, observed, origin = fixture_inputs()
    players = tuple(
        replace(p, long_term_value=2) if p.key == "bad-target" else p for p in players
    )
    narrow = optimize(players, tx, rules, games, opponent, observed, origin, CONFIG)
    wide = optimize(
        players,
        tx,
        rules,
        games,
        opponent,
        observed,
        origin,
        replace(CONFIG, close_margin=1),
    )
    assert narrow["refined_actions"] == 2
    assert wide["refined_actions"] == 3
    assert narrow["recommended_action"] == wide["recommended_action"]
    assert row(wide, "ADD:bad-target/DROP:streamer")["samples"] == 512
    players, tx, rules, games, opponent, observed, origin = marginal_inputs()
    players = tuple(
        replace(p, long_term_value=0) if p.key == "target" else p for p in players
    )
    allowed = optimize(
        players,
        tx,
        rules,
        games,
        opponent,
        observed,
        origin,
        replace(CONFIG, max_value_loss=1),
    )
    assert allowed["recommended_action"] == "ADD:target/DROP:streamer"
    assert row(allowed, "ADD:target/DROP:streamer")["long_term_value_loss"] == 1
