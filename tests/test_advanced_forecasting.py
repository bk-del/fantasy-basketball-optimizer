"""Temporal, numerical and lifecycle boundaries for actual CPU challengers."""

import copy
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from fantasy_optimizer.advanced_benchmark import promotion_gate, subset
from fantasy_optimizer.advanced_features import (
    FEATURE_NAMES,
    FeatureState,
    counts_from_primitives,
    observations,
    target_components,
)
from fantasy_optimizer.advanced_models import (
    component_primitives,
    feature_columns,
    fit_calibrator,
    fit_model,
    joint_draws,
    predict_model,
)
from fantasy_optimizer.forecasting import STATS, ForecastConfig
from fantasy_optimizer.nba_forecasting import Population
from fantasy_optimizer.registry import Registry, RegistryError
from fantasy_optimizer.storage import timestamp


def histories():
    start = datetime(2024, 11, 1, tzinfo=UTC)
    rows = []
    for day in range(12):
        for player in range(3):
            primitive = np.array(
                [3 + player, 4, day % 3, 2, 2, 1, 5, 4, 1, 1, 2], dtype=float
            )
            rows.append(
                {
                    "player": f"nba:{player + 1}",
                    "id": str(day * 3 + player),
                    "team": player + 1,
                    "season": 2025,
                    "day": start + timedelta(days=day),
                    "end": start + timedelta(days=day + 1),
                    "available": start + timedelta(days=day + 1, hours=12),
                    "primitive": primitive,
                    "counts": counts_from_primitives(primitive),
                    "minutes": 20 + player,
                    "context": [98, 112, 108, 42, 23, 30, 1],
                }
            )
    return rows, start + timedelta(days=9)


def test_lagged_features_ignore_future_targets_and_late_ingestion():
    rows, origin = histories()
    state = FeatureState(rows)
    state.advance(origin)
    before = state.snapshot("nba:1", origin)
    revised = copy.deepcopy(rows)
    for row in revised:
        if row["available"] > origin:
            row["counts"] += 100
            row["primitive"] += 100
            row["context"] = [999] * 7
            row["minutes"] = 70
    other = FeatureState(revised)
    other.advance(origin)
    after = other.snapshot("nba:1", origin)
    assert before["input_hash"] == after["input_hash"]
    assert np.array_equal(before["x"], after["x"])
    known = copy.deepcopy(rows)
    known[0]["context"][0] = 200
    changed = FeatureState(known)
    changed.advance(origin)
    assert changed.snapshot("nba:1", origin)["input_hash"] != before["input_hash"]
    with pytest.raises(ValueError, match="backwards"):
        state.advance(origin - timedelta(seconds=1))
    with pytest.raises(ValueError, match="Advance"):
        state.snapshot("nba:1", origin + timedelta(seconds=1))


def test_population_baseline_equivalence_and_identifier_invariance():
    rows, origin = histories()
    state = FeatureState(rows)
    state.advance(origin)
    records = [{**r, "counts": tuple(int(x) for x in r["counts"])} for r in rows]
    pop = Population(records, origin, ForecastConfig(half_life_days=14))
    for p in state.history:
        snapshot = state.snapshot(p, origin)
        for field, model in [
            ("recency", "recency"),
            ("shrinkage", "shrinkage"),
            ("season_to_date", "long_run"),
        ]:
            expected = pop.predict(p, model, seed=42, samples=32)
            assert snapshot[field] == pytest.approx(
                [expected["expected_counts"][s] for s in STATS]
            )
        assert counts_from_primitives(snapshot["recency_primitive"]) == pytest.approx(
            snapshot["recency"]
        )
    relabel = copy.deepcopy(rows)
    for r in relabel:
        r["player"] = "renamed:" + r["player"]
    renamed = FeatureState(relabel)
    renamed.advance(origin)
    assert renamed.snapshot("renamed:nba:1", origin)["x"] == pytest.approx(
        state.snapshot("nba:1", origin)["x"]
    )


def test_missing_minutes_do_not_become_zero_minute_labels():
    rows, _ = histories()
    row = rows[0]
    row["minutes"] = None
    target, weights = target_components(row)
    assert target[0] == 1 and weights[0] == 1
    assert not weights[1:10].any()
    assert weights[10:].sum() > 0
    row["counts"][:] = 0
    row["primitive"][:] = 0
    target, weights = target_components(row)
    assert target[0] == 0 and weights[0] == 1
    assert not weights[1:].any()


