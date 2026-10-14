"""Frozen chronological comparisons of CPU NBA forecasting challengers."""

import argparse
import hashlib
import json
import resource
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np

from fantasy_optimizer.advanced_features import (
    Array,
    FeatureState,
    counts_from_primitives,
    observations,
    prepare_dataset,
)
from fantasy_optimizer.advanced_models import (
    fit_calibrator,
    fit_model,
    joint_draws,
    predict_model,
)
from fantasy_optimizer.forecasting import STATS, recency_weights
from fantasy_optimizer.registry import Registry, atomic_write
from fantasy_optimizer.storage import canonical, digest, timestamp

CATEGORY_INDICES = [4, 5, 6, 7, 8, 9, 10, 11, 12]
METRIC_NAMES = [*STATS, "FG%", "FT%"]


def advanced_code_hash() -> str:
    directory = Path(__file__).parent
    paths = [
        directory / n
        for n in [
            "advanced_features.py",
            "advanced_models.py",
            "advanced_benchmark.py",
            "advanced_pipeline.py",
        ]
    ]
    return digest(
        "".join(p.read_text() for p in paths)
        + Path("pyproject.toml").read_text()
        + Path("uv.lock").read_text()
    )


def subset(
    data: dict[str, Any], start: str | None, end: str, *, labels_by_end: bool = True
) -> Any:
    lower = timestamp(start) if start else None
    upper = timestamp(end)
    return np.array(
        [
            i
            for i, c in enumerate(data["cases"])
            if (lower is None or timestamp(c["as_of"]) >= lower)
            and timestamp(c["as_of"]) < upper
            and (not labels_by_end or timestamp(c["outcome_available"]) <= upper)
        ],
        dtype=int,
    )


def augmented(values: Array) -> Array:
    ratios = np.column_stack(
        [
            np.divide(
                values[:, i],
                values[:, j],
                out=np.zeros(len(values)),
                where=values[:, j] > 0,
            )
            for i, j in [(0, 1), (2, 3)]
        ]
    )
    return np.column_stack([values, ratios])


def errors(expected: Array, actual: Array) -> Array:
    result = abs(augmented(expected) - augmented(actual))
    result[actual[:, 1] == 0, 11] = np.nan
    result[actual[:, 3] == 0, 12] = np.nan
    return result


def point_metrics(
    expected: Array, actual: Array, cases: list[dict[str, Any]]
) -> dict[str, Any]:
    err = errors(expected, actual)
    bias = augmented(expected) - augmented(actual)
    bias[np.isnan(err)] = np.nan
    values = {
        name: {
            "n": int(np.isfinite(err[:, j]).sum()),
            "mae": float(np.nanmean(err[:, j])),
            "bias": float(np.nanmean(bias[:, j])),
        }
        for j, name in enumerate(METRIC_NAMES)
    }
    return {
        "cases": len(cases),
        "players": len({c["player_key"] for c in cases}),
        "per_stat": {s: values[s] for s in STATS},
        "shooting_ratios": {s: values[s] for s in METRIC_NAMES[-2:]},
    }


def score(expected: Array, actual: Array, scales: Array) -> float:
    return float(
        np.mean(
            np.nanmean(errors(expected, actual), axis=0)[CATEGORY_INDICES]
            / scales[CATEGORY_INDICES]
        )
    )


