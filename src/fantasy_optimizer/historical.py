"""Offline NBA game adapter; retrospective availability is an explicit assumption."""

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from fantasy_optimizer.forecasting import (
    STATS,
    Forecast,
    ForecastConfig,
    Window,
    count,
    forecast,
    known_windows,
    validate_counts,
)
from fantasy_optimizer.storage import canonical, digest, timestamp

ADAPTER_VERSION = "nba-weekly-v1"
COLUMNS = (
    "fieldGoalsMade",
    "fieldGoalsAttempted",
    "freeThrowsMade",
    "freeThrowsAttempted",
    "threePointersMade",
    "points",
    "reboundsTotal",
    "assists",
    "steals",
    "blocks",
    "turnovers",
)


@dataclass(frozen=True)
class IdentityLink:
    """A verified exact-ID link scoped to a Yahoo season and knowledge time."""

    yahoo_player_key: str
    nba_player_id: int
    season: int
    observed_at: datetime
    ingested_at: datetime
    evidence: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"\d+\.p\.\d+", self.yahoo_player_key):
            raise ValueError("Expected a stable Yahoo player key.")
        if type(self.nba_player_id) is not int or self.nba_player_id <= 0:
            raise ValueError("Expected a positive NBA player ID.")
        if not self.evidence.strip() or not 2010 <= self.season <= 2100:
            raise ValueError("Exact-ID evidence and season are required.")
        if timestamp(self.observed_at.isoformat()) > timestamp(
            self.ingested_at.isoformat()
        ):
            raise ValueError("Identity ingestion precedes observation.")


class IdentityMap:
    def __init__(self, links: list[IdentityLink]) -> None:
        self.links = tuple(links)
        by_yahoo: dict[tuple[int, str], int] = {}
        by_nba: dict[tuple[int, int], str] = {}
        for link in links:
            key = (link.season, link.yahoo_player_key)
            reverse = (link.season, link.nba_player_id)
            if by_yahoo.get(key, link.nba_player_id) != link.nba_player_id:
                raise ValueError("Conflicting Yahoo/NBA identity link.")
            if by_nba.get(reverse, link.yahoo_player_key) != link.yahoo_player_key:
                raise ValueError("Ambiguous NBA/Yahoo identity link.")
            by_yahoo[key] = link.nba_player_id
            by_nba[reverse] = link.yahoo_player_key

    def nba_id(self, yahoo_key: str, season: int, as_of: datetime) -> int:
        as_of = timestamp(as_of.isoformat())
        for link in self.links:
            if (
                link.yahoo_player_key == yahoo_key
                and link.season == season
                and max(link.observed_at, link.ingested_at) <= as_of
            ):
                return link.nba_player_id
        raise ValueError(
            "No verified identity known at cutoff; name matching is unavailable."
        )

    @classmethod
    def load(cls, path: Path) -> "IdentityMap":
        data = json.loads(path.read_text())
        if data["version"] != 1:
            raise ValueError("Unsupported identity map version.")
        return cls(
            [
                IdentityLink(
                    row["yahoo_player_key"],
                    row["nba_player_id"],
                    row["season"],
                    timestamp(row["observed_at"]),
                    timestamp(row["ingested_at"]),
                    row["evidence"],
                )
                for row in data["links"]
            ]
        )


@dataclass(frozen=True)
class GameObservation:
    nba_player_id: int
    team_id: int
    game_id: str
    season: int
    game_date: date
    counts: tuple[int | None, ...]
    minutes_raw: str | None
    observed_at: datetime | None
    ingested_at: datetime

    def __post_init__(self) -> None:
        if any(
            type(v) is not int or v <= 0 for v in (self.nba_player_id, self.team_id)
        ):
            raise ValueError("Invalid NBA identifiers.")
        if not re.fullmatch(r"002\d{7}", self.game_id):
            raise ValueError("Only regular-season game identifiers are supported.")
        if not date(self.season - 1, 7, 1) <= self.game_date < date(self.season, 7, 1):
            raise ValueError("Game date disagrees with season.")
        validate_counts(self.counts)
        timestamp(self.ingested_at.isoformat())
        if self.observed_at is not None:
            if timestamp(self.observed_at.isoformat()) > self.ingested_at:
                raise ValueError("Publication follows ingestion.")
            if self.observed_at.date() < self.game_date:
                raise ValueError("Publication precedes game date.")

    def available_at(self, policy: str) -> datetime:
        if policy == "strict":
            return max(self.observed_at or self.ingested_at, self.ingested_at)
        if policy != "retrospective_next_day":
            raise ValueError("Unknown availability policy.")
        # Date labels are not tip-off times. Noon UTC on the following date is
        # an assumed publication/virtual ingestion boundary, never source evidence.
        assumed = datetime.combine(
            self.game_date + timedelta(days=1), datetime.min.time(), UTC
        )
        assumed += timedelta(hours=12)
        return self.observed_at if self.observed_at is not None else assumed


@dataclass(frozen=True)
class HistoricalWindow:
    season: int
    window: Window
    game_ids: tuple[str, ...]
    team_ids: tuple[int, ...]
    source_retrieved_at: datetime
    availability_policy: str


