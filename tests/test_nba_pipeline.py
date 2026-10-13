"""Real-data connection boundaries and scalar/reference equivalence."""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from fantasy_optimizer.forecast_fixture import fixture_history
from fantasy_optimizer.forecasting import STATS, ForecastConfig, forecast, known_windows
from fantasy_optimizer.nba_forecasting import (
    Population,
    game_records,
    load_games,
    minutes_value,
)
from fantasy_optimizer.simulation import validate_counts


def weekly_records():
    windows, origin = fixture_history()
    return (
        [
            {
                "player": w.player_key,
                "id": w.start.isoformat(),
                "counts": w.counts,
                "end": w.end,
                "available": w.ingested_at,
            }
            for w in known_windows(windows, origin)
        ],
        windows,
        origin,
    )


@pytest.mark.parametrize("model", ("long_run", "recency", "shrinkage"))
def test_population_matches_existing_engine(model):
    records, windows, origin = weekly_records()
    population = Population(records, origin, ForecastConfig())
    for player in population.players:
        expected = forecast(windows, player, origin, model=model, samples=32)
        actual = population.predict(player, model, seed=42, samples=32)
        assert actual["expected_counts"] == pytest.approx(expected.expected_counts)
        assert actual["prior_strength"] == pytest.approx(
            expected.feature_snapshot["prior_strength"]
        )
        for sample in actual["joint_samples"]:
            validate_counts(tuple(sample[s] for s in STATS))


def test_no_future_peer_or_late_ingestion_and_sparse_prior():
    records, _, origin = weekly_records()
    one = next(iter(records))["player"]
    filtered = [r for r in records if r["player"] != one] + [
        next(r for r in records if r["player"] == one)
    ]
    baseline = Population(filtered, origin, ForecastConfig()).predict(
        one, "shrinkage", seed=42, samples=256
    )
    revised = [
        *filtered,
        {
            **records[0],
            "available": origin + timedelta(seconds=1),
            "counts": (100, 200, 100, 200, 50, 350, 100, 100, 100, 100, 100),
        },
    ]
    assert (
        Population(revised, origin, ForecastConfig()).predict(
            one, "shrinkage", seed=42, samples=256
        )
        == baseline
    )
    assert baseline["history_observations"] == 1
    assert 0 < baseline["own_weight"] < 1
    assert (
        Population(list(reversed(filtered)), origin, ForecastConfig()).predict(
            one, "shrinkage", seed=42, samples=256
        )
        == baseline
    )


def test_stale_support_does_not_underflow():
    records, _, origin = weekly_records()
    pop = Population(
        records, origin + timedelta(days=100000), ForecastConfig(half_life_days=1)
    )
    p = pop.predict(pop.players[0], "recency", seed=42, samples=32)
    assert np.isfinite(list(p["expected_counts"].values())).all()


def test_minutes_strict_interpretation():
    assert minutes_value("29:30") == 29.5
    assert minutes_value("") is None
    assert minutes_value("DNP") is None
    assert minutes_value("20:75") is None
    assert minutes_value("nan") is None


def test_real_games_full_population_and_strict_boundary():
    root = Path("data/nba_data")
    if not (root / "manifest.json").exists():
        pytest.skip("Owner-authorized ignored NBA snapshot unavailable.")
    games, data = load_games(root)
    assert len(games) == 64695
    assert len({g.nba_player_id for g in games}) > 591
    origin = datetime.fromisoformat(data["retrieved_at"])
    records = game_records(games, "strict")
    assert not Population(
        records, origin - timedelta(seconds=1), ForecastConfig()
    ).players
    population = Population(records, origin, ForecastConfig())
    assert sum(len(g) for g in population.groups.values()) == 64695
    assert len(population.players) > 591


