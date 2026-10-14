"""Bounded CPU residual learners over strictly lagged sequences and teammate graphs.

The graph is a one-hop GraphSAGE mean aggregator, not an injury/active-roster
model. Its caller owns point-in-time node/edge construction and provenance.
"""

import importlib
from typing import Any

import numpy as np

from fantasy_optimizer.advanced_features import Array, counts_from_primitives
from fantasy_optimizer.advanced_models import component_primitives
from fantasy_optimizer.storage import timestamp


def _config(config: dict[str, Any]) -> dict[str, Any]:
    result = {
        "hidden": 32,
        "epochs": 20,
        "patience": 3,
        "batch_size": 256,
        "learning_rate": 0.001,
        "weight_decay": 0.01,
        "gradient_clip": 5.0,
        **config,
    }
    if result.get("kind") not in {"gru", "graph", "mlp"}:
        raise ValueError("Expected kind gru, graph or mlp.")
    for name in ("hidden", "epochs", "patience", "batch_size"):
        if not isinstance(result[name], int) or result[name] < 1:
            raise ValueError(f"Positive integer {name} required.")
    for name in ("learning_rate", "weight_decay", "gradient_clip"):
        if not np.isfinite(result[name]) or result[name] < 0:
            raise ValueError(f"Finite nonnegative {name} required.")
    if result["learning_rate"] == 0 or result["gradient_clip"] == 0:
        raise ValueError("Learning rate and gradient clip must be positive.")
    return result


def _indices(indices: Any, size: int) -> Any:
    values = np.asarray(indices)
    if values.ndim != 1 or values.dtype.kind not in "iu":
        raise ValueError("Indices must be a one-dimensional integer array.")
    if len(np.unique(values)) != len(values) or np.any(values < 0):
        raise ValueError("Indices must be unique and nonnegative.")
    if np.any(values >= size):
        raise ValueError("Index outside dataset.")
    return values


def _split(
    data: dict[str, Any], indices: Any, validation_indices: Any
) -> tuple[Any, Any]:
    train = _indices(indices, len(data["x"]))
    if len(train) < 4:
        raise ValueError("At least four fitting cases required.")
    cases = data.get("cases")
    if validation_indices is None:
        if cases is not None:
            train = np.asarray(
                sorted(train, key=lambda i: timestamp(cases[i]["as_of"]))
            )
            cutoff = timestamp(cases[train[max(1, int(len(train) * 0.85))]]["as_of"])
            valid = np.asarray(
                [i for i in train if timestamp(cases[i]["as_of"]) >= cutoff],
                dtype=int,
            )
            train = np.asarray(
                [
                    i
                    for i in train
                    if timestamp(cases[i]["as_of"]) < cutoff
                    and timestamp(cases[i]["outcome_available"]) <= cutoff
                ],
                dtype=int,
            )
        else:
            boundary = max(1, int(len(train) * 0.85))
            train, valid = train[:boundary], train[boundary:]
    else:
        valid = _indices(validation_indices, len(data["x"]))
    if not len(train) or not len(valid):
        raise ValueError("Nonempty chronological fitting and validation sets required.")
    if np.intersect1d(train, valid).size:
        raise ValueError("Fitting and validation indices overlap.")
    if cases is not None:
        first_validation = min(timestamp(cases[i]["as_of"]) for i in valid)
        if any(
            timestamp(cases[i]["as_of"]) >= first_validation
            or timestamp(cases[i]["outcome_available"]) > first_validation
            for i in train
        ):
            raise ValueError("Fitting origins/labels must precede validation origins.")
    return train, valid


def _raw_inputs(data: dict[str, Any], indices: Any, kind: str) -> dict[str, Array]:
    names = ["x"]
    if kind == "gru":
        names += ["sequence", "sequence_mask"]
    if kind == "graph":
        names += ["node", "neighbors", "neighbor_mask"]
    inputs = {k: np.asarray(data[k][indices], dtype=float) for k in names}
    x = inputs["x"]
    if x.ndim != 2 or not x.shape[1]:
        raise ValueError("Tabular inputs must have shape [N,F].")
    if any(not np.isfinite(v).all() for v in inputs.values()):
        raise ValueError("Nonfinite relational features.")
    if kind == "gru":
        seq, mask = inputs["sequence"], inputs["sequence_mask"]
        if seq.ndim != 3 or mask.shape != seq.shape[:2] or not seq.shape[1]:
            raise ValueError("Sequence/mask shapes must be [N,T,F] and [N,T].")
    if kind == "graph":
        node, neighbors, mask = (
            inputs["node"],
            inputs["neighbors"],
            inputs["neighbor_mask"],
        )
        if (
            node.ndim != 2
            or neighbors.ndim != 3
            or mask.shape != neighbors.shape[:2]
            or node.shape[1] != neighbors.shape[2]
        ):
            raise ValueError("Own and neighbor node feature dimensions must match.")
    for name in ("sequence_mask", "neighbor_mask"):
        if name in inputs and not np.isin(inputs[name], [0, 1]).all():
            raise ValueError("Masks must be binary.")
    return inputs


