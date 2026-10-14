"""Lagged NBA features; outcomes and target-game context never enter inputs."""

import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from numpy.typing import NDArray

from fantasy_optimizer.forecasting import (
    STATS,
    ForecastConfig,
    recency_weights,
    strength_from_moments,
)
from fantasy_optimizer.nba_forecasting import load_games, minutes_value
from fantasy_optimizer.registry import atomic_write
from fantasy_optimizer.storage import canonical, digest

Array = NDArray[np.float64]
PRIMITIVES = (
    "2PM",
    "2PX",
    "3PM",
    "3PX",
    "FTM",
    "FTX",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TO",
)
RATE_NAMES = ("2PA", "3PA", "FTA", "REB", "AST", "STL", "BLK", "TO")
CONTEXT_NAMES = (
    "pace",
    "team_pts",
    "opponent_pts",
    "opponent_reb",
    "opponent_ast",
    "opponent_3pa",
    "last_home",
)
FEATURE_NAMES = (
    "log_history",
    "effective_history",
    "staleness_days",
    "minute_missing_fraction",
    "minute_mean",
    "minute_recent3",
    "minute_sd",
    "positive_row_frequency",
    *[f"count14_{s}" for s in STATS],
    *[f"count3_{s}" for s in STATS],
    *[f"count10_{s}" for s in STATS],
    *[f"count_sd_{s}" for s in STATS],
    *[f"rate14_{s}" for s in RATE_NAMES],
    *[f"rate_long_{s}" for s in RATE_NAMES],
    "shot_2p",
    "shot_3p",
    "shot_ft",
    "shot_mass_2p",
    "shot_mass_3p",
    "shot_mass_ft",
    "population_2p",
    "population_3p",
    "population_ft",
    *[f"context_{s}" for s in CONTEXT_NAMES],
    "context_games",
)


def primitive_counts(counts: Array, three_attempts: float) -> Array:
    fgm, fga, ftm, fta, threes, _, reb, ast, stl, blk, tov = counts
    two_makes, two_attempts = fgm - threes, fga - three_attempts
    values = np.array(
        [
            two_makes,
            two_attempts - two_makes,
            threes,
            three_attempts - threes,
            ftm,
            fta - ftm,
            reb,
            ast,
            stl,
            blk,
            tov,
        ],
        dtype=float,
    )
    if (values < 0).any() or not np.isfinite(values).all():
        raise ValueError("Invalid primitive shooting/count record.")
    return values


def counts_from_primitives(values: Array) -> Array:
    result = np.empty((*values.shape[:-1], len(STATS)), dtype=float)
    result[..., 0] = values[..., 0] + values[..., 2]
    result[..., 1] = values[..., :4].sum(axis=-1)
    result[..., 2] = values[..., 4]
    result[..., 3] = values[..., 4] + values[..., 5]
    result[..., 4] = values[..., 2]
    result[..., 5] = 2 * values[..., 0] + 3 * values[..., 2] + values[..., 4]
    result[..., 6:] = values[..., 6:]
    return result


def feature_code_hash() -> str:
    return digest(Path(__file__).read_text())