def store(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    atomic_write(path, value)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def restore(reference: dict[str, Any]) -> dict[str, Any]:
    path = Path(reference["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
        raise ValueError(f"Artifact checksum mismatch: {path}")
    return dict(json.loads(path.read_text()))


def baselines(data: dict[str, Any], indices: Any, label: str) -> dict[str, Array]:
    key = {
        "recency": "recency_primitive",
        "recency_raw": "recency_primitive",
        "season_to_date": "season_primitive",
        "shrinkage": "shrinkage_primitive",
    }[label]
    primitive = data[key][indices]
    return {"primitive": primitive, "counts": counts_from_primitives(primitive)}


def add_minute_calibration(
    calibrator: dict[str, Any],
    prediction: dict[str, Array],
    data: dict[str, Any],
    indices: Any,
) -> None:
    if "components" not in prediction or prediction["components"].shape[1] != 13:
        return
    cells = {}
    for group in ["pooled", "low", "medium", "high", "unknown"]:
        rows = [
            j
            for j, i in enumerate(indices)
            if data["weights"][i, 1] > 0
            and (group == "pooled" or data["cases"][i]["minutes_group"] == group)
        ]
        if len(rows) < 100 and group != "pooled":
            continue
        residuals = (
            data["y"][indices[rows], 1]
            - np.clip(prediction["components"][rows, 1], 0, 80)
        ).tolist()
        cells[group] = residuals
    calibrator["minute_residuals"] = cells


def minute_metrics(
    prediction: dict[str, Array],
    data: dict[str, Any],
    indices: Any,
    calibrator: dict[str, Any],
) -> dict[str, Any] | None:
    if "components" not in prediction or prediction["components"].shape[1] != 13:
        return None
    c = prediction["components"]
    valid = data["weights"][indices, 1] > 0
    actual = data["y"][indices]
    pred = np.clip(c[:, 1], 0, 80)
    result = {
        "n": int(valid.sum()),
        "conditional_minutes_mae": float(abs(pred[valid] - actual[valid, 1]).mean()),
        "conditional_minutes_bias": float((pred[valid] - actual[valid, 1]).mean()),
        "nonzero_boxscore_brier": float(
            np.mean((np.clip(c[:, 0], 0, 1) - actual[:, 0]) ** 2)
        ),
        "per_minute_mae": {
            name: float(
                abs(np.maximum(c[valid, j + 2], 0) - actual[valid, j + 2]).mean()
            )
            for j, name in enumerate(
                ["2PA", "3PA", "FTA", "REB", "AST", "STL", "BLK", "TO"]
            )
        },
        "availability_probability": None,
        "minutes_target": (
            "known >=1 minute, nonzero box-score rows only; missing minutes never "
            "set to zero"
        ),
    }
    cells = calibrator.get("minute_residuals", {})
    coverage = []
    width = []
    if cells:
        for j in np.flatnonzero(valid):
            case = data["cases"][indices[j]]
            residual = cells.get(case["minutes_group"], cells["pooled"])
            low, high = np.clip(pred[j] + np.quantile(residual, [0.1, 0.9]), 0, 80)
            coverage.append(low <= actual[j, 1] <= high)
            width.append(high - low)
        result.update(
            coverage_80=float(np.mean(coverage)), mean_width_80=float(np.mean(width))
        )
    return result


def distribution_metrics(
    expected: Array,
    actual: Array,
    low: Array,
    high: Array,
    probability: Array,
    threshold: Array,
    rows: Any,
) -> dict[str, Any]:
    e = augmented(expected)[rows]
    a = augmented(actual)[rows]
    lo = low[rows]
    hi = high[rows]
    p = probability[rows]
    t = threshold[rows]
    valid = np.isfinite(errors(expected[rows], actual[rows]))
    output: dict[str, Any] = {}
    for j, name in enumerate(METRIC_NAMES):
        mask = valid[:, j]
        av = a[mask, j]
        ev = e[mask, j]
        lv = lo[mask, j]
        hv = hi[mask, j]
        pv = p[mask, j]
        tv = t[mask, j]
        if not len(av):
            output[name] = {"n": 0}
            continue
        reliability = []
        for k in range(5):
            selected = (pv >= k / 5) & ((pv < (k + 1) / 5) if k < 4 else (pv <= 1))
            reliability.append(
                {
                    "n": int(selected.sum()),
                    "mean_probability": float(pv[selected].mean())
                    if selected.any()
                    else None,
                    "observed_rate": float((av[selected] > tv[selected]).mean())
                    if selected.any()
                    else None,
                }
            )
        output[name] = {
            "n": len(av),
            "mae": float(abs(ev - av).mean()),
            "bias": float((ev - av).mean()),
            "coverage_80": float(((av >= lv) & (av <= hv)).mean()),
            "mean_width_80": float((hv - lv).mean()),
            "interval_score_80": float(
                (
                    (hv - lv)
                    + 10 * np.maximum(lv - av, 0)
                    + 10 * np.maximum(av - hv, 0)
                ).mean()
            ),
            "brier": float(((pv - (av > tv)) ** 2).mean()),
            "reliability": reliability,
        }
    return output


def evaluate(
    data: dict[str, Any],
    indices: Any,
    prediction: dict[str, Array],
    calibrator: dict[str, Any],
    protocol: dict[str, Any],
    *,
    raw_records: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cases = [data["cases"][i] for i in indices]
    expected = prediction["counts"]
    actual = data["counts"][indices]
    threshold = augmented(data["season_to_date"][indices])
    threshold[:, :11] = np.floor(threshold[:, :11])
    low = np.zeros((len(indices), 13))
    high = low.copy()
    probability = low.copy()
    state = FeatureState(raw_records) if raw_records is not None else None
    for j, case in enumerate(cases):
        if state is not None:
            origin = timestamp(case["as_of"])
            state.advance(origin)
            own = state.history[case["player_key"]]
            weights = recency_weights([r["end"] for r in own], origin, 14)
            rng = np.random.default_rng(
                int(
                    digest(
                        canonical([protocol["seed"], case["player_key"], case["as_of"]])
                    ),
                    16,
                )
            )
            selected = rng.choice(len(own), size=protocol["samples"], p=weights)
            shocks = rng.choice(
                [0.5, 1, 1.5] if len(own) < 3 else [0.75, 1, 1.25],
                size=protocol["samples"],
            )
            draws = np.rint(
                np.array([own[int(k)]["counts"] for k in selected]) * shocks[:, None]
            )
            draws[:, 5] = 2 * draws[:, 0] + draws[:, 4] + draws[:, 2]
        else:
            draws = joint_draws(
                prediction["primitive"][j],
                case,
                calibrator,
                seed=protocol["seed"],
                samples=protocol["samples"],
                stream=case["as_of"],
            )
        values = augmented(draws)
        low[j], high[j] = np.quantile(values, [0.1, 0.9], axis=0)
        probability[j] = (values > threshold[j]).mean(axis=0)
    per = distribution_metrics(
        expected, actual, low, high, probability, threshold, np.arange(len(indices))
    )
    segments = {}
    for segment in ["low", "medium", "high", "unknown", "sparse", "established"]:
        rows = np.array(
            [
                j
                for j, c in enumerate(cases)
                if (
                    c["history"] < 4
                    if segment == "sparse"
                    else c["history"] >= 4
                    if segment == "established"
                    else c["minutes_group"] == segment
                )
            ],
            dtype=int,
        )
        segments[segment] = (
            {
                "cases": len(rows),
                "per_category": distribution_metrics(
                    expected, actual, low, high, probability, threshold, rows
                ),
            }
            if len(rows)
            else {"cases": 0}
        )
    result = {
        "cases": len(cases),
        "players": len({c["player_key"] for c in cases}),
        "per_category": per,
        "segments": segments,
        "minutes": minute_metrics(prediction, data, indices, calibrator),
        "mean_probability_mc_se": float(
            np.sqrt(probability * (1 - probability) / protocol["samples"]).mean()
        ),
        "ratio_zero_policy": (
            "target zero attempts excluded; sample zero attempts ratio zero"
        ),
        "sampler": (
            "existing whole-vector empirical/exposure distribution, vectorized RNG"
        )
        if state is not None
        else calibrator["version"],
    }
    replay = {
        "case_keys": [
            [c["player_key"], c["as_of"], c["id"], c["input_hash"], c["outcome_hash"]]
            for c in cases
        ],
        "expected": expected.tolist(),
        "interval_low": low.tolist(),
        "interval_high": high.tolist(),
        "probability": probability.tolist(),
        "threshold": threshold.tolist(),
        "actual": actual.tolist(),
    }
    return result, replay


def paired_comparison(
    expected: Array,
    baseline: Array,
    actual: Array,
    cases: list[dict[str, Any]],
    scales: Array,
    *,
    seed: int,
    repetitions: int,
) -> dict[str, Any]:
    delta = errors(expected, actual) - errors(baseline, actual)
    players = sorted({c["player_key"] for c in cases})
    lookup = {p: i for i, p in enumerate(players)}
    sums = np.zeros((len(players), 13))
    counts = sums.copy()
    for i, c in enumerate(cases):
        valid = np.isfinite(delta[i])
        sums[lookup[c["player_key"]], valid] += delta[i, valid]
        counts[lookup[c["player_key"]], valid] += 1
    rng = np.random.default_rng(seed)
    weights = rng.multinomial(
        len(players), np.full(len(players), 1 / len(players)), size=repetitions
    )
    means = np.divide(
        weights @ sums,
        weights @ counts,
        out=np.zeros((repetitions, 13)),
        where=(weights @ counts) > 0,
    )
    score_samples = np.mean(
        means[:, CATEGORY_INDICES] / scales[CATEGORY_INDICES], axis=1
    )
    return {
        "players": len(players),
        "repetitions": repetitions,
        "scope": "paired player-cluster bootstrap; shared calendar shocks not removed",
        "normalized_nine_category_delta": float(
            np.mean(
                np.nanmean(delta, axis=0)[CATEGORY_INDICES] / scales[CATEGORY_INDICES]
            )
        ),
        "normalized_interval_95": np.quantile(score_samples, [0.025, 0.975]).tolist(),
        "per_category": {
            name: {
                "mae_delta": float(np.nanmean(delta[:, j])),
                "interval_95": np.quantile(means[:, j], [0.025, 0.975]).tolist(),
            }
            for j, name in enumerate(METRIC_NAMES)
        },
    }


def promotion_gate(
    selected: dict[str, Any],
    baseline: dict[str, Any],
    comparison: dict[str, Any],
    relative_gain: float,
    criteria: dict[str, Any],
) -> dict[str, Any]:
    reasons = []
    a = selected["per_category"]
    b = baseline["per_category"]
    if relative_gain < criteria["minimum_relative_nine_category_gain"]:
        reasons.append("Insufficient normalized nine-category gain.")
    if comparison["normalized_interval_95"][1] >= 0:
        reasons.append("Player-cluster comparison interval includes no improvement.")
    for name in METRIC_NAMES:
        limit = (
            criteria["maximum_shooting_ratio_relative_mae_increase"]
            if name in ["FG%", "FT%"]
            else criteria["maximum_single_category_relative_mae_increase"]
        )
        if a[name]["mae"] > b[name]["mae"] * (1 + limit):
            reasons.append(f"{name} MAE exceeds frozen regression limit.")
    interval_ratio = float(
        np.mean(
            [
                a[s]["interval_score_80"] / max(b[s]["interval_score_80"], 1e-8)
                for s in STATS
            ]
        )
    )
    brier_ratio = float(
        np.mean([a[s]["brier"] / max(b[s]["brier"], 1e-8) for s in STATS])
    )
    if interval_ratio > criteria["maximum_mean_interval_score_ratio"]:
        reasons.append("Mean count interval score regresses.")
    if brier_ratio > criteria["maximum_mean_count_brier_ratio"]:
        reasons.append("Mean count probability Brier regresses.")
    lo, hi = criteria["coverage_80_range"]
    if not lo <= float(np.mean([a[s]["coverage_80"] for s in STATS])) <= hi:
        reasons.append("Overall count coverage outside frozen range.")
    for group in ["low", "medium", "high"]:
        segment = selected["segments"][group]
        if segment["cases"] >= 100:
            coverage = segment["per_category"]["PTS"]["coverage_80"]
            if not lo <= coverage <= hi:
                reasons.append(f"{group} minute PTS coverage outside frozen range.")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "nine_category_relative_gain": relative_gain,
        "mean_count_interval_score_ratio": interval_ratio,
        "mean_count_brier_ratio": brier_ratio,
    }


def run(
    root: Path, protocol_path: Path, output: Path, *, prepare_only: bool = False
) -> dict[str, Any]:
    started = time.perf_counter()
    protocol = json.loads(protocol_path.read_text())
    data = prepare_dataset(root)
    freeze = digest(canonical([protocol, advanced_code_hash(), data["identity"]]))
    registry = Registry(root / "features" / "advanced-benchmark-registry.json")
    holdout_id = digest(
        canonical(
            [protocol["version"], protocol["holdout_start"], protocol["holdout_end"]]
        )
    )
    report = json.loads(output.read_text()) if output.exists() else None
    if report and report["freeze_hash"] != freeze:
        raise ValueError(
            "Advanced protocol/code/data changed; retain frozen evidence and "
            "use a new unexamined period."
        )
    if report and report["state"] == "completed":
        return dict(report)
    if not report:
        if holdout_id in registry.read()["holdouts"]:
            raise ValueError("Holdout already consumed; frozen evidence is required.")
        directory = Path("models/advanced") / freeze
        directory.mkdir(parents=True, exist_ok=True)
        all_dev = []
        baseline_dev = []
        actual_dev = []
        dev_cases: list[dict[str, Any]] = []
        development: dict[str, Any] = {
            label: {"folds": [], "fit_seconds": 0.0} for label in protocol["candidates"]
        }
        predictions: dict[str, list[Array]] = {label: [] for label in development}
        for start, end in protocol["development_folds"]:
            train = subset(data, None, start)
            valid = subset(data, start, end)
            all_dev.extend(valid.tolist())
            baseline_dev.append(data["recency"][valid])
            actual_dev.append(data["counts"][valid])
            dev_cases.extend(data["cases"][i] for i in valid)
            for label, config in protocol["candidates"].items():
                timer = time.perf_counter()
                model = fit_model(
                    data,
                    train,
                    config,
                    seed=protocol["seed"],
                    threads=protocol["threads"],
                )
                elapsed = time.perf_counter() - timer
                pred = predict_model(model, data, valid)
                predictions[label].append(pred["counts"])
                development[label]["fit_seconds"] += elapsed
                development[label]["folds"].append(
                    {
                        "train_end": start,
                        "validation_end": end,
                        "training_cases": len(train),
                        "validation_cases": len(valid),
                        "training_players": len(
                            {data["cases"][i]["player_key"] for i in train}
                        ),
                        "metrics": point_metrics(
                            pred["counts"],
                            data["counts"][valid],
                            [data["cases"][i] for i in valid],
                        ),
                        "fit_seconds": elapsed,
                    }
                )
                print(f"development {start} {label} {elapsed:.2f}s", flush=True)
        baseline = np.concatenate(baseline_dev)
        actual = np.concatenate(actual_dev)
        scales = np.maximum(np.nanmean(errors(baseline, actual), axis=0), 1e-8)
        for label in development:
            means = np.concatenate(predictions[label])
            development[label].update(
                normalized_nine_category_loss=score(means, actual, scales),
                metrics=point_metrics(means, actual, dev_cases),
            )
        eligible = [k for k in development if not k.startswith("ablate_")]
        selected = min(
            eligible, key=lambda k: (development[k]["normalized_nine_category_loss"], k)
        )
        best_tree = min(
            [k for k in eligible if protocol["candidates"][k]["kind"] == "lightgbm"],
            key=lambda k: (development[k]["normalized_nine_category_loss"], k),
        )
        final_labels = sorted({selected, best_tree, "mlp_small"})
        trained = {}
        calibration = {}
        train = subset(data, None, protocol["fit_end"])
        cal = subset(data, protocol["fit_end"], protocol["calibration_end"])
        cal_cases = [data["cases"][i] for i in cal]
        for label in [*final_labels, "recency", "season_to_date", "shrinkage"]:
            timer = time.perf_counter()
            if label in protocol["candidates"]:
                model = fit_model(
                    data,
                    train,
                    protocol["candidates"][label],
                    seed=protocol["seed"],
                    threads=protocol["threads"],
                )
                trained[label] = store(directory / f"{label}.json", model)
                prediction = predict_model(model, data, cal)
            else:
                prediction = baselines(data, cal, label)
            calibrator = fit_calibrator(
                prediction["primitive"], data["primitive"][cal], cal_cases
            )
            add_minute_calibration(calibrator, prediction, data, cal)
            calibration[label] = {
                "artifact": store(directory / f"{label}-calibration.json", calibrator),
                "cases": len(cal),
                "fit_seconds": time.perf_counter() - timer,
                "point_metrics": point_metrics(
                    prediction["counts"], data["counts"][cal], cal_cases
                ),
            }
            print(f"calibration {label}", flush=True)
        report = {
            "state": "prepared",
            "protocol": protocol,
            "freeze_hash": freeze,
            "holdout_id": holdout_id,
            "code_hash": advanced_code_hash(),
            "data": data["data"],
            "data_identity": data["identity"],
            "all_observations": data["all_observations"],
            "all_players": data["all_players"],
            "eligible_feature_cases": len(data["cases"]),
            "feature_names": data["feature_names"],
            "development": development,
            "selected": selected,
            "best_tree": best_tree,
            "final_labels": final_labels,
            "scales": scales.tolist(),
            "models": trained,
            "calibration": calibration,
            "research_training_cases": len(train),
            "research_training_players": len(
                {data["cases"][i]["player_key"] for i in train}
            ),
            "development_indices_hash": digest(canonical(all_dev)),
            "prepare_seconds": time.perf_counter() - started,
        }
        atomic_write(output, report)
    if prepare_only:
        return dict(report)
    # A resumed identical frozen computation is allowed; no selection is recomputed.
    registry.consume_holdout(holdout_id) if holdout_id not in registry.read()[
        "holdouts"
    ] else None
    indices = subset(
        data, protocol["holdout_start"], protocol["holdout_end"], labels_by_end=False
    )
    label_cutoff = timestamp(protocol["holdout_end"]) + timedelta(days=2)
    indices = np.array(
        [
            i
            for i in indices
            if timestamp(data["cases"][i]["outcome_available"]) <= label_cutoff
        ],
        dtype=int,
    )
    holdout = {}
    predicted = {}
    records, _ = observations(root, protocol["availability_policy"])
    directory = Path("models/advanced") / freeze
    for label in [
        "recency_raw",
        "recency",
        "season_to_date",
        "shrinkage",
        *report["final_labels"],
    ]:
        timer = time.perf_counter()
        prediction = (
            predict_model(restore(report["models"][label]), data, indices)
            if label in report["models"]
            else baselines(data, indices, label)
        )
        calibrator = restore(
            report["calibration"]["recency" if label == "recency_raw" else label][
                "artifact"
            ]
        )
        result, replay = evaluate(
            data,
            indices,
            prediction,
            calibrator,
            protocol,
            raw_records=records if label == "recency_raw" else None,
        )
        result.update(
            evaluation_seconds=time.perf_counter() - timer,
            replay=store(directory / f"{label}-heldout-replay.json", replay),
        )
        holdout[label] = result
        predicted[label] = prediction["counts"]
        print(
            f"heldout {label} {result['cases']} cases "
            f"{result['evaluation_seconds']:.2f}s",
            flush=True,
        )
    selected = report["selected"]
    cases = [data["cases"][i] for i in indices]
    scales = np.asarray(report["scales"])
    comparison = paired_comparison(
        predicted[selected],
        predicted["recency_raw"],
        data["counts"][indices],
        cases,
        scales,
        seed=protocol["seed"],
        repetitions=protocol["bootstrap_repetitions"],
    )
    relative_gain = 1 - score(
        predicted[selected], data["counts"][indices], scales
    ) / score(predicted["recency_raw"], data["counts"][indices], scales)
    gate = promotion_gate(
        holdout[selected],
        holdout["recency_raw"],
        comparison,
        relative_gain,
        protocol["promotion_gate"],
    )
    report.update(
        state="completed",
        holdout=holdout,
        comparison=comparison,
        promotion_gate=gate,
        target_cases_hash=digest(
            canonical(
                [
                    [c["player_key"], c["id"], c["as_of"], c["outcome_hash"]]
                    for c in cases
                ]
            )
        ),
        final_evaluation_seconds=time.perf_counter() - started,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        limitations=[
            (
                "Snapshot next-day publication assumption; historical corrections "
                "cannot be undone."
            ),
            (
                "Target-game team/opponent/home/lineup/injury/schedule absent from "
                "features."
            ),
            (
                "Missing minutes are unknown; nonzero-boxscore probability is not "
                "availability."
            ),
            (
                "Current NBA roles unknown; no verified future schedule, no actual "
                "seven-day totals."
            ),
            (
                "Conditional moment calibration has no coverage or "
                "matchup-probability guarantee."
            ),
            "Player-cluster intervals do not remove common calendar shocks.",
            "Ablations are development diagnostics, not selected on final outcomes.",
        ],
    )
    atomic_write(output, report)
    return dict(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/nba_data"))
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("docs/benchmarks/nba-advanced-protocol.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("docs/benchmarks/nba-advanced.json")
    )
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    result = run(args.data, args.protocol, args.output, prepare_only=args.prepare_only)
    print(
        json.dumps(
            {
                "state": result["state"],
                "selected": result["selected"],
                "report": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
