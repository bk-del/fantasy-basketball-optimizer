"""Fixture diagnostic report; fitting/promotion waits for verified Yahoo histories."""

from dataclasses import asdict
from importlib.resources import files
from typing import Any

from fantasy_optimizer.context import PROTOCOL, breakout_label, shift_features
from fantasy_optimizer.forecast_fixture import fixture_history
from fantasy_optimizer.forecasting import known_windows
from fantasy_optimizer.storage import canonical, digest


def context_fixture() -> dict[str, Any]:
    windows, as_of = fixture_history()
    features = [
        shift_features(windows, key, as_of)
        for key in sorted({r.player_key for r in windows})
    ]
    # Rolling chronological diagnostics only: no randomly shuffled player windows.
    labels = []
    for row in known_windows(windows, as_of):
        if row.end > as_of:
            continue
        past = shift_features(windows, row.player_key, row.end)
        if past["baseline_points"] is not None:
            labels.append(breakout_label(windows, (), row.player_key, row.end, as_of))
    return {
        "fixture_only": True,
        "as_of": as_of.isoformat(),
        "version": "context-diagnostics-v1",
        "active_baseline": "recency",
        "active_model_version": "weekly-counts-v1",
        "model_promoted": False,
        "protocol": asdict(PROTOCOL),
        "protocol_hash": digest(canonical(asdict(PROTOCOL))),
        "code_hash": digest(
            files("fantasy_optimizer").joinpath("context.py").read_text()
        ),
        "input_hash": digest(
            canonical([r.payload() for r in known_windows(windows, as_of)])
        ),
        "features": features,
        "evaluation": {
            "split": (
                "chronological rolling origins; features at "
                "origin, labels at evaluation time"
            ),
            "candidate_origins": len(labels),
            "usable_labels": sum(label["label"] is not None for label in labels),
            "precision": None,
            "recall": None,
            "calibration": None,
            "decision_uplift_vs_stage03": None,
            "label_skip_reasons": sorted({label["skip_reason"] for label in labels}),
            "reason": (
                "No verified Yahoo history or "
                "game/availability labels; no model fit, "
                "probabilities or uplift estimate."
            ),
        },
        "context_uncertainty": {
            "action": "retain Stage 03 joint exposure widening",
            "availability_probability": None,
            "minutes": None,
            "additional_role_multiplier": None,
        },
        "skipped": [
            "supervised_model",
            "probability_calibration",
            "decision_uplift",
            "role_injury_features",
            "per_game_conversion",
        ],
        "warnings": [
            (
                "Count-shift alarms are not breakout "
                "probabilities or causal injury narratives."
            ),
            (
                "Synthetic diagnostics do not establish Yahoo "
                "support or real-world improvement."
            ),
            "Stage 03 remains active; no forecast or optimizer inputs were adjusted.",
        ],
    }