def aggregate_games(
    games: list[GameObservation], policy: str
) -> list[HistoricalWindow]:
    """One conversion path; no absent player-week is synthesized as zero."""
    groups: dict[tuple[int, int, datetime], list[GameObservation]] = {}
    seen: dict[tuple[int, str], GameObservation] = {}
    for game in games:
        key = (game.nba_player_id, game.game_id)
        if key in seen:
            if seen[key] != game:
                raise ValueError(
                    "Conflicting player/game record, including team changes."
                )
            continue
        seen[key] = game
        start = datetime.combine(game.game_date, datetime.min.time(), UTC)
        start += timedelta(hours=12) - timedelta(days=start.weekday())
        groups.setdefault((game.season, game.nba_player_id, start), []).append(game)
    result = []
    for (season, player, start), rows in sorted(groups.items()):
        end = start + timedelta(days=7)
        counts = tuple(
            None
            if any(r.counts[i] is None for r in rows)
            else sum(count(r.counts[i]) for r in rows)
            for i in range(len(STATS))
        )
        available = max(end, *(r.available_at(policy) for r in rows))
        result.append(
            HistoricalWindow(
                season,
                Window(f"nba:{player}", start, end, available, available, counts),
                tuple(sorted(r.game_id for r in rows)),
                tuple(sorted({r.team_id for r in rows})),
                max(r.ingested_at for r in rows),
                policy,
            )
        )
    return result


def load_history(
    root: Path, *, policy: str = "strict"
) -> tuple[list[HistoricalWindow], dict[str, Any]]:
    """Verify four existing partitions; cache only derived windows, never raw games."""
    if policy not in ("strict", "retrospective_next_day"):
        raise ValueError("Unknown availability policy.")
    manifest = json.loads((root / "manifest.json").read_text())
    entries = {e["path"]: e for e in manifest["files"]}
    paths = [
        f"data/{kind}_{year}.parquet"
        for year in (2025, 2026)
        for kind in ("playerlog", "gamelog")
    ]
    for path in paths:
        actual = hashlib.sha256((root / "raw" / path).read_bytes()).hexdigest()
        if actual != entries[path]["sha256"]:
            raise ValueError(f"Historical partition checksum mismatch: {path}")
    source_hash = digest(
        canonical(
            {
                "commit": manifest["commit"],
                "files": {p: entries[p]["sha256"] for p in paths},
                "retrieved_at": manifest["retrieved_at"],
            }
        )
    )
    code_hash = digest(
        Path(__file__).read_text()
        + Path(__file__).with_name("forecasting.py").read_text()
    )
    cache_hash = digest(canonical([ADAPTER_VERSION, code_hash, source_hash, policy]))
    cache = root / "features" / f"{cache_hash}.parquet"
    metadata: dict[str, Any] = {
        "adapter_version": ADAPTER_VERSION,
        "source_hash": source_hash,
        "code_hash": code_hash,
        "availability_policy": policy,
        "retrieved_at": manifest["retrieved_at"],
        "seasons": {},
    }
    retrieved = timestamp(manifest["retrieved_at"])
    with duckdb.connect() as db:
        db.execute("SET memory_limit='1GB'")
        db.execute("SET threads=2")
        if cache.exists():
            # Cache embeds its metadata; Parquet corruption fails closed.
            saved = db.execute("SELECT * FROM read_parquet(?)", [str(cache)]).fetchall()
            result = [_cached_window(row, retrieved, policy) for row in saved]
            metadata["seasons"] = json.loads(saved[0][-1])
            return result, metadata
        games = []
        bounds = {}
        for season in (2025, 2026):
            player_path = str(root / "raw" / f"data/playerlog_{season}.parquet")
            team_path = str(root / "raw" / f"data/gamelog_{season}.parquet")
            db.read_parquet(player_path).create_view("players", replace=True)
            db.read_parquet(team_path).create_view("teams", replace=True)
            team_rows = db.execute(
                "SELECT game_id, team_id, game_date, season_year FROM teams "
                "WHERE starts_with(game_id, '002')"
            ).fetchall()
            dates: dict[tuple[str, int], date] = {}
            for game_id, team_id, game_date, label in team_rows:
                if (
                    game_id,
                    team_id,
                ) in dates or label != f"{season - 1}-{str(season)[-2:]}":
                    raise ValueError(
                        "Duplicate team/game or inconsistent season label."
                    )
                dates[(game_id, team_id)] = date.fromisoformat(game_date[:10])
            if len(dates) != 2460 or len({k[0] for k in dates}) != 1230:
                raise ValueError("Regular-season team-game coverage gate failed.")
            bounds[season] = (min(dates.values()), max(dates.values()))
            columns = ", ".join(COLUMNS)
            player_rows = db.execute(
                f"SELECT personId, teamId, gameId, minutes, {columns} "
                "FROM players WHERE starts_with(gameId, '002')"
            ).fetchall()
            seen = set()
            for player, team, game, minutes, *counts in player_rows:
                if (player, game) in seen or (game, team) not in dates:
                    raise ValueError("Duplicate player/game or missing date/team join.")
                seen.add((player, game))
                games.append(
                    GameObservation(
                        player,
                        team,
                        game,
                        season,
                        dates[(game, team)],
                        tuple(counts),
                        minutes,
                        None,
                        retrieved,
                    )
                )
            metadata["seasons"][str(season)] = {
                "regular_season_games": 1230,
                "player_rows": len(player_rows),
                "players": len({r[0] for r in player_rows}),
                "first_date": bounds[season][0].isoformat(),
                "last_date": bounds[season][1].isoformat(),
                "unmatched_dates": 0,
                "duplicate_player_games": 0,
                "publication_timestamps_known": 0,
            }
        windows = aggregate_games(games, policy)
        # Exclude boundary weeks that overlap dates outside the covered regular season.
        windows = [
            r
            for r in windows
            if r.window.start.date() >= bounds[r.season][0]
            and (r.window.end - timedelta(days=1)).date() <= bounds[r.season][1]
        ]
        db.execute(
            "CREATE TEMP TABLE features (season INTEGER, player VARCHAR, "
            "start VARCHAR, "
            "finish VARCHAR, available VARCHAR, counts INTEGER[], games VARCHAR[], "
            "teams INTEGER[], metadata VARCHAR)"
        )
        cache.parent.mkdir(parents=True, exist_ok=True)
        buffer = cache.with_suffix(".json.tmp")
        temporary = cache.with_suffix(".tmp.parquet")
        try:
            buffer.write_text(
                canonical(
                    [
                        {
                            "season": r.season,
                            "player": r.window.player_key,
                            "start": r.window.start.isoformat(),
                            "finish": r.window.end.isoformat(),
                            "available": r.window.observed_at.isoformat(),
                            "counts": list(r.window.counts),
                            "games": list(r.game_ids),
                            "teams": list(r.team_ids),
                            "metadata": canonical(metadata["seasons"]),
                        }
                        for r in windows
                    ]
                )
            )
            db.read_json(
                str(buffer),
                columns={
                    "season": "INTEGER",
                    "player": "VARCHAR",
                    "start": "VARCHAR",
                    "finish": "VARCHAR",
                    "available": "VARCHAR",
                    "counts": "INTEGER[]",
                    "games": "VARCHAR[]",
                    "teams": "INTEGER[]",
                    "metadata": "VARCHAR",
                },
            ).create_view("buffer")
            db.execute("INSERT INTO features SELECT * FROM buffer")
            db.execute("COPY features TO ? (FORMAT PARQUET)", [str(temporary)])
            temporary.replace(cache)
        finally:
            buffer.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
        return windows, metadata