def _scalers(inputs: dict[str, Array], kind: str) -> dict[str, Any]:
    values = {"x": inputs["x"]}
    if kind == "gru":
        values["sequence"] = inputs["sequence"][inputs["sequence_mask"] > 0]
    if kind == "graph":
        values["node"] = np.concatenate(
            [inputs["node"], inputs["neighbors"][inputs["neighbor_mask"] > 0]]
        )
    result = {}
    for name, rows in values.items():
        if not len(rows):
            result[name] = {
                "mean": [0.0] * rows.shape[1],
                "scale": [1.0] * rows.shape[1],
            }
        else:
            result[name] = {
                "mean": rows.mean(axis=0).tolist(),
                "scale": np.maximum(rows.std(axis=0), 1e-3).tolist(),
            }
    return result


def _tensors(torch: Any, inputs: dict[str, Array], scalers: dict[str, Any]) -> Any:
    result = {}
    for name, values in inputs.items():
        if not name.endswith("mask"):
            scaler = scalers["node" if name == "neighbors" else name]
            values = np.clip(
                (values - np.asarray(scaler["mean"])) / np.asarray(scaler["scale"]),
                -20,
                20,
            )
        result[name] = torch.tensor(values, dtype=torch.float32)
    return result


def _network(torch: Any, config: dict[str, Any], dimensions: dict[str, int]) -> Any:
    h = config["hidden"]
    parts = {
        "tabular": torch.nn.Sequential(
            torch.nn.Linear(dimensions["x"], h), torch.nn.ReLU()
        )
    }
    if config["kind"] == "gru":
        parts["temporal"] = torch.nn.GRUCell(dimensions["sequence"], h)
    if config["kind"] == "graph":
        parts["node"] = torch.nn.Sequential(
            torch.nn.Linear(dimensions["node"], h), torch.nn.ReLU()
        )
        parts["message"] = torch.nn.Sequential(
            torch.nn.Linear(2 * h, h), torch.nn.ReLU()
        )
    parts["head"] = torch.nn.Sequential(
        torch.nn.Linear(h if config["kind"] == "mlp" else 2 * h, h),
        torch.nn.ReLU(),
        torch.nn.Linear(h, 13),
    )
    torch.nn.init.zeros_(parts["head"][-1].weight)
    torch.nn.init.zeros_(parts["head"][-1].bias)
    return torch.nn.ModuleDict(parts)


def _forward(torch: Any, net: Any, inputs: Any, kind: str) -> Any:
    own = net["tabular"](inputs["x"])
    if kind == "gru":
        state = torch.zeros_like(own)
        for t in range(inputs["sequence"].shape[1]):
            update = net["temporal"](inputs["sequence"][:, t], state)
            state = torch.where(inputs["sequence_mask"][:, t, None] > 0, update, state)
        own = torch.cat([own, state], dim=1)
    if kind == "graph":
        # Shared node transform and learned self/mean-neighbor update are one
        # genuine inductive message-passing layer; padding contributes no mass.
        encoded = net["node"](inputs["neighbors"])
        mask = inputs["neighbor_mask"][:, :, None]
        aggregate = (encoded * mask).sum(1) / mask.sum(1).clamp(min=1)
        state = net["message"](
            torch.cat([net["node"](inputs["node"]), aggregate], dim=1)
        )
        own = torch.cat([own, state], dim=1)
    return net["head"](own)


