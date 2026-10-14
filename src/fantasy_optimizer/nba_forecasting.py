"""Prepared population fits of the existing count baselines for actual NBA rows."""

import math
import random
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from fantasy_optimizer.forecasting import (
    STATS,
    ForecastConfig,
    count,
    joint_count_draw,
    recency_weights,
    strength_from_moments,
)
from fantasy_optimizer.historical import COLUMNS, GameObservation, load_history
from fantasy_optimizer.storage import canonical, digest, timestamp

VERSION = "nba-empirical-counts-v1"


def code_hash() -> str:
    return digest(
        "".join(
            Path(__file__).with_name(n).read_text()
            for n in (
                "nba_forecasting.py",
                "forecasting.py",
                "historical.py",
            )
        )
    )


def load_games(
    root: Path, policy: str = "strict"
) -> tuple[list[GameObservation], dict[str, Any]]:
    # Reuse coverage, checksum and duplicate/date gates of the existing adapter.
    _, provenance = load_history(root, policy=policy)
    retrieved = timestamp(provenance["retrieved_at"])
    games = []
    with duckdb.connect() as db:
        db.execute("SET memory_limit='1GB'")
        db.execute("SET threads=2")
        for season in (2025, 2026):
            db.read_parquet(
                str(root / "raw" / f"data/playerlog_{season}.parquet")
            ).create_view("p", replace=True)
            db.read_parquet(
                str(root / "raw" / f"data/gamelog_{season}.parquet")
            ).create_view("t", replace=True)
            rows = db.execute(
                "SELECT p.personId,p.teamId,p.gameId,t.game_date,p.minutes,"
                + ",".join("p." + c for c in COLUMNS)
                + " FROM p JOIN t ON p.gameId=t.game_id AND p.teamId=t.team_id "
                "WHERE starts_with(p.gameId,'002') ORDER BY t.game_date,p.personId"
            ).fetchall()
            for player, team, game, day, minutes, *counts in rows:
                games.append(
                    GameObservation(
                        player,
                        team,
                        game,
                        season,
                        datetime.fromisoformat(day[:10]).date(),
                        tuple(counts),
                        minutes,
                        None,
                        retrieved,
                    )
                )
    return games, provenance


def minutes_value(raw: str | None) -> float | None:
    """Only verified numeric mm:ss or decimal-minute strings; blanks stay unknown."""
    if raw is None or not raw.strip():
        return None
    try:
        if ":" in raw:
            m, s = raw.split(":")
            value = float(m) + float(s) / 60
            if not 0 <= float(s) < 60:
                return None
        else:
            value = float(raw)
        return value if math.isfinite(value) and 0 <= value <= 80 else None
    except ValueError:
        return None