def test_feature_ablations_and_temporal_training_cutoff():
    base = {"features": "full"}
    assert len(feature_columns(base)) == len(FEATURE_NAMES)
    for mode, forbidden in [("no_context", "context_"), ("no_shot_priors", "shot_")]:
        columns = feature_columns({"features": mode})
        assert columns and all(
            not FEATURE_NAMES[i].startswith(forbidden) for i in columns
        )
    data = {
        "cases": [
            {
                "as_of": "2024-12-01T00:00:00Z",
                "outcome_available": "2024-12-03T00:00:00Z",
            },
            {
                "as_of": "2024-12-01T00:00:00Z",
                "outcome_available": "2024-12-02T00:00:00Z",
            },
        ]
    }
    assert subset(data, None, "2024-12-02T12:00:00Z").tolist() == [1]


@pytest.mark.parametrize("kind", ["lightgbm", "torch"])
def test_real_learner_execution_roundtrip_seed_and_training_separation(kind):
    if importlib.util.find_spec(kind) is None:
        pytest.skip("Optional advanced CPU extra not installed.")
    rng = np.random.default_rng(4)
    n = 192
    base = np.tile(
        [0.8, 25, 0.2, 0.1, 0.1, 0.3, 0.2, 0.04, 0.02, 0.08, 0.5, 0.35, 0.75], (n, 1)
    )
    data = {
        "x": rng.normal(size=(n, len(FEATURE_NAMES))),
        "base": base,
        "shot_population": base[:, 10:13],
        "y": base + rng.normal(size=base.shape) * 0.1,
        "weights": np.ones_like(base),
        "recency_primitive": component_primitives(base),
    }
    config = {
        "kind": kind,
        "features": "full",
        "factorized": True,
        "leaves": 7,
        "rounds": 4,
        "hidden": [8, 4],
        "epochs": 3,
        "batch_size": 32,
    }
    indices = np.arange(144)
    first = fit_model(data, indices, config, threads=1)
    changed = copy.deepcopy(data)
    changed["y"][144:] += 100
    changed["x"][144:] += 100
    second = fit_model(changed, indices, config, threads=1)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    restored = json.loads(json.dumps(first))
    a = predict_model(first, data, np.arange(n))
    b = predict_model(restored, data, np.arange(n))
    assert np.array_equal(a["counts"], b["counts"])
    assert (a["primitive"] >= 0).all()
    assert a["counts"][:, 5] == pytest.approx(
        2 * a["counts"][:, 0] + a["counts"][:, 4] + a["counts"][:, 2], abs=1e-12
    )


def test_joint_calibration_moments_shooting_constraints_and_seed():
    rng = np.random.default_rng(5)
    means = np.tile([3, 4, 2, 3, 2, 1, 5, 4, 1, 1, 2], (500, 1)).astype(float)
    factors = rng.choice([0.4, 1, 1.6], size=(500, 1))
    actual = rng.poisson(means * factors).astype(float)
    cases = [
        {"player_key": "nba:1", "minutes_group": "high", "history": 20} for _ in means
    ]
    calibration = fit_calibrator(means, actual, cases)
    assert "high:regular" in calibration["cells"]
    draws = joint_draws(
        means[0], cases[0], calibration, seed=42, samples=20000, stream="test"
    )
    again = joint_draws(
        means[0], cases[0], calibration, seed=42, samples=20000, stream="test"
    )
    assert np.array_equal(draws, again)
    expected = counts_from_primitives(means[0])
    se = draws.std(axis=0) / np.sqrt(len(draws))
    assert (abs(draws.mean(axis=0) - expected) <= 5 * se).all()
    assert (draws[:, 0] <= draws[:, 1]).all() and (draws[:, 4] <= draws[:, 0]).all()
    assert (draws[:, 2] <= draws[:, 3]).all()
    assert np.array_equal(draws[:, 5], 2 * draws[:, 0] + draws[:, 4] + draws[:, 2])
    assert np.corrcoef(draws[:, 5], draws[:, 6])[0, 1] > 0.1


def test_failed_advanced_gate_cannot_promote_or_change_registry(tmp_path):
    registry = Registry(tmp_path / "models.json")

    def entry(kind, score, gate):
        return {
            "kind": kind,
            "scope": "nba_research",
            "model": "recency",
            "code_hash": "code",
            "dataset_watermark": "data",
            "evaluation_hash": "evaluation",
            "selection_metric": "normalized_all_count_mae",
            "validation_score": score,
            "baseline_scores": {"recency": 1.0},
            "promotion_gate": {"passed": gate},
        }

    baseline = registry.register(entry("incumbent", 1, True), max_candidates=3)
    candidate = registry.register(entry("candidate", 0.9, False), max_candidates=3)
    before = registry.path.read_bytes()
    with pytest.raises(RegistryError, match="holdout gate"):
        registry.promote(candidate)
    assert (
        registry.read()["active"] == baseline and registry.path.read_bytes() == before
    )
    approved = registry.register(entry("candidate", 0.8, True), max_candidates=3)
    registry.promote(approved)
    registry.rollback()
    assert registry.read()["active"] == baseline


