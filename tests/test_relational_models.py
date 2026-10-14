"""Real compact fits verify temporal separation, masking and learned messages."""

import copy
import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from fantasy_optimizer.relational_models import fit_relational, predict_relational


def dataset():
    rng = np.random.default_rng(3)
    n = 72
    start = datetime(2024, 1, 1, tzinfo=UTC)
    base = np.tile([0.9, 25, *([0.12] * 8), 0.5, 0.35, 0.8], (n, 1))
    x = rng.normal(size=(n, 6))
    seq = rng.normal(size=(n, 8, 13))
    neighbors = rng.normal(size=(n, 4, 13))
    mask = np.ones((n, 4))
    mask[:, 3] = 0
    mask[::3, :] = 0
    y = base.copy()
    y[:, 1] += x[:, 0] * 2 + seq[:, -1, 0] + neighbors[:, 0, 0] * mask[:, 0]
    return {
        "x": x,
        "node": rng.normal(size=(n, 13)),
        "sequence": seq,
        "sequence_mask": np.tile([0, 0, 1, 1, 1, 1, 1, 1], (n, 1)).astype(float),
        "neighbors": neighbors,
        "neighbor_mask": mask,
        "base": base,
        "y": y,
        "weights": np.ones_like(y),
        "cases": [
            {
                "as_of": (start + timedelta(days=i)).isoformat(),
                "outcome_available": (start + timedelta(days=i, hours=12)).isoformat(),
            }
            for i in range(n)
        ],
    }


@pytest.mark.parametrize("kind", ["gru", "graph", "mlp"])
def test_real_fit_json_roundtrip_determinism_and_count_arithmetic(kind):
    data = dataset()
    config = {"kind": kind, "hidden": 8, "epochs": 5, "patience": 2, "batch_size": 16}
    artifact = fit_relational(
        data, np.arange(48), config, validation_indices=np.arange(48, 60)
    )
    restored = json.loads(json.dumps(artifact, allow_nan=False))
    repeated = fit_relational(
        data, np.arange(48), config, validation_indices=np.arange(48, 60)
    )
    assert restored == repeated
    assert artifact["parameter_count"] > 100
    assert artifact["maximum_gradient_norm_before_clip"] > 0
    assert artifact["best_epoch"] <= artifact["epochs_run"] <= 5
    assert artifact["validation_loss"] == min(
        h["validation"] for h in artifact["history"]
    )
    # Inference must operate without labels or outcome metadata.
    no_labels = {k: v for k, v in data.items() if k not in {"y", "weights", "cases"}}
    predictions = predict_relational(restored, no_labels, np.arange(60, 72))
    expected = predict_relational(artifact, data, np.arange(60, 72))
    for key in predictions:
        np.testing.assert_array_equal(predictions[key], expected[key])
    counts = predictions["counts"]
    assert np.isfinite(counts).all() and (counts >= 0).all()
    assert (counts[:, 0] <= counts[:, 1]).all()
    assert (counts[:, 2] <= counts[:, 3]).all()
    assert (counts[:, 4] <= counts[:, 0]).all()
    np.testing.assert_allclose(
        counts[:, 5], 2 * counts[:, 0] + counts[:, 4] + counts[:, 2]
    )
    assert predict_relational(restored, no_labels, np.array([], dtype=int))[
        "counts"
    ].shape == (0, 11)


@pytest.mark.parametrize("kind", ["gru", "graph"])
def test_masks_ignore_padding_and_graph_is_permutation_invariant(kind):
    data = dataset()
    artifact = fit_relational(
        data, np.arange(60), {"kind": kind, "hidden": 8, "epochs": 5}
    )
    before = predict_relational(artifact, data, np.arange(60, 72))
    changed = copy.deepcopy(data)
    if kind == "gru":
        changed["sequence"][changed["sequence_mask"] == 0] = 1e6
    else:
        changed["neighbors"][changed["neighbor_mask"] == 0] = 1e6
        changed["neighbors"] = changed["neighbors"][:, ::-1].copy()
        changed["neighbor_mask"] = changed["neighbor_mask"][:, ::-1].copy()
    after = predict_relational(artifact, changed, np.arange(60, 72))
    np.testing.assert_allclose(before["components"], after["components"], atol=1e-7)
    # Actual learned sequence/message branch must influence the result.
    if kind == "gru":
        changed["sequence"][:] = 15
    else:
        changed["neighbors"][:] = 15
    altered = predict_relational(artifact, changed, np.arange(60, 72))
    assert not np.allclose(before["components"], altered["components"])


def test_training_scalers_never_read_validation_or_future_and_reject_bad_split():
    data = dataset()
    config = {"kind": "graph", "hidden": 8, "epochs": 2}
    first = fit_relational(
        data, np.arange(48), config, validation_indices=np.arange(48, 60)
    )
    changed = copy.deepcopy(data)
    for key in ("x", "node", "neighbors", "y", "base"):
        changed[key][60:] = 1e5
    second = fit_relational(
        changed, np.arange(48), config, validation_indices=np.arange(48, 60)
    )
    assert first == second
    np.testing.assert_allclose(
        first["scalers"]["x"]["mean"], data["x"][:48].mean(axis=0)
    )
    with pytest.raises(ValueError, match="overlap"):
        fit_relational(
            data, np.arange(48), config, validation_indices=np.arange(47, 60)
        )
    with pytest.raises(ValueError, match="precede"):
        fit_relational(
            data, np.arange(12, 60), config, validation_indices=np.arange(12)
        )
    changed = copy.deepcopy(data)
    changed["cases"][47]["outcome_available"] = data["cases"][49]["as_of"]
    with pytest.raises(ValueError, match="precede"):
        fit_relational(
            changed, np.arange(48), config, validation_indices=np.arange(48, 60)
        )


def test_automatic_tail_keeps_whole_origin_groups_and_purges_late_labels():
    data = dataset()
    for i in range(72):
        data["cases"][i] = copy.deepcopy(data["cases"][i // 4 * 4])
    # The split boundary lies within a shared origin; every case at it validates.
    artifact = fit_relational(data, np.arange(60), {"kind": "mlp", "epochs": 1})
    assert artifact["training_cases"] == 48
    assert artifact["validation_cases"] == 12
    assert artifact["temporal_metadata_checked"]
    data["cases"][47]["outcome_available"] = data["cases"][52]["as_of"]
    artifact = fit_relational(data, np.arange(60), {"kind": "mlp", "epochs": 1})
    assert artifact["training_cases"] == 47


def test_nonfinite_features_negative_weights_and_invalid_masks_refuse():
    data = dataset()
    config = {"kind": "gru", "epochs": 1}
    data["sequence_mask"][0, 0] = 0.5
    with pytest.raises(ValueError, match="binary"):
        fit_relational(data, np.arange(60), config)
    data["sequence_mask"][0, 0] = 1
    data["sequence"][0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="Nonfinite"):
        fit_relational(data, np.arange(60), config)
    data["sequence"][0, 0, 0] = 0
    data["weights"][0, 0] = -1
    with pytest.raises(ValueError, match="negative"):
        fit_relational(data, np.arange(60), config)