def observations(
    root: Path, policy: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    games, provenance = load_games(root, policy)
    extra = {}
    with duckdb.connect() as db:
        db.execute("SET memory_limit='1GB'")
        db.execute("SET threads=2")
        for season in (2025, 2026):
            player = str(root / "raw" / f"data/playerlog_{season}.parquet")
            team = str(root / "raw" / f"data/gamelog_{season}.parquet")
            rows = db.execute(
                "SELECT p.personId,p.gameId,p.threePointersAttempted,t.pace,t.pts,"
                "o.pts,o.reb,o.ast,o.fg3a,t.matchup FROM read_parquet(?) p "
                "JOIN read_parquet(?) t ON p.gameId=t.game_id AND p.teamId=t.team_id "
                "JOIN read_parquet(?) o ON o.game_id=t.game_id "
                "AND o.team_id<>t.team_id "
                "WHERE starts_with(p.gameId,'002')",
                [player, team, team],
            ).fetchall()
            for person, game, attempts, *context in rows:
                key = (person, game)
                if key in extra:
                    raise ValueError("Ambiguous team/opponent join.")
                matchup = str(context.pop())
                home = 0.0 if " @ " in matchup else 1.0 if " vs. " in matchup else None
                context.append(home)
                extra[key] = (attempts, context)
    if len(extra) != len(games):
        raise ValueError("Context join coverage differs from validated observations.")
    records: list[dict[str, Any]] = []
    for g in games:
        attempts, context = extra[(g.nba_player_id, g.game_id)]
        counts = np.asarray(g.counts, dtype=float)
        primitive = primitive_counts(counts, attempts)
        records.append(
            {
                "player": f"nba:{g.nba_player_id}",
                "id": g.game_id,
                "team": g.team_id,
                "season": g.season,
                "day": datetime.combine(g.game_date, datetime.min.time(), UTC),
                "end": datetime.combine(
                    g.game_date + timedelta(days=1), datetime.min.time(), UTC
                ),
                "available": g.available_at(policy),
                "counts": counts,
                "primitive": primitive,
                "minutes": minutes_value(g.minutes_raw),
                "context": context,
            }
        )
    provenance = {
        **provenance,
        "context_source": "same verified player/team Parquet; lagged only",
        "unknown_minute_rows": sum(r["minutes"] is None for r in records),
        "unknown_minutes_nonzero_rows": int(
            sum(r["minutes"] is None and r["counts"].sum() > 0 for r in records)
        ),
    }
    return records, provenance


class FeatureState:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.pending = sorted(
            records, key=lambda r: (max(r["end"], r["available"]), r["player"], r["id"])
        )
        self.cursor = 0
        self.origin = datetime.min.replace(tzinfo=UTC)
        self.history: dict[str, list[dict[str, Any]]] = {}
        self.teams: dict[int, list[dict[str, Any]]] = {}
        self.team_seen: set[tuple[int, str]] = set()
        self.watermark = digest("advanced-known-history-v1")
        self.peer_players: list[str] = []
        self.peer_means: Array = np.empty((0, len(STATS)))
        self.peer_primitive: Array = np.empty((0, len(PRIMITIVES)))
        self.peer_var: Array = np.empty((0, len(STATS)))
        self.peer_inverse: Array = np.empty(0)
        self.global_primitive = np.zeros(len(PRIMITIVES))

    def advance(self, origin: datetime) -> None:
        if origin < self.origin:
            raise ValueError("Feature state cannot move backwards in time.")
        self.origin = origin
        changed = False
        changed_players: set[str] = set()
        changed_teams: set[int] = set()
        while self.cursor < len(self.pending):
            r = self.pending[self.cursor]
            if max(r["end"], r["available"]) > origin:
                break
            self.cursor += 1
            self.history.setdefault(r["player"], []).append(r)
            changed_players.add(r["player"])
            self.global_primitive += r["primitive"]
            key = (r["team"], r["id"])
            if key not in self.team_seen:
                self.team_seen.add(key)
                self.teams.setdefault(r["team"], []).append(r)
                changed_teams.add(r["team"])
            self.watermark = digest(
                canonical(
                    [
                        self.watermark,
                        r["player"],
                        r["id"],
                        r["end"].isoformat(),
                        r["available"].isoformat(),
                        r["counts"].tolist(),
                        r["primitive"].tolist(),
                        r["minutes"],
                        r["context"],
                    ]
                )
            )
            changed = True
        if changed:
            for p in changed_players:
                self.history[p].sort(key=lambda r: (r["end"], r["id"]))
            for t in changed_teams:
                self.teams[t].sort(key=lambda r: (r["end"], r["id"]))
            self.peer_players = sorted(self.history)
            self.peer_means = np.array(
                [
                    np.mean([r["counts"] for r in self.history[p]], axis=0)
                    for p in self.peer_players
                ]
            )
            self.peer_primitive = np.array(
                [
                    np.mean([r["primitive"] for r in self.history[p]], axis=0)
                    for p in self.peer_players
                ]
            )
            self.peer_var = np.array(
                [
                    np.var([r["counts"] for r in self.history[p]], axis=0, ddof=1)
                    if len(self.history[p]) > 1
                    else np.zeros(len(STATS))
                    for p in self.peer_players
                ]
            )
            self.peer_inverse = np.array(
                [1 / len(self.history[p]) for p in self.peer_players]
            )

    def snapshot(self, player: str, origin: datetime) -> dict[str, Any] | None:
        if origin != self.origin:
            raise ValueError("Advance feature state to the requested origin first.")
        own = self.history.get(player, [])
        if not own:
            return None
        counts = np.array([r["counts"] for r in own])
        primitive = np.array([r["primitive"] for r in own])
        w = np.asarray(recency_weights([r["end"] for r in own], origin, 14))
        recency = w @ counts
        n_eff = 1 / float(w @ w)
        known_mins = np.array(
            [r["minutes"] if r["minutes"] is not None else np.nan for r in own]
        )
        valid = np.isfinite(known_mins)
        positive = valid & (known_mins > 0) & (counts.sum(axis=1) > 0)
        m = known_mins[positive]
        minute_mean = float(known_mins[valid].mean()) if valid.any() else 0.0
        minute_recent = float(known_mins[valid][-3:].mean()) if valid.any() else 0.0
        minute_sd = float(known_mins[valid].std()) if valid.any() else 0.0
        conditional_minutes = (
            float(w[positive] @ m / w[positive].sum()) if positive.any() else 0.0
        )
        sums = w @ primitive
        attempt = np.array([sums[:2].sum(), sums[2:4].sum(), sums[4:6].sum()])
        makes = sums[[0, 2, 4]]
        peer_primitive = self.global_primitive - primitive.sum(axis=0)
        global_attempt = np.array(
            [
                peer_primitive[:2].sum(),
                peer_primitive[2:4].sum(),
                peer_primitive[4:6].sum(),
            ]
        )
        population_shots = np.divide(
            peer_primitive[[0, 2, 4]],
            global_attempt,
            out=np.array([0.5, 0.35, 0.75]),
            where=global_attempt > 0,
        )
        # Fifty attempted shots is a predeclared statistical prior, not future accuracy.
        weighted_attempt_mass = attempt * n_eff
        shot = (makes * n_eff + 50 * population_shots) / (weighted_attempt_mass + 50)
        total_minutes = float(w[positive] @ m) if positive.any() else 0.0
        rate_sums = (
            w[positive] @ primitive[positive] if positive.any() else np.zeros(11)
        )
        rate = np.r_[
            rate_sums[:2].sum(),
            rate_sums[2:4].sum(),
            rate_sums[4:6].sum(),
            rate_sums[6:],
        ] / max(total_minutes, 1e-6)
        long_min = float(known_mins[positive].sum()) if positive.any() else 0.0
        long_sums = primitive[positive].sum(axis=0)
        long_rate = np.r_[
            long_sums[:2].sum(),
            long_sums[2:4].sum(),
            long_sums[4:6].sum(),
            long_sums[6:],
        ] / max(long_min, 1e-6)
        row_probability = float(w @ (counts.sum(axis=1) > 0))
        context_rows = self.teams.get(own[-1]["team"], [])[-6:]
        context = []
        for i in range(len(CONTEXT_NAMES)):
            vals = [
                float(r["context"][i])
                for r in context_rows
                if r["context"][i] is not None and math.isfinite(float(r["context"][i]))
            ]
            context.append(float(np.mean(vals)) if vals else 0.0)
        values = np.r_[
            math.log1p(len(own)),
            n_eff,
            min(365, (origin - own[-1]["end"]).total_seconds() / 86400),
            1 - float(valid.mean()),
            minute_mean,
            minute_recent,
            minute_sd,
            row_probability,
            recency,
            counts[-3:].mean(axis=0),
            counts[-10:].mean(axis=0),
            counts.std(axis=0),
            rate,
            long_rate,
            shot,
            weighted_attempt_mass,
            population_shots,
            context,
            len(context_rows),
        ].astype(float)
        if len(values) != len(FEATURE_NAMES) or not np.isfinite(values).all():
            raise ValueError("Invalid point-in-time feature snapshot.")
        base = np.r_[row_probability, conditional_minutes, rate, shot].astype(float)
        season = origin.year + int(origin.month >= 7)
        current = [r["counts"] for r in own if r["season"] == season]
        season_mean = np.mean(current, axis=0) if current else counts.mean(axis=0)
        mask = np.array(
            [p != player and len(self.history[p]) >= 2 for p in self.peer_players]
        )
        strength = (
            2.0
            if mask.sum() < 2
            else strength_from_moments(
                self.peer_var[mask].mean(axis=0).tolist(),
                self.peer_means[mask].var(axis=0, ddof=1).tolist(),
                [float(self.peer_inverse[mask].mean())] * len(STATS),
                ForecastConfig(),
            )
        )
        peers = [i for i, p in enumerate(self.peer_players) if p != player]
        peer_mean = self.peer_means[peers].mean(axis=0) if peers else recency
        alpha = n_eff / (n_eff + strength) if peers else 1.0
        group = (
            "unknown"
            if not valid.any()
            else "low"
            if minute_mean < 15
            else "medium"
            if minute_mean < 28
            else "high"
        )
        return {
            "x": values,
            "base": base,
            "recency_primitive": sums,
            "season_primitive": np.mean(
                [r["primitive"] for r in own if r["season"] == season], axis=0
            )
            if current
            else primitive.mean(axis=0),
            "shrinkage_primitive": alpha * sums
            + (1 - alpha)
            * (self.peer_primitive[peers].mean(axis=0) if peers else sums),
            "recency": recency,
            "season_to_date": np.asarray(season_mean),
            "shrinkage": alpha * recency + (1 - alpha) * peer_mean,
            "minutes_group": group,
            "history": len(own),
            "minutes_history": int(valid.sum()),
            "latest": own[-1]["end"].isoformat(),
            "input_hash": digest(
                canonical([player, origin.isoformat(), self.watermark, values.tolist()])
            ),
            "shot_population": population_shots,
        }


def target_components(row: dict[str, Any]) -> tuple[Array, Array]:
    y = np.zeros(13)
    weights = np.zeros(13)
    p = row["primitive"]
    m = row["minutes"]
    y[0] = float(row["counts"].sum() > 0)
    weights[0] = 1
    if m is not None and m >= 1 and y[0] > 0:
        y[1] = m
        weights[1] = 1
        y[2:10] = np.r_[p[:2].sum(), p[2:4].sum(), p[4:6].sum(), p[6:]] / m
        weights[2:10] = min(m / 20, 3)
    attempts = np.array([p[:2].sum(), p[2:4].sum(), p[4:6].sum()])
    y[10:13] = np.divide(p[[0, 2, 4]], attempts, out=np.zeros(3), where=attempts > 0)
    weights[10:13] = attempts
    return y, weights


def prepare_dataset(root: Path) -> dict[str, Any]:
    records, data = observations(root, "retrospective_next_day")
    identity = digest(canonical([feature_code_hash(), data]))
    directory = root / "features"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"advanced-{identity}.npz"
    meta = directory / f"advanced-{identity}.json"
    if path.exists() and meta.exists():
        info = json.loads(meta.read_text())
        if hashlib.sha256(path.read_bytes()).hexdigest() == info["arrays_sha256"]:
            with np.load(path, allow_pickle=False) as saved:
                arrays = {k: saved[k] for k in saved.files}
            return {**arrays, **info, "cache_hit": True}
    state = FeatureState(records)
    cases = []
    columns: dict[str, list[Any]] = {
        k: []
        for k in (
            "x",
            "base",
            "y",
            "weights",
            "counts",
            "primitive",
            "recency_primitive",
            "season_primitive",
            "shrinkage_primitive",
            "recency",
            "season_to_date",
            "shrinkage",
            "shot_population",
        )
    }
    for row in sorted(records, key=lambda r: (r["day"], r["player"], r["id"])):
        origin = row["day"]
        state.advance(origin)
        snapshot = state.snapshot(row["player"], origin)
        if snapshot is None:
            continue
        y, weights = target_components(row)
        for k in (
            "x",
            "base",
            "recency_primitive",
            "season_primitive",
            "shrinkage_primitive",
            "recency",
            "season_to_date",
            "shrinkage",
            "shot_population",
        ):
            columns[k].append(snapshot[k])
        for k, v in [
            ("y", y),
            ("weights", weights),
            ("counts", row["counts"]),
            ("primitive", row["primitive"]),
        ]:
            columns[k].append(v)
        cases.append(
            {
                "player_key": row["player"],
                "id": row["id"],
                "as_of": origin.isoformat(),
                "outcome_available": max(row["end"], row["available"]).isoformat(),
                "input_hash": snapshot["input_hash"],
                "outcome_hash": digest(
                    canonical(
                        [
                            row["player"],
                            row["id"],
                            row["counts"].tolist(),
                            row["minutes"],
                        ]
                    )
                ),
                "history": snapshot["history"],
                "minutes_group": snapshot["minutes_group"],
                "minutes": row["minutes"],
            }
        )
    arrays = {k: np.asarray(v, dtype=float) for k, v in columns.items()}
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".npz", delete=False) as tmp:
        np.savez_compressed(tmp, **arrays)
        temporary = tmp.name
    os.replace(temporary, path)
    info = {
        "identity": identity,
        "data": data,
        "cases": cases,
        "all_observations": len(records),
        "all_players": len({r["player"] for r in records}),
        "arrays_artifact": str(path),
        "arrays_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "feature_names": FEATURE_NAMES,
    }
    atomic_write(meta, info)
    return {**arrays, **info, "cache_hit": False}