def test_gate_rejects_high_minute_undercoverage_and_shooting_regression():
    categories = {
        s: {"mae": 1, "interval_score_80": 1, "brier": 0.2, "coverage_80": 0.8}
        for s in [*STATS, "FG%", "FT%"]
    }
    baseline = {"per_category": categories, "segments": {}}
    selected = {
        "per_category": copy.deepcopy(categories),
        "segments": {
            s: {"cases": 200, "per_category": {"PTS": {"coverage_80": 0.8}}}
            for s in ["low", "medium", "high"]
        },
    }
    selected["segments"]["high"]["per_category"]["PTS"]["coverage_80"] = 0.55
    selected["per_category"]["FG%"]["mae"] = 1.1
    protocol = json.loads(
        Path("docs/benchmarks/nba-advanced-protocol.json").read_text()
    )
    result = promotion_gate(
        selected,
        baseline,
        {"normalized_interval_95": [-0.1, -0.01]},
        0.1,
        protocol["promotion_gate"],
    )
    assert not result["passed"] and any("high minute" in r for r in result["reasons"])
    assert any("FG%" in r for r in result["reasons"])


def test_real_source_context_identity_and_strict_retrieval_boundary():
    root = Path("data/nba_data")
    if not (root / "manifest.json").exists():
        pytest.skip("Owner-authorized ignored snapshot unavailable.")
    records, data = observations(root, "strict")
    assert len(records) == 64695 and len({r["player"] for r in records}) == 697
    assert (
        data["unknown_minute_rows"] == 11865
        and data["unknown_minutes_nonzero_rows"] == 125
    )
    origin = timestamp(data["retrieved_at"])
    state = FeatureState(records)
    state.advance(origin - timedelta(seconds=1))
    assert not state.history
    state.advance(origin)
    assert sum(len(h) for h in state.history.values()) == 64695
    for p in ["nba:2544", "nba:201143", "nba:201145"]:
        feature = state.snapshot(p, origin)
        assert feature["history"] > 1 and np.isfinite(feature["x"]).all()
        assert feature["latest"] == max(r["end"] for r in state.history[p]).isoformat()


def test_advanced_cli_requires_explicit_fixture(capsys):
    from fantasy_optimizer.cli import main

    assert main(["advanced", "run"]) == 1
    output = capsys.readouterr()
    assert "Use --fixture" in output.err


def test_actual_frozen_challenger_native_reference_cache_and_read_only(tmp_path):
    from fantasy_optimizer.advanced_benchmark import advanced_code_hash
    from fantasy_optimizer.advanced_pipeline import run
    from fantasy_optimizer.optimization import SearchConfig

    report_path = Path("docs/benchmarks/nba-advanced.json")
    if not report_path.exists() or not Path("data/nba_data/manifest.json").exists():
        pytest.skip("Ignored real source or frozen advanced artifacts unavailable.")
    report = json.loads(report_path.read_text())
    label = report["selected"]
    if not Path(report["models"][label]["path"]).exists():
        pytest.skip("Ignored fitted learner unavailable.")
    registry = Registry(tmp_path / "research-model.json")
    registry.register(
        {
            "kind": "incumbent",
            "scope": "nba_research",
            "model": "lightgbm",
            "learner_label": label,
            "code_hash": advanced_code_hash(),
            "dataset_watermark": report["data"]["source_hash"],
            "training_cutoff": report["protocol"]["fit_end"],
            "selection_cutoff": report["protocol"]["calibration_end"],
            "learner_artifact": report["models"][label],
            "calibration_artifact": report["calibration"][label]["artifact"],
        },
        max_candidates=1,
    )
    baseline = Registry(Path("models/nba-registry.json"))
    before = registry.path.read_bytes()
    original = baseline.path.read_bytes()
    origin = timestamp("2026-10-13T03:40:00Z")
    results = []
    for backend in ["cpp", "python", "cpp"]:
        results.append(
            run(
                Path("data/nba_data"),
                registry,
                baseline,
                tmp_path / "runs",
                origin,
                config=SearchConfig(
                    backend=backend, screening_samples=64, finalist_samples=512
                ),
            )
        )
    assert (
        results[0]["report"]["optimization"]["ranked_actions"]
        == results[1]["report"]["optimization"]["ranked_actions"]
    )
    assert results[0]["report"] == results[2]["report"]
    assert results[2]["forecast_cache_hit"] and results[2]["decision_cache_hit"]
    assert not results[0]["report"]["live_yahoo_recommendation"]
    assert any(
        a["action"] == "HOLD"
        for a in results[0]["report"]["optimization"]["ranked_actions"]
    )
    assert (
        registry.path.read_bytes() == before and baseline.path.read_bytes() == original
    )
