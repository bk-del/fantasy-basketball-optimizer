"""Checksum-gated cached ESPN research rows; source-row exposure is conditional."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from fantasy_optimizer.advanced_features import primitive_counts
from fantasy_optimizer.forecasting import validate_counts
from fantasy_optimizer.nba_forecasting import minutes_value
from fantasy_optimizer.storage import canonical, digest, timestamp

VERSION = "cached-espn-nba-intelligence-v1"
COMPLETE_SEASONS = (2019, 2021, 2022, 2023, 2024, 2025)
COUNT_COLUMNS = (
    "fgmplyr",
    "fgaplyr",
    "ftmplyr",
    "ftaplyr",
    "fg3mplyr",
    "pts",
    "rebounder",
    "assister",
    "stlr",
    "blockplyr",
    "tov1",
)


def verified_manifest(root: Path) -> dict[str, Any]:
    """Verify immutable source bytes before issuing any observational claims."""
    manifest: dict[str, Any] = json.loads((root / "manifest.json").read_text())
    paths: set[str] = set()
    for entry in manifest["files"]:
        path = Path(entry["path"])
        if path.is_absolute() or ".." in path.parts or str(path) in paths:
            raise ValueError("Unsafe or duplicate source-manifest path.")
        paths.add(str(path))
        payload = (root / "raw" / path).read_bytes()
        if len(payload) != entry["bytes"] or (
            hashlib.sha256(payload).hexdigest() != entry["sha256"]
        ):
            raise ValueError(f"Source checksum mismatch: {path}")
    timestamp(manifest["retrieved_at"])
    return manifest


def _views(db: duckdb.DuckDBPyConnection, root: Path) -> None:
    for name, file in (("p", "player_box"), ("e", "team_box")):
        db.read_parquet(str(root / "raw/data/espn" / f"{file}.parquet")).create_view(
            name
        )


def _team_view(db: duckdb.DuckDBPyConnection, root: Path, year: int) -> None:
    db.read_parquet(str(root / "raw/data" / f"gamelog_{year}.parquet")).create_view(
        "t", replace=True
    )


def season_quality(db: duckdb.DuckDBPyConnection, year: int) -> dict[str, Any]:
    """Measure source completeness against independent NBA-ID team-game rows."""
    nba = db.execute(
        "SELECT count(*),count(DISTINCT game_id),"
        "count(*)-count(DISTINCT (game_id,team_id)),"
        "count(DISTINCT team_id),min(game_date),max(game_date) FROM t "
        "WHERE starts_with(game_id,'002')"
    ).fetchone()
    assert nba is not None
    quality = db.execute(
        "SELECT count(*),count(DISTINCT p.game_id),count(DISTINCT p.player_id),"
        "count(*)-count(DISTINCT (p.game_id,p.player_id)),"
        "count(*) FILTER(WHERE e.team_id IS NULL OR t.team_id IS NULL),"
        "count(*) FILTER(WHERE p.team<>e.tmName OR "
        "(p.team_id IS NOT NULL AND p.team_id<>e.team_id)),"
        "count(*) FILTER(WHERE p.team_id IS NULL),"
        "count(*) FILTER(WHERE p.pts<>2*p.fgmplyr+p.fg3mplyr+p.ftmplyr),"
        "count(*) FILTER(WHERE p.fgmplyr>p.fgaplyr OR p.ftmplyr>p.ftaplyr "
        "OR p.fg3mplyr>p.fgmplyr OR p.fg3mplyr>p.fg3aplyr "
        "OR p.fg3aplyr>p.fgaplyr),"
        "count(*) FILTER(WHERE p.played<>1),"
        "count(*) FILTER(WHERE p.starter IS NULL OR p.played IS NULL) "
        "FROM p LEFT JOIN e ON p.season=e.season AND p.game_id=e.game_id "
        "AND p.home=e.homeTm LEFT JOIN t ON p.game_id=t.game_id "
        "AND e.team_id=t.team_id "
        "WHERE p.season=? AND starts_with(p.game_id,'002')",
        [year],
    ).fetchone()
    assert quality is not None
    names = (
        "rows",
        "games",
        "players",
        "duplicate_or_multiplied_player_game_rows",
        "unmatched_team_rows",
        "team_identity_disagreements",
        "source_null_team_ids",
        "points_identity_failures",
        "shooting_failures",
        "played_not_one_rows",
        "unknown_starter_or_played_rows",
    )
    result = dict(zip(names, quality, strict=True))
    missing = db.execute(
        "SELECT count(*) FROM (SELECT DISTINCT game_id FROM t "
        "WHERE starts_with(game_id,'002') EXCEPT SELECT DISTINCT game_id "
        "FROM p WHERE season=? AND starts_with(game_id,'002'))",
        [year],
    ).fetchone()
    assert missing is not None
    result.update(
        nba_team_rows=nba[0],
        nba_games=nba[1],
        nba_duplicate_team_rows=nba[2],
        nba_teams=nba[3],
        first_game_date=nba[4][:10],
        last_game_date=nba[5][:10],
        missing_games=missing[0],
    )
    result["complete"] = (
        result["games"] == nba[1]
        and missing[0] == 0
        and nba[2] == 0
        and nba[0] == 2 * nba[1]
        and nba[3] == 30
        and result["rows"] > 0
        and not any(
            result[key]
            for key in (
                "duplicate_or_multiplied_player_game_rows",
                "unmatched_team_rows",
                "team_identity_disagreements",
                "points_identity_failures",
                "shooting_failures",
                "unknown_starter_or_played_rows",
            )
        )
    )
    return result


def audit(root: Path) -> dict[str, Any]:
    manifest = verified_manifest(root)
    result: dict[str, Any] = {
        "version": VERSION,
        "commit": manifest["commit"],
        "retrieved_at": manifest["retrieved_at"],
        "manifest_sha256": hashlib.sha256(
            (root / "manifest.json").read_bytes()
        ).hexdigest(),
        "verified_files": len(manifest["files"]),
        "verified_bytes": sum(e["bytes"] for e in manifest["files"]),
        "espn_seasons": {},
        "nba_playerlog_seasons": {},
        "historical_publication_timestamp": None,
    }
    with duckdb.connect() as db:
        db.execute("SET memory_limit='1GB'")
        db.execute("SET threads=2")
        _views(db, root)
        for year in range(2019, 2027):
            _team_view(db, root, year)
            result["espn_seasons"][str(year)] = season_quality(db, year)
        for year in range(2010, 2027):
            row = db.execute(
                "SELECT count(*),count(DISTINCT gameId),"
                "count(*)-count(DISTINCT (gameId,personId)) "
                "FROM read_parquet(?) WHERE starts_with(gameId,'002')",
                [str(root / "raw/data" / f"playerlog_{year}.parquet")],
            ).fetchone()
            assert row is not None
            result["nba_playerlog_seasons"][str(year)] = dict(
                zip(("rows", "games", "duplicate_player_games"), row, strict=True)
            )
    return result


def observations(
    root: Path, policy: str = "strict", seasons: tuple[int, ...] = COMPLETE_SEASONS
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return advanced-feature-compatible rows from complete cached partitions.

    These are ESPN-origin NBA-ID rows, not an inferred roster/availability panel.
    A game key has an explicit source namespace even after the exact NBA-ID join.
    """
    if policy not in ("strict", "retrospective_next_day"):
        raise ValueError("Unknown availability policy.")
    if not seasons or len(set(seasons)) != len(seasons):
        raise ValueError("Specify unique nonempty historical seasons.")
    report = audit(root)
    for year in seasons:
        if not report["espn_seasons"].get(str(year), {}).get("complete"):
            raise ValueError(f"Incomplete or invalid ESPN source season: {year}")
    retrieved = timestamp(report["retrieved_at"])
    records: list[dict[str, Any]] = []
    with duckdb.connect() as db:
        db.execute("SET memory_limit='1GB'")
        db.execute("SET threads=2")
        _views(db, root)
        for year in sorted(seasons):
            _team_view(db, root, year)
            rows = db.execute(
                "SELECT p.player_id,e.team_id,p.game_id,t.game_date,"
                "p.minutes_played,p.fg3aplyr,p.starter,p.played,"
                + ",".join("p." + col for col in COUNT_COLUMNS)
                + ",t.pace,t.pts,o.pts,o.reb,o.ast,o.fg3a,p.home "
                "FROM p JOIN e ON p.season=e.season AND p.game_id=e.game_id "
                "AND p.home=e.homeTm JOIN t ON p.game_id=t.game_id "
                "AND e.team_id=t.team_id JOIN t o ON o.game_id=t.game_id "
                "AND o.team_id<>t.team_id WHERE p.season=? "
                "AND starts_with(p.game_id,'002') ORDER BY t.game_date,p.player_id",
                [year],
            ).fetchall()
            for (
                player,
                team,
                game,
                raw_day,
                mins,
                attempts,
                starter,
                played,
                *v,
            ) in rows:
                if (
                    type(player) is not int
                    or player <= 0
                    or type(team) is not int
                    or team <= 0
                    or not re.fullmatch(r"002\d{7}", game)
                    or starter not in (0, 1)
                    or played not in (0, 1)
                ):
                    raise ValueError("Invalid ESPN identity or source flags.")
                counts_raw, context = v[:11], v[11:]
                if any(x is None or float(x) != int(x) for x in counts_raw):
                    raise ValueError("Unknown or noninteger ESPN counts.")
                counts = tuple(int(x) for x in counts_raw)
                validate_counts(counts)
                if counts[5] != 2 * counts[0] + counts[4] + counts[2]:
                    raise ValueError("ESPN points identity mismatch.")
                day = datetime.fromisoformat(raw_day[:10]).replace(tzinfo=UTC)
                if (
                    not datetime(year - 1, 7, 1, tzinfo=UTC)
                    <= day
                    < datetime(year, 10, 1, tzinfo=UTC)
                ):
                    raise ValueError("Game event date disagrees with season.")
                end = day + timedelta(days=1)
                array = np.asarray(counts, dtype=float)
                records.append(
                    {
                        "player": f"nba:{player}",
                        "id": f"espn:{game}",
                        "nba_game_id": game,
                        "team": team,
                        "season": year,
                        "day": day,
                        "end": end,
                        "available": retrieved
                        if policy == "strict"
                        else (end + timedelta(hours=12)),
                        "counts": array,
                        "primitive": primitive_counts(array, attempts),
                        "minutes": minutes_value(mins),
                        "context": context,
                        "starter": bool(starter),
                        "source_played": bool(played),
                        "observed_at": None,
                        "ingested_at": retrieved,
                        "availability_status": "unknown",
                        "source": "cached_espn_player_box",
                    }
                )
    provenance = {
        **report,
        "adapter_version": VERSION,
        "seasons": list(seasons),
        "availability_policy": policy,
        "source_hash": digest(canonical([report["manifest_sha256"], VERSION, seasons])),
        "code_hash": digest(Path(__file__).read_text()),
        "rows": len(records),
        "players": len({r["player"] for r in records}),
        "unknown_minute_rows": sum(r["minutes"] is None for r in records),
        "exposure": "next recorded ESPN player-game row; not pregame participation",
        "team_mapping": "exact season/game/home join; NBA game/team ID cross-check",
        "historical_publication_assumption": (
            None
            if policy == "strict"
            else "next calendar date noon UTC; virtual ingestion"
        ),
    }
    return records, provenance