def test_actual_forecast_native_reference_moments_and_optimizer():
    from fantasy_optimizer.nba_pipeline import FIXTURE_IDS, league_inputs
    from fantasy_optimizer.optimization import SearchConfig, optimize
    from fantasy_optimizer.simulation import (
        Selection,
        evaluate_scenarios,
        prepare,
        sample_scenarios,
    )

    root = Path("data/nba_data")
    if not (root / "manifest.json").exists():
        pytest.skip("Owner-authorized ignored NBA snapshot unavailable.")
    games, data = load_games(root)
    origin = datetime.fromisoformat(data["retrieved_at"])
    population = Population(game_records(games, "strict"), origin, ForecastConfig())
    predictions = {
        f"nba:{p}": population.predict(f"nba:{p}", "recency", seed=42, samples=256)
        for p in FIXTURE_IDS.values()
    }
    for p in predictions.values():
        p["model_id"] = "actual-nba-test-config"
    inputs = league_inputs(predictions, origin)
    rules, forecasts, observed = inputs[2], inputs[3], inputs[5]
    selected = tuple(
        Selection(
            g.game_key,
            0 if g.player_key in rules.rosters[0] else 1,
            g.eligible_slots[0],
        )
        for g in forecasts
        if g.player_key in rules.rosters[0] + rules.rosters[1]
    )
    bank = sample_scenarios(forecasts, seed=42, scenarios=10000)
    assert np.array_equal(
        bank.values, sample_scenarios(forecasts, seed=42, scenarios=10000).values
    )
    values, teams, totals = prepare(forecasts, bank, selected, rules, origin, observed)
    py = evaluate_scenarios(
        forecasts, bank, selected, rules, origin, observed, backend="python"
    )
    cpp = evaluate_scenarios(
        forecasts, bank, selected, rules, origin, observed, backend="cpp"
    )
    for a, b in zip(py, cpp, strict=True):
        assert np.array_equal(a, b)
    for i, g in enumerate(sorted(forecasts, key=lambda g: g.game_key)):
        reference = np.array(g.joint_samples)
        measured = bank.values[:, i, :].mean(axis=0)
        se = reference.std(axis=0) / 100
        assert (abs(measured - reference.mean(axis=0)) <= 5 * se + 1e-10).all()
        # Makes/attempts/PTS move jointly through sampling and aggregate arithmetic.
        assert np.array_equal(
            bank.values[:, i, 5],
            2 * bank.values[:, i, 0] + bank.values[:, i, 4] + bank.values[:, i, 2],
        )
    native = optimize(
        *inputs,
        config=SearchConfig(finalist_samples=512, screening_samples=64, backend="cpp"),
    )
    reference = optimize(
        *inputs,
        config=SearchConfig(
            finalist_samples=512, screening_samples=64, backend="python"
        ),
    )
    assert native["recommended_action"] == reference["recommended_action"]
    assert native["ranked_actions"] == reference["ranked_actions"]
    assert any(a["action"] == "HOLD" for a in native["ranked_actions"])


def test_nba_all_count_promotion_and_rollback(tmp_path):
    from fantasy_optimizer.registry import Registry, RegistryError

    registry = Registry(tmp_path / "registry.json")

    def record(kind, score):
        return {
            "kind": kind,
            "scope": "nba_research",
            "model": "recency",
            "selection_metric": "normalized_all_count_mae",
            "validation_score": score,
            "baseline_scores": {"season": 0.9, "recency": 0.8},
            "dataset_watermark": "test-data",
            "evaluation_hash": "test-period",
        }

    first = registry.register(record("incumbent", 0.8), max_candidates=3)
    worse = registry.register(record("candidate", 0.85), max_candidates=3)
    with pytest.raises(RegistryError, match="all-count"):
        registry.promote(worse)
    better = registry.register(record("candidate", 0.7), max_candidates=3)
    registry.promote(better)
    assert registry.read()["active"] == better
    registry.rollback()
    assert registry.read()["active"] == first


def test_real_pipeline_cache_read_only_registry_and_live_gate(tmp_path, monkeypatch):
    from fantasy_optimizer import nba_pipeline
    from fantasy_optimizer.cli import main
    from fantasy_optimizer.nba_forecasting import VERSION, code_hash
    from fantasy_optimizer.optimization import SearchConfig
    from fantasy_optimizer.registry import Registry

    root = Path("data/nba_data")
    if not (root / "manifest.json").exists():
        pytest.skip("Owner-authorized ignored NBA snapshot unavailable.")
    games, data = load_games(root)
    origin = datetime.fromisoformat(data["retrieved_at"])
    registry = Registry(tmp_path / "nba.json")
    # Handmade lifecycle metadata tests cache mechanics only; forecast inputs real.
    registry.register(
        {
            "kind": "incumbent",
            "scope": "nba_research",
            "model": "recency",
            "model_version": VERSION,
            "code_hash": code_hash(),
            "config": {"half_life_days": 28},
            "training_cutoff": origin.isoformat(),
            "selection_cutoff": origin.isoformat(),
            "calibration": dict.fromkeys(STATS),
        },
        max_candidates=1,
    )
    original = registry.path.read_bytes()
    first = nba_pipeline.run(
        root,
        registry,
        tmp_path / "out",
        origin,
        config=SearchConfig(finalist_samples=64, screening_samples=32),
        samples=32,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Cached model inference/optimization should be skipped.")

    monkeypatch.setattr(Population, "predict", forbidden)
    monkeypatch.setattr(nba_pipeline, "optimize", forbidden)
    second = nba_pipeline.run(
        root,
        registry,
        tmp_path / "out",
        origin,
        config=SearchConfig(finalist_samples=64, screening_samples=32),
        samples=32,
    )
    assert first["report"] == second["report"]
    assert second["forecast_cache_hit"] and second["decision_cache_hit"]
    assert registry.path.read_bytes() == original
    assert first["report"]["live_yahoo_recommendation"] is False
    assert main(["nba", "run", "--registry", str(registry.path)]) == 1
