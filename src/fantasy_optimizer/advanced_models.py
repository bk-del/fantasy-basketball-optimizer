"""Small CPU challengers and calibrated joint nonnegative count distributions."""

import importlib
from typing import Any

import numpy as np

from fantasy_optimizer.advanced_features import (
    FEATURE_NAMES,
    Array,
    counts_from_primitives,
)


def feature_columns(config: dict[str, Any]) -> list[int]:
    def keep(name: str) -> bool:
        if config["features"] == "no_context" and name.startswith("context_"):
            return False
        if config["features"] == "no_shot_priors" and name.startswith("shot_"):
            return False
        return not (
            config["features"] == "no_minutes_rates"
            and ("minute" in name or name.startswith("rate"))
        )

    return [i for i, name in enumerate(FEATURE_NAMES) if keep(name)]


def base_values(data: dict[str, Any], indices: Any, config: dict[str, Any]) -> Array:
    if not config["factorized"]:
        return np.asarray(data["recency_primitive"][indices]).copy()
    base = np.asarray(data["base"][indices]).copy()
    if config["features"] == "no_shot_priors":
        base[:, 10:13] = data["shot_population"][indices]
    return base


def component_primitives(components: Array) -> Array:
    c = components.copy()
    c[:, 0] = np.clip(c[:, 0], 0, 1)
    c[:, 1] = np.clip(c[:, 1], 0, 80)
    c[:, 2:10] = np.maximum(c[:, 2:10], 0)
    c[:, 10:13] = np.clip(c[:, 10:13], 0, 1)
    expected_exposure = c[:, 0] * c[:, 1]
    attempts = expected_exposure[:, None] * c[:, 2:5]
    makes = attempts * c[:, 10:13]
    values = np.empty((len(c), 11))
    for j in range(3):
        values[:, 2 * j] = makes[:, j]
        values[:, 2 * j + 1] = attempts[:, j] - makes[:, j]
    values[:, 6:] = expected_exposure[:, None] * c[:, 5:10]
    return values


def network(torch: Any, inputs: int, hidden: list[int], outputs: int) -> Any:
    net = torch.nn.Sequential(
        torch.nn.Linear(inputs, hidden[0]),
        torch.nn.ReLU(),
        torch.nn.Linear(hidden[0], hidden[1]),
        torch.nn.ReLU(),
        torch.nn.Linear(hidden[1], outputs),
    )
    torch.nn.init.zeros_(net[-1].weight)
    torch.nn.init.zeros_(net[-1].bias)
    return net


def fit_model(
    data: dict[str, Any],
    indices: Any,
    config: dict[str, Any],
    *,
    seed: int = 42,
    threads: int = 2,
) -> dict[str, Any]:
    columns = feature_columns(config)
    x = data["x"][indices][:, columns]
    base = base_values(data, indices, config)
    y = data["y"][indices] if config["factorized"] else data["primitive"][indices]
    weights = data["weights"][indices] if config["factorized"] else np.ones_like(y)
    target = y - base
    artifact: dict[str, Any] = {
        "config": config,
        "columns": columns,
        "training_cases": len(x),
        "seed": seed,
        "threads": threads,
        "feature_mean": x.mean(axis=0).tolist(),
        "feature_scale": np.maximum(x.std(axis=0), 1e-3).tolist(),
    }
    if config["kind"] == "lightgbm":
        lgb = importlib.import_module("lightgbm")
        models: list[str | None] = []
        for j in range(target.shape[1]):
            mask = weights[:, j] > 0
            if mask.sum() < 20:
                models.append(None)
                continue
            dataset = lgb.Dataset(
                x[mask],
                label=target[mask, j],
                weight=weights[mask, j],
                feature_name=[FEATURE_NAMES[i] for i in columns],
                free_raw_data=True,
            )
            booster = lgb.train(
                {
                    "objective": "regression",
                    "verbosity": -1,
                    "num_threads": threads,
                    "device_type": "cpu",
                    "deterministic": True,
                    "force_col_wise": True,
                    "seed": seed,
                    "num_leaves": config["leaves"],
                    "min_data_in_leaf": 80,
                    "learning_rate": 0.05,
                    "lambda_l2": 10,
                    "max_bin": 63,
                },
                dataset,
                num_boost_round=config["rounds"],
            )
            models.append(booster.model_to_string())
        artifact.update(models=models, library_version=lgb.__version__)
    else:
        torch = importlib.import_module("torch")
        torch.set_num_threads(threads)
        torch.manual_seed(seed)
        torch.use_deterministic_algorithms(True)
        normalized = (x - np.asarray(artifact["feature_mean"])) / np.asarray(
            artifact["feature_scale"]
        )
        normalized = np.clip(normalized, -20, 20)
        wsum = np.maximum(weights.sum(axis=0), 1)
        scale = np.maximum(np.sqrt((weights * target**2).sum(axis=0) / wsum), 1e-3)
        tx = torch.tensor(normalized, dtype=torch.float32)
        ty = torch.tensor(target / scale, dtype=torch.float32)
        tw = torch.tensor(weights * len(x) / wsum, dtype=torch.float32)
        net = network(torch, len(columns), config["hidden"], target.shape[1])
        optimizer = torch.optim.AdamW(net.parameters(), lr=0.001, weight_decay=0.01)
        generator = torch.Generator().manual_seed(seed)
        net.train()
        for _ in range(config["epochs"]):
            order = torch.randperm(len(tx), generator=generator)
            for batch in order.split(config["batch_size"]):
                optimizer.zero_grad(set_to_none=True)
                loss = (((net(tx[batch]) - ty[batch]) ** 2) * tw[batch]).mean()
                loss.backward()
                optimizer.step()
        artifact.update(
            weights={
                k: v.detach().cpu().numpy().tolist()
                for k, v in net.state_dict().items()
            },
            target_scale=scale.tolist(),
            library_version=torch.__version__,
        )
    return artifact