class Population:
    """Fit origin-known sufficient statistics once, with target-excluded peer priors.

    Same recency/empirical-Bayes formulas and joint exposure sampler as the weekly
    engine. Group summaries avoid O(players * games) peer fitting and hashing.
    No present-day roster, minutes or availability enters the count estimator.
    """

    def __init__(
        self, records: list[dict[str, Any]], as_of: datetime, config: ForecastConfig
    ) -> None:
        self.as_of = timestamp(as_of.isoformat())
        self.config = config
        self.groups: dict[str, list[dict[str, Any]]] = {}
        for row in sorted(records, key=lambda r: (r["player"], r["end"], r["id"])):
            if max(row["end"], row["available"]) <= self.as_of:
                self.groups.setdefault(row["player"], []).append(row)
        self.players = sorted(self.groups)
        self.hash = digest(
            canonical(
                [
                    [
                        p,
                        [
                            [
                                r["id"],
                                r["end"].isoformat(),
                                r["available"].isoformat(),
                                r["counts"],
                            ]
                            for r in self.groups[p]
                        ],
                    ]
                    for p in self.players
                ]
            )
        )
        self.means = np.array(
            [
                np.mean([r["counts"] for r in self.groups[p]], axis=0)
                for p in self.players
            ]
        )
        eligible = [p for p in self.players if len(self.groups[p]) >= 2]
        self.eligible = eligible
        self.peer_means = np.array(
            [np.mean([r["counts"] for r in self.groups[p]], axis=0) for p in eligible]
        )
        self.peer_variances = np.array(
            [
                np.var([r["counts"] for r in self.groups[p]], axis=0, ddof=1)
                for p in eligible
            ]
        )
        self.inverses = np.array([1 / len(self.groups[p]) for p in eligible])
        self.weights = {
            p: recency_weights(
                [r["end"] for r in self.groups[p]], self.as_of, config.half_life_days
            )
            for p in self.players
        }
        self.strengths: dict[str, float] = {}
        self.indices = {p: i for i, p in enumerate(self.players)}
        self.eligible_indices = {p: i for i, p in enumerate(eligible)}

    def strength(self, player: str) -> float:
        if player not in self.strengths:
            mask = np.ones(len(self.eligible), dtype=bool)
            if player in self.eligible_indices:
                mask[self.eligible_indices[player]] = False
            if mask.sum() < 2:
                strength = self.config.prior_strength_min
            else:
                strength = strength_from_moments(
                    self.peer_variances[mask].mean(axis=0).tolist(),
                    self.peer_means[mask].var(axis=0, ddof=1).tolist(),
                    [float(self.inverses[mask].mean())] * len(STATS),
                    self.config,
                )
            self.strengths[player] = strength
        return self.strengths[player]

    def predict(
        self, player: str, model: str, *, seed: int, samples: int
    ) -> dict[str, Any]:
        if (
            model not in ("long_run", "recency", "shrinkage")
            or not 32 <= samples <= 10000
            or seed < 0
        ):
            raise ValueError("Invalid model, seed or samples.")
        own = self.groups.get(player, [])
        if not own:
            raise ValueError("At least one origin-known observation is required.")
        weights = (
            [1 / len(own)] * len(own) if model == "long_run" else self.weights[player]
        )
        n_eff = 1 / sum(w * w for w in weights)
        peers = [p for p in self.players if p != player]
        strength = self.strength(player) if model == "shrinkage" and peers else 0.0
        alpha = n_eff / (n_eff + strength)
        own_mean = np.asarray([r["counts"] for r in own]).T @ np.asarray(weights)
        peer_mean = (
            (self.means.sum(axis=0) - self.means[self.indices[player]]) / len(peers)
            if peers
            else own_mean
        )
        expected = alpha * own_mean + (1 - alpha) * peer_mean
        rng = random.Random(int(digest(canonical([seed, player])), 16))
        # Cumulative weights once; previous engine rebuilt these per draw.
        cumulative = np.cumsum(weights).tolist()
        shocks = (0.5, 1.0, 1.5) if len(own) < 3 else (0.75, 1.0, 1.25)
        draws = []
        for _ in range(samples):
            if strength and rng.random() >= alpha:
                support = self.groups[rng.choice(peers)]
                row = rng.choice(support)
            else:
                row = rng.choices(own, cum_weights=cumulative, k=1)[0]
            draws.append(joint_count_draw(row["counts"], rng.choice(shocks)))
        values = np.array([[count(d[s]) for s in STATS] for d in draws])
        intervals = {
            s: [int(np.sort(values[:, i])[int(q * (samples - 1))]) for q in (0.1, 0.9)]
            for i, s in enumerate(STATS)
        }
        minute_values = [v for r in own if (v := r.get("minutes")) is not None]
        minutes = float(np.mean(minute_values)) if minute_values else None
        return {
            "player_key": player,
            "as_of": self.as_of.isoformat(),
            "model": model,
            "model_version": VERSION,
            "config": asdict(self.config),
            "input_hash": self.hash,
            "seed": seed,
            "expected_counts": dict(zip(STATS, expected.tolist(), strict=True)),
            "intervals_80": intervals,
            "joint_samples": draws,
            "sample_sd": dict(
                zip(STATS, values.std(axis=0, ddof=1).tolist(), strict=True)
            ),
            "sample_mean": dict(zip(STATS, values.mean(axis=0).tolist(), strict=True)),
            "history_observations": len(own),
            "effective_observations": n_eff,
            "prior_strength": strength,
            "own_weight": alpha,
            "latest_observation": own[-1]["end"].isoformat(),
            "history_minutes": minutes,
            "segment": "unknown"
            if minutes is None
            else "low"
            if minutes < 15
            else "medium"
            if minutes < 28
            else "high",
            "assumptions": {
                "availability_probability": None,
                "expected_minutes": None,
                "exposure_multipliers": shocks,
                "game_count": None,
                "sampling": "whole joint count vectors; independent games/players",
            },
        }


def game_records(games: list[GameObservation], policy: str) -> list[dict[str, Any]]:
    return [
        {
            "player": f"nba:{g.nba_player_id}",
            "id": g.game_id,
            "end": datetime.combine(
                g.game_date + timedelta(days=1), datetime.min.time(), UTC
            ),
            "available": g.available_at(policy),
            "counts": g.counts,
            "season": g.season,
            "minutes": minutes_value(g.minutes_raw),
        }
        for g in games
    ]
