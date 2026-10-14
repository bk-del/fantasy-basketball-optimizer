"""Chronological synthetic-league decisions scored on real subsequent NBA counts.

Ownership and weekly exposure are hypothetical. Inputs come only from completed,
origin-known rows; future rows enter ``realized_counts`` after actions are frozen.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from fantasy_optimizer.advanced_benchmark import restore
from fantasy_optimizer.advanced_features import (
    Array,
    FeatureState,
    counts_from_primitives,
    observations,
)
from fantasy_optimizer.advanced_models import predict_model
from fantasy_optimizer.simulation import CATEGORIES, reference_outcomes
from fantasy_optimizer.storage import canonical, digest, timestamp

PROTOCOL: dict[str, Any] = {
    "version": "hypothetical-nba-decisions-v1",
    "registered_before_execution": "2026-10-13",
    "evaluation_label": "previously examined chronological descriptive research",
    "first_origin": "2025-10-27T00:00:00+00:00",
    "origins": 12,
    "horizon_days": 7,
    "leagues_per_origin": 4,
    "roster_size": 8,
    "opponent_size": 8,
    "free_agents": 8,
    "draft_population": 96,
    "minimum_same_season_rows": 5,
    "maximum_staleness_days": 14,
    "samples": 256,
    "seed": 142,
    "bootstrap_replicates": 2000,
    "eligibility": "all UTIL; every rostered player active for every actual game",
    "transactions": "one immediate add/drop or HOLD; no waiver delay, cap, or IR",
    "ownership": "independent deterministic synthetic draft each origin and league",
    "selection": "matchup credit then category credit; HOLD then action order on ties",
    "schedule": "unknown; empirical four past 7-day row-count bins; no future games",
    "uncertainty": "independent player empirical primitive-vector bootstrap",
    "models": "HOLD, season_to_date, recency, frozen lgbm_small and mlp_small",
    "model_cutoff": "frozen research fit and calibration precede first replay origin",
    "missing_rows": "no recorded subsequent statistics; never labelled injury or DNP",
    "publication_policy": "retrospective_next_day assumption; original timing unknown",
    "unsupported": [
        "historical Yahoo ownership/transactions/positions",
        "opponent responses or persistent league trajectory",
        "calibrated joint matchup odds or championship probability",
        "verified future schedule, current roster, injuries or causal effects",
    ],
}


def eligible_players(state: FeatureState, origin: datetime) -> list[str]:
    """Deterministic origin-only pool; no target rows, current team, or names."""
    season = origin.year + int(origin.month >= 7)
    scores = []
    for player, rows in state.history.items():
        current = [r for r in rows if r["season"] == season]
        if len(current) < PROTOCOL["minimum_same_season_rows"]:
            continue
        if (origin - rows[-1]["end"]).days > PROTOCOL["maximum_staleness_days"]:
            continue
        mean = np.mean([r["counts"] for r in current], axis=0)
        # A fixed production ordering for the synthetic draft, never a model fit.
        score = float(mean[5] + mean[6] + mean[7] + 2 * (mean[8] + mean[9]))
        scores.append((-score, player))
    return [p for _, p in sorted(scores)[: PROTOCOL["draft_population"]]]


def candidate_actions(roster: list[str], pool: list[str]) -> list[tuple[str, str]]:
    if len(set(roster + pool)) != len(roster + pool):
        raise ValueError("Roster/free-agent identities must be disjoint and unique.")
    return [("", "")] + [(add, drop) for add in pool for drop in roster]


def roster_after(roster: list[str], action: tuple[str, str]) -> list[str]:
    add, drop = action
    if not add and not drop:
        return roster.copy()
    if drop not in roster or add in roster or not add:
        raise ValueError("Illegal add/drop action.")
    return [add if p == drop else p for p in roster]


def compare_totals(own: NDArray[np.int64], opponent: NDArray[np.int64]) -> Array:
    """Use existing 9-CAT integer ratio arithmetic, zero-attempt tie policy."""
    values = np.stack([own, opponent], axis=1)
    return reference_outcomes(
        values,
        np.array([0, 1], dtype=np.int64),
        np.zeros((2, 11), dtype=np.int64),
        True,
    ).astype(float)


def credits(outcomes: Array) -> tuple[Array, Array]:
    wins = (outcomes > 0).sum(axis=1)
    losses = (outcomes < 0).sum(axis=1)
    matchup = (wins > losses).astype(float) + 0.5 * (wins == losses)
    category = wins.astype(float) + 0.5 * (outcomes == 0).sum(axis=1)
    return matchup, category


def choose_action(
    rosters: list[list[str]], opponent: list[str], banks: dict[str, NDArray[np.int64]]
) -> tuple[int, list[dict[str, float]]]:
    opposition = sum(
        (banks[p] for p in opponent), start=np.zeros_like(banks[opponent[0]])
    )
    scores = []
    for roster in rosters:
        own = sum((banks[p] for p in roster), start=np.zeros_like(opposition))
        matchup, category = credits(compare_totals(own, opposition))
        scores.append(
            {
                "matchup_credit": float(matchup.mean()),
                "categories": float(category.mean()),
            }
        )
    # Stable max preserves HOLD (index zero) whenever both scores tie.
    best = max(
        range(len(scores)),
        key=lambda i: (scores[i]["matchup_credit"], scores[i]["categories"]),
    )
    return best, scores


def weekly_banks(
    history: dict[str, list[dict[str, Any]]],
    players: list[str],
    origin: datetime,
    means: Array,
    seed: int,
    samples: int,
) -> dict[str, NDArray[np.int64]]:
    """Whole-vector empirical draws; every input row is checked as origin-known.

    Empirical counts of recorded rows include source zero rows and are not
    participation probabilities. Primitive scaling preserves shooting identities.
    Shared random numbers compare strategies/actions; different players remain
    independent, an explicit limitation of this historical experiment.
    """
    banks = {}
    for index, player in enumerate(players):
        rows = history[player]
        if any(max(r["end"], r["available"]) > origin for r in rows):
            raise ValueError("Future row in decision sampling history.")
        recent = [r for r in rows if r["end"] > origin - timedelta(days=28)]
        source = recent or rows[-10:]
        primitive = np.asarray([r["primitive"] for r in source])
        exposure = np.array(
            [
                sum(
                    origin - timedelta(days=7 * (i + 1))
                    < r["end"]
                    <= origin - timedelta(days=7 * i)
                    for r in rows
                )
                for i in range(4)
            ]
        )
        rng = np.random.default_rng(int(digest(f"{seed}:{player}")[:16], 16))
        n = rng.choice(exposure, size=samples)
        raw = rng.integers(0, len(source), size=(samples, max(1, int(exposure.max()))))
        empirical_mean = primitive.mean(axis=0)
        scale = np.divide(
            means[index], empirical_mean, out=np.zeros(11), where=empirical_mean > 0
        )
        scaled = np.rint(primitive[raw] * scale).astype(np.int64)
        # Unsupported positive components use constant integer rounding, recorded
        # as a limitation rather than invented uncertainty or Gaussian noise.
        scaled[:, :, empirical_mean == 0] = np.rint(
            means[index, empirical_mean == 0]
        ).astype(np.int64)
        scaled *= (np.arange(raw.shape[1])[None, :] < n[:, None])[:, :, None]
        banks[player] = counts_from_primitives(scaled.sum(axis=1)).astype(np.int64)
    return banks


def realized_counts(
    records: list[dict[str, Any]], players: list[str], origin: datetime
) -> dict[str, NDArray[np.int64]]:
    """Outcome-only path; never used by pool, features, or action selection."""
    end = origin + timedelta(days=PROTOCOL["horizon_days"])
    totals: dict[str, NDArray[np.int64]] = {
        p: np.zeros(11, dtype=np.int64) for p in players
    }
    for row in records:
        if row["player"] in totals and origin <= row["day"] < end:
            totals[row["player"]] += row["counts"].astype(np.int64)
    return totals


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    strategies = sorted({r["strategy"] for r in rows})
    result = {}
    for strategy in strategies:
        selected = [r for r in rows if r["strategy"] == strategy]
        weekly: dict[str, list[float]] = {}
        for row in selected:
            hold = next(
                r
                for r in rows
                if r["origin"] == row["origin"]
                and r["league"] == row["league"]
                and r["strategy"] == "HOLD"
            )
            weekly.setdefault(row["origin"], []).append(
                row["matchup_credit"] - hold["matchup_credit"]
            )
        paired = np.array([np.mean(v) for _, v in sorted(weekly.items())])
        rng = np.random.default_rng(PROTOCOL["seed"])
        boot = paired[
            rng.integers(
                0, len(paired), size=(PROTOCOL["bootstrap_replicates"], len(paired))
            )
        ].mean(axis=1)
        result[strategy] = {
            "decisions": len(selected),
            "calendar_weeks": len(paired),
            "matchup_win_rate": float(np.mean([r["matchup_win"] for r in selected])),
            "matchup_tie_rate": float(np.mean([r["matchup_tie"] for r in selected])),
            "matchup_credit": float(np.mean([r["matchup_credit"] for r in selected])),
            "category_wins_mean": float(
                np.mean([r["category_wins"] for r in selected])
            ),
            "category_credit_mean": float(
                np.mean([r["category_credit"] for r in selected])
            ),
            "matchup_regret_mean": float(
                np.mean([r["matchup_regret"] for r in selected])
            ),
            "category_regret_mean": float(
                np.mean([r["category_regret"] for r in selected])
            ),
            "adds": sum(bool(r["add"]) for r in selected),
            "category_credit_by_category": dict(
                zip(
                    CATEGORIES,
                    np.mean([r["category_credits"] for r in selected], axis=0).tolist(),
                    strict=True,
                )
            ),
            "paired_matchup_credit_minus_hold": float(paired.mean()),
            "paired_calendar_week_bootstrap_95": np.quantile(
                boot, [0.025, 0.975]
            ).tolist(),
            "forecast_matchup_credit_mse": float(
                np.mean(
                    [
                        (r["predicted_credit"] - r["matchup_credit"]) ** 2
                        for r in selected
                    ]
                )
            ),
        }
    return result


def run_replay(
    root: Path,
    *,
    include_frozen_models: bool = True,
    forecast_provider: Callable[
        [dict[str, Any], list[str], datetime], dict[str, dict[str, Any]]
    ]
    | None = None,
) -> dict[str, Any]:
    """Run registered replay, optionally adding origin-safe external models.

    Provider receives only origin-known feature arrays, player IDs and origin.
    Each returned label requires primitive means, trained_through, artifact_sha256.
    Training/selection/calibration cutoff must all precede prediction origin.
    """
    records, provenance = observations(root, "retrospective_next_day")
    models = {}
    references = {}
    if include_frozen_models:
        report = json.loads(Path("docs/benchmarks/nba-advanced.json").read_text())
        first = timestamp(PROTOCOL["first_origin"])
        if timestamp(report["protocol"]["calibration_end"]) >= first:
            raise ValueError(
                "Frozen research models/calibration must precede decisions."
            )
        for label, reference in report["models"].items():
            models[label] = restore(reference)
            references[label] = reference
    state = FeatureState(records)
    rows = []
    skipped = []
    first = timestamp(PROTOCOL["first_origin"])
    for week in range(PROTOCOL["origins"]):
        origin = first + timedelta(days=7 * week)
        state.advance(origin)
        population = eligible_players(state, origin)
        if len(population) < 24:
            skipped.append(
                {
                    "origin": origin.isoformat(),
                    "reason": "fewer than 24 origin-eligible draft players",
                    "eligible": len(population),
                }
            )
            continue
        raw_snapshots = [state.snapshot(p, origin) for p in population]
        if any(s is None for s in raw_snapshots):
            raise ValueError("Eligible player without feature history.")
        snapshots = [s for s in raw_snapshots if s is not None]
        feature_data = {
            k: np.array([s[k] for s in snapshots])
            for k in ("x", "base", "recency_primitive", "shot_population")
        }
        means = {
            "season_to_date": np.array([s["season_primitive"] for s in snapshots]),
            "recency": np.array([s["recency_primitive"] for s in snapshots]),
        }
        means.update(
            {
                label: predict_model(
                    artifact, feature_data, np.arange(len(population))
                )["primitive"]
                for label, artifact in models.items()
            }
        )
        if forecast_provider is not None:
            for label, prediction in forecast_provider(
                feature_data, population, origin
            ).items():
                if label in means or label == "HOLD":
                    raise ValueError("External forecast label conflicts with strategy.")
                if timestamp(prediction["trained_through"]) >= origin:
                    raise ValueError("External learner cutoff must precede origin.")
                checksum = prediction["artifact_sha256"]
                if len(checksum) != 64 or any(
                    c not in "0123456789abcdef" for c in checksum
                ):
                    raise ValueError("External model requires artifact SHA256.")
                values = np.asarray(prediction["primitive"], dtype=float)
                if (
                    values.shape != (len(population), 11)
                    or not np.isfinite(values).all()
                    or (values < 0).any()
                ):
                    raise ValueError("Invalid external primitive forecasts.")
                means[label] = values
                references[f"{label}:{origin.isoformat()}"] = {
                    "trained_through": prediction["trained_through"],
                    "artifact_sha256": checksum,
                }
        banks = {
            label: weekly_banks(
                state.history,
                population,
                origin,
                mean,
                PROTOCOL["seed"] + week,
                PROTOCOL["samples"],
            )
            for label, mean in means.items()
        }
        # Decisions are completely frozen before realized_counts is invoked.
        decisions = []
        for league in range(PROTOCOL["leagues_per_origin"]):
            rng = np.random.default_rng(PROTOCOL["seed"] + 1000 * week + league)
            draft = [population[int(i)] for i in rng.permutation(len(population))[:24]]
            roster, opponent, pool = draft[:8], draft[8:16], draft[16:]
            actions = candidate_actions(roster, pool)
            rosters = [roster_after(roster, action) for action in actions]
            chosen = {}
            for label, bank in banks.items():
                best, scores = choose_action(rosters, opponent, bank)
                chosen[label] = (best, scores[best])
                if label == "recency":
                    chosen["HOLD"] = (0, scores[0])
            decisions.append((league, roster, opponent, pool, actions, rosters, chosen))
        actual = realized_counts(records, population, origin)
        for league, roster, opponent, pool, actions, rosters, chosen in decisions:
            opposition = sum(
                (actual[p] for p in opponent), start=np.zeros(11, dtype=np.int64)
            )[None, :]
            outcomes = [
                compare_totals(
                    sum((actual[p] for p in team), start=np.zeros(11, dtype=np.int64))[
                        None, :
                    ],
                    opposition,
                )
                for team in rosters
            ]
            realized = [credits(o) for o in outcomes]
            best_matchup = max(float(m[0]) for m, _ in realized)
            best_category = max(float(c[0]) for _, c in realized)
            for label, (best, predicted) in chosen.items():
                m, c = realized[best]
                row = {
                    "origin": origin.isoformat(),
                    "league": league,
                    "strategy": label,
                    "add": actions[best][0],
                    "drop": actions[best][1],
                    "action_index": best,
                    "actions": len(actions),
                    "owned": roster,
                    "opponent": opponent,
                    "free_agents": pool,
                    "known_input_hash": digest(
                        canonical(
                            [
                                origin.isoformat(),
                                state.watermark,
                                population,
                                [s["input_hash"] for s in snapshots],
                            ]
                        )
                    ),
                    "realized_outcome_hash": digest(
                        canonical(
                            {p: actual[p].tolist() for p in roster + opponent + pool}
                        )
                    ),
                    "predicted_credit": predicted["matchup_credit"],
                    "matchup_credit": float(m[0]),
                    "matchup_win": bool(m[0] == 1),
                    "matchup_tie": bool(m[0] == 0.5),
                    "category_wins": int((outcomes[best][0] > 0).sum()),
                    "category_credit": float(c[0]),
                    "category_credits": ((outcomes[best][0] + 1) / 2).tolist(),
                    "matchup_regret": best_matchup - float(m[0]),
                    "category_regret": best_category - float(c[0]),
                }
                rows.append(row)
    periods = {
        "2025": summarize([r for r in rows if r["origin"][:4] == "2025"]),
        "2026": summarize([r for r in rows if r["origin"][:4] == "2026"]),
    }
    return {
        "protocol": PROTOCOL,
        "protocol_sha256": digest(canonical(PROTOCOL)),
        "source_provenance": provenance,
        "frozen_model_artifacts": references,
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "summary": summarize(rows),
        "periods": periods,
        "skipped_origins": skipped,
        "decisions": rows,
        "interpretation": (
            "Small overlapping synthetic drafts on shared NBA weeks; descriptive "
            "only. Calendar bootstrap cannot remove ownership/model/schedule "
            "assumptions. No promotion or live performance claim."
        ),
    }