def predict_model(
    artifact: dict[str, Any], data: dict[str, Any], indices: Any
) -> dict[str, Array]:
    config = artifact["config"]
    x = data["x"][indices][:, artifact["columns"]]
    base = base_values(data, indices, config)
    if config["kind"] == "lightgbm":
        lgb = importlib.import_module("lightgbm")
        correction = np.column_stack(
            [
                np.zeros(len(x))
                if model is None
                else lgb.Booster(model_str=model).predict(
                    x, num_threads=artifact["threads"]
                )
                for model in artifact["models"]
            ]
        )
    else:
        torch = importlib.import_module("torch")
        torch.set_num_threads(artifact["threads"])
        normalized = np.clip(
            (x - np.asarray(artifact["feature_mean"]))
            / np.asarray(artifact["feature_scale"]),
            -20,
            20,
        )
        net = network(torch, len(artifact["columns"]), config["hidden"], base.shape[1])
        net.load_state_dict(
            {
                k: torch.tensor(v, dtype=torch.float32)
                for k, v in artifact["weights"].items()
            }
        )
        net.eval()
        with torch.inference_mode():
            correction = net(
                torch.tensor(normalized, dtype=torch.float32)
            ).numpy() * np.asarray(artifact["target_scale"])
    components = base + correction
    if config["factorized"]:
        primitive = component_primitives(components)
    else:
        primitive = np.maximum(components, 0)
    if not np.isfinite(primitive).all():
        raise ValueError("Nonfinite advanced forecast.")
    return {
        "primitive": primitive,
        "counts": counts_from_primitives(primitive),
        "components": components,
    }


def condition_key(case: dict[str, Any]) -> str:
    return f"{case['minutes_group']}:{'sparse' if case['history'] < 4 else 'regular'}"


def fit_calibrator(
    mu: Array, actual: Array, cases: list[dict[str, Any]], *, minimum: int = 100
) -> dict[str, Any]:
    cells: dict[str, Any] = {}
    keys = [condition_key(c) for c in cases]
    groups = sorted({c["minutes_group"] for c in cases})
    for key in ["pooled", *groups, *sorted(set(keys))]:
        mask = np.array(
            [
                key == "pooled" or key == c["minutes_group"] or key == k
                for c, k in zip(cases, keys, strict=True)
            ]
        )
        if mask.sum() < minimum and key != "pooled":
            continue
        mean = mu[mask]
        observed = actual[mask]
        factors = (observed + 0.5) / (mean + 0.5)
        factors -= factors.mean(axis=0)
        variance = np.maximum(
            0, (((observed - mean) ** 2 - mean) / (mean + 0.5) ** 2).mean(axis=0)
        )
        scale = np.sqrt(
            np.divide(
                variance,
                factors.var(axis=0),
                out=np.zeros(11),
                where=factors.var(axis=0) > 1e-8,
            )
        )
        factors = np.maximum(0, 1 + factors * scale)
        normalizer = factors.mean(axis=0)
        factors = np.divide(
            factors, normalizer, out=np.ones_like(factors), where=normalizer > 0
        )
        cells[key] = {
            "n": int(mask.sum()),
            "factors": factors.tolist(),
            "variance_target": variance.tolist(),
        }
    if not cells:
        raise ValueError("Chronological calibration cases required.")
    return {
        "version": "conditional-primitive-poisson-v1",
        "minimum": minimum,
        "cells": cells,
        "sampling": (
            "one whole residual factor vector, then primitive Poisson "
            "counts; preserves residual dependence and count identities"
        ),
        "limits": (
            "conditional marginal moment calibration; no guaranteed "
            "coverage or calibrated matchup odds"
        ),
    }


def joint_draws(
    mu: Array,
    case: dict[str, Any],
    calibrator: dict[str, Any],
    *,
    seed: int,
    samples: int,
    stream: str,
) -> Array:
    from fantasy_optimizer.storage import canonical, digest

    cell = calibrator["cells"].get(
        condition_key(case),
        calibrator["cells"].get(case["minutes_group"], calibrator["cells"]["pooled"]),
    )
    factors = cell["factors"]
    rng = np.random.default_rng(
        int(digest(canonical([seed, case["player_key"], stream])), 16)
    )
    chosen = np.asarray(
        [factors[int(i)] for i in rng.integers(0, len(factors), size=samples)]
    )
    primitive = rng.poisson(mu * chosen).astype(float)
    return counts_from_primitives(primitive)