def _cached_window(
    row: tuple[Any, ...], retrieved: datetime, policy: str
) -> HistoricalWindow:
    season, player, start, end, available, counts, games, teams, _ = row
    known = timestamp(available)
    return HistoricalWindow(
        season,
        Window(player, timestamp(start), timestamp(end), known, known, tuple(counts)),
        tuple(games),
        tuple(teams),
        retrieved,
        policy,
    )


def forecast_historical(
    rows: list[HistoricalWindow],
    player_key: str,
    as_of: datetime,
    *,
    season: int,
    identities: IdentityMap | None = None,
    model: str = "recency",
    config: ForecastConfig | None = None,
    seed: int = 42,
    samples: int = 256,
) -> Forecast:
    """Current-season inference, optionally using an origin-known exact Yahoo link."""
    if re.fullmatch(r"nba:[1-9]\d*", player_key):
        nba_key = player_key
    else:
        if identities is None:
            raise ValueError("A verified Yahoo/NBA identity map is required.")
        nba_key = f"nba:{identities.nba_id(player_key, season, as_of)}"
    scoped = [r for r in rows if r.season == season]
    available = known_windows([r.window for r in scoped], as_of)
    windows = [
        replace(r, player_key=player_key) if r.player_key == nba_key else r
        for r in available
    ]
    prediction = forecast(
        windows,
        player_key,
        as_of,
        model=model,
        config=config,
        seed=seed,
        samples=samples,
    )
    known_keys = {(r.player_key, r.start) for r in available}
    provenance = [
        {
            "season": r.season,
            "games": r.game_ids,
            "teams": r.team_ids,
            "policy": r.availability_policy,
            "retrieved_at": r.source_retrieved_at.isoformat(),
        }
        for r in scoped
        if (r.window.player_key, r.window.start) in known_keys
    ]
    policies = sorted(
        {
            r.availability_policy
            for r in scoped
            if (r.window.player_key, r.window.start) in known_keys
        }
    )
    return replace(
        prediction,
        assumptions={
            **prediction.assumptions,
            "source": "historical NBA regular-season game rows",
            "availability_policy": policies,
            "season": season,
        },
        feature_snapshot={
            **prediction.feature_snapshot,
            "adapter_version": ADAPTER_VERSION,
            "game_provenance_hash": digest(canonical(provenance)),
        },
        warnings=[
            "Historical weekly totals; no verified future schedule or availability.",
            "Publication times absent; retrospective availability is assumed.",
        ]
        + prediction.warnings[1:],
    )
