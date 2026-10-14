"""Read-only point-estimate frontiers from comparable refined fixture actions."""

from collections.abc import Mapping, Sequence
from importlib.resources import files
from math import isfinite
from typing import Any

import numpy as np

from fantasy_optimizer.simulation import CATEGORIES
from fantasy_optimizer.storage import canonical, digest

VERSION = "category-tradeoffs-v1"
MAX_ACTIONS = 256


class TradeoffError(ValueError):
    """Safe diagnostic for an unsupported tradeoff report."""


def numeric(value: object, lower: float, upper: float) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and isfinite(value)
        and lower <= value <= upper
    )


def frontier(points: Mapping[str, tuple[float, ...]]) -> list[str]:
    """Keep exact duplicates; dominance requires a strict improvement somewhere."""
    if not points:
        return []
    keys = sorted(points)
    matrix = np.array([points[key] for key in keys], dtype=np.float64)
    no_worse = np.ones((len(keys), len(keys)), dtype=np.bool_)
    better = np.zeros_like(no_worse)
    # Rows are challengers, columns are targets. Process one objective at a time
    # to avoid allocating actions x actions x objectives intermediate arrays.
    for column in matrix.T:
        no_worse &= column[:, None] >= column[None, :]
        better |= column[:, None] > column[None, :]
    dominated = np.atleast_1d((no_worse & better).any(axis=0))
    return [key for key, excluded in zip(keys, dominated, strict=True) if not excluded]


def tradeoff_view(
    report: Mapping[str, Any],
    categories: Sequence[str] = CATEGORIES,
) -> dict[str, Any]:
    categories = tuple(categories)
    if (
        not categories
        or len(set(categories)) != len(categories)
        or any(category not in CATEGORIES for category in categories)
    ):
        raise TradeoffError("Choose unique supported category names.")
    if isinstance(report.get("optimization"), dict):
        report = report["optimization"]
    if report.get("fixture_only") is not True or report.get("read_only") is not True:
        raise TradeoffError("Only read-only fixture optimizer reports are supported.")
    rows = report.get("ranked_actions")
    if not isinstance(rows, list) or len(rows) > MAX_ACTIONS:
        raise TradeoffError("Tradeoff report requires at most 256 ranked actions.")
    samples = report.get("finalist_samples")
    if type(samples) is not int or samples < 32:
        raise TradeoffError("Missing finalist sample budget.")
    actions: list[dict[str, Any]] = []
    excluded = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("action"), str):
            raise TradeoffError("Invalid action row.")
        action = row["action"]
        if not action or action in seen:
            raise TradeoffError("Action identities must be unique.")
        seen.add(action)
        reason = None
        if row.get("feasibility") != "feasible":
            reason = "Action is not verified feasible."
        elif row.get("refined") is not True or row.get("samples") != samples:
            reason = "Screening-only or different-budget estimate is not comparable."
        else:
            bounded = (
                ("matchup_credit_after", 0, 1),
                ("win_probability_after", 0, 1),
                ("win_probability_mc_se", 0, 0.5),
                ("paired_gain_mc_se", 0, 0.5),
                ("matchup_credit_gain", -1, 1),
                ("long_term_value_loss", 0, float("inf")),
            )
            if any(
                not numeric(row.get(key), lower, upper) for key, lower, upper in bounded
            ):
                reason = "Missing or invalid utility, value cost or uncertainty."
            for field in ("category_win_deltas", "category_tie_deltas"):
                values = row.get(field)
                if not isinstance(values, dict) or any(
                    not numeric(values.get(category), -1, 1) for category in categories
                ):
                    reason = "Missing or invalid category effects."
        if reason is not None:
            excluded.append({"action": action, "reason": reason})
            continue
        actions.append(
            {
                "action": action,
                "samples": samples,
                "win_probability": row["win_probability_after"],
                "win_probability_mc_se": row["win_probability_mc_se"],
                "matchup_credit": row["matchup_credit_after"],
                "matchup_credit_gain": row["matchup_credit_gain"],
                "paired_gain_mc_se": row["paired_gain_mc_se"],
                "long_term_value_loss": row["long_term_value_loss"],
                "category_win_deltas": {
                    category: row["category_win_deltas"][category]
                    for category in categories
                },
                "category_tie_deltas": {
                    category: row["category_tie_deltas"][category]
                    for category in categories
                },
                "recommendable": row.get("recommendable") is True,
                "explanation": row.get("explanation"),
            }
        )
    actions.sort(key=lambda row: row["action"])
    utility = {
        row["action"]: (row["matchup_credit"], -row["long_term_value_loss"])
        for row in actions
    }
    category_points = {
        row["action"]: (
            *row["category_win_deltas"].values(),
            -row["long_term_value_loss"],
        )
        for row in actions
    }
    return {
        "version": VERSION,
        "code_hash": digest(
            files("fantasy_optimizer").joinpath("tradeoffs.py").read_text()
        ),
        "config_hash": digest(
            canonical({"version": VERSION, "categories": categories})
        ),
        "source_provenance": {
            key: report.get(key)
            for key in (
                "optimizer_version",
                "simulator_version",
                "model_versions",
                "input_hash",
                "forecast_input_hash",
                "scenario_hash",
                "config_hash",
                "code_hash",
            )
        },
        "fixture_only": True,
        "read_only": True,
        "recommended_action": report.get("recommended_action"),
        "categories": list(categories),
        "samples": samples,
        "seed": report.get("seed"),
        "source_input_hash": report.get("input_hash"),
        "utility_frontier": frontier(utility),
        "category_frontier": frontier(category_points),
        "actions": actions,
        "excluded": excluded,
        "limitations": [
            "Point-estimate dominance is not statistical certainty or advice.",
            "Selected category axes change this display only, not the objective.",
            "Category tie effects are separate; no missing calibration is invented.",
            "Sampling SE excludes model uncertainty; roster cost is an ordinal proxy.",
        ],
    }


def render_text(view: Mapping[str, Any]) -> str:
    lines = [
        f"Fixture category tradeoffs ({view['version']}); point estimates only.",
        f"Incumbent recommendation: {view['recommended_action']}",
        "Utility frontier: " + (", ".join(view["utility_frontier"]) or "none"),
        "Category frontier: " + (", ".join(view["category_frontier"]) or "none"),
    ]
    for row in view["actions"]:
        lines.append(
            f"{row['action']}: win {row['win_probability']:.4f} "
            f"(MC SE {row['win_probability_mc_se']:.4f}); "
            f"gain {row['matchup_credit_gain']:+.4f} "
            f"(paired SE {row['paired_gain_mc_se']:.4f}); "
            f"value loss {row['long_term_value_loss']:.4f}; "
            f"recommendable={row['recommendable']}"
        )
        lines.append(
            "  Category win deltas: "
            + ", ".join(
                f"{category} {delta:+.4f}"
                for category, delta in row["category_win_deltas"].items()
            )
        )
        lines.append(
            "  Category tie deltas: "
            + ", ".join(
                f"{category} {delta:+.4f}"
                for category, delta in row["category_tie_deltas"].items()
            )
        )
        lines.append(f"  {row['explanation']}")
    for row in view["excluded"]:
        lines.append(f"Excluded {row['action']}: {row['reason']}")
    lines.extend(view["limitations"])
    return "\n".join(lines)