def fit_relational(
    data: dict[str, Any],
    indices: Any,
    config: dict[str, Any],
    *,
    validation_indices: Any = None,
    seed: int = 42,
    threads: int = 2,
) -> dict[str, Any]:
    """Fit masked residual heads; the validation tail never fits scalers/gradients.

    With ``cases``, origin and outcome-availability boundaries are checked. Without
    metadata, callers must supply chronologically ordered indices themselves.
    """
    config = _config(config)
    if threads < 1:
        raise ValueError("Positive CPU thread count required.")
    train, valid = _split(data, indices, validation_indices)
    kind = config["kind"]
    raw = _raw_inputs(data, train, kind)
    validation = _raw_inputs(data, valid, kind)
    scalers = _scalers(raw, kind)
    dimensions = {k: len(v["mean"]) for k, v in scalers.items()}
    target = np.asarray(data["y"][train]) - np.asarray(data["base"][train])
    validation_target = np.asarray(data["y"][valid]) - np.asarray(data["base"][valid])
    weights = np.asarray(data["weights"][train])
    validation_weights = np.asarray(data["weights"][valid])
    for values in (target, validation_target, weights, validation_weights):
        if values.ndim != 2 or values.shape[1] != 13 or not np.isfinite(values).all():
            raise ValueError("Finite [N,13] component targets/weights required.")
    if (weights < 0).any() or (validation_weights < 0).any():
        raise ValueError("Loss weights cannot be negative.")
    if not weights.any() or not validation_weights.any():
        raise ValueError("Observed targets required in fitting and validation.")
    scale = np.maximum(
        np.sqrt((weights * target**2).sum(0) / np.maximum(weights.sum(0), 1)), 1e-3
    )
    torch = importlib.import_module("torch")
    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    tx, vx = _tensors(torch, raw, scalers), _tensors(torch, validation, scalers)
    ty = torch.tensor(target / scale, dtype=torch.float32)
    vy = torch.tensor(validation_target / scale, dtype=torch.float32)
    tw = torch.tensor(
        weights * len(train) / np.maximum(weights.sum(0), 1), dtype=torch.float32
    )
    vw = torch.tensor(
        validation_weights * len(valid) / np.maximum(validation_weights.sum(0), 1),
        dtype=torch.float32,
    )
    net = _network(torch, config, dimensions)
    optimizer = torch.optim.AdamW(
        net.parameters(),
        lr=config["learning_rate"],
        weight_decay=config["weight_decay"],
    )
    generator = torch.Generator().manual_seed(seed)
    best_loss = float("inf")
    best_state: dict[str, Any] = {}
    best_epoch, stale, max_gradient = 0, 0, 0.0
    history = []
    for epoch in range(config["epochs"]):
        net.train()
        total_loss = 0.0
        for batch in torch.randperm(len(train), generator=generator).split(
            config["batch_size"]
        ):
            optimizer.zero_grad(set_to_none=True)
            output = _forward(torch, net, {k: v[batch] for k, v in tx.items()}, kind)
            loss = (((output - ty[batch]) ** 2) * tw[batch]).mean()
            if not bool(torch.isfinite(loss)):
                raise ValueError("Nonfinite relational training loss.")
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(
                net.parameters(), config["gradient_clip"], error_if_nonfinite=True
            )
            max_gradient = max(max_gradient, float(norm))
            optimizer.step()
            total_loss += float(loss.detach()) * len(batch)
        net.eval()
        with torch.inference_mode():
            validation_loss = float(
                (((_forward(torch, net, vx, kind) - vy) ** 2) * vw).mean()
            )
        if not np.isfinite(validation_loss):
            raise ValueError("Nonfinite relational validation loss.")
        history.append(
            {
                "epoch": epoch + 1,
                "train": total_loss / len(train),
                "validation": validation_loss,
            }
        )
        if validation_loss < best_loss - 1e-7:
            best_loss, best_epoch, stale = validation_loss, epoch + 1, 0
            best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
        else:
            stale += 1
        if stale >= config["patience"]:
            break
    return {
        "version": "relational-residual-v1",
        "config": config,
        "scalers": scalers,
        "dimensions": dimensions,
        "weights": {k: v.cpu().numpy().tolist() for k, v in best_state.items()},
        "target_scale": scale.tolist(),
        "training_cases": len(train),
        "validation_cases": len(valid),
        "temporal_metadata_checked": data.get("cases") is not None,
        "best_epoch": best_epoch,
        "epochs_run": len(history),
        "validation_loss": best_loss,
        "history": history,
        "maximum_gradient_norm_before_clip": max_gradient,
        "parameter_count": sum(p.numel() for p in net.parameters()),
        "seed": seed,
        "threads": threads,
        "library_version": torch.__version__,
    }


def predict_relational(
    artifact: dict[str, Any], data: dict[str, Any], indices: Any
) -> dict[str, Array]:
    """Infer constrained raw counts without inspecting any labels or case metadata."""
    selected = _indices(indices, len(data["x"]))
    config = artifact["config"]
    inputs = _raw_inputs(data, selected, config["kind"])
    base = np.asarray(data["base"][selected], dtype=float)
    if base.shape != (len(selected), 13) or not np.isfinite(base).all():
        raise ValueError("Finite [N,13] component baseline required.")
    torch = importlib.import_module("torch")
    torch.set_num_threads(artifact["threads"])
    net = _network(torch, config, artifact["dimensions"])
    net.load_state_dict(
        {
            k: torch.tensor(v, dtype=torch.float32)
            for k, v in artifact["weights"].items()
        }
    )
    net.eval()
    tx = _tensors(torch, inputs, artifact["scalers"])
    with torch.inference_mode():
        correction = (
            np.concatenate(
                [
                    _forward(
                        torch,
                        net,
                        {k: v[start : start + 1024] for k, v in tx.items()},
                        config["kind"],
                    ).numpy()
                    for start in range(0, len(selected), 1024)
                ]
            )
            if len(selected)
            else np.empty((0, 13))
        )
    components = base + correction * np.asarray(artifact["target_scale"])
    primitive = component_primitives(components)
    if not np.isfinite(primitive).all():
        raise ValueError("Nonfinite relational forecast.")
    return {
        "components": components,
        "primitive": primitive,
        "counts": counts_from_primitives(primitive),
    }
