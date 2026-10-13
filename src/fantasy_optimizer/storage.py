"""Versioned DuckDB snapshots; no fabricated games or raw credential payloads."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

KINDS = ("league", "player", "roster", "availability", "matchup", "stat_window")
SCHEMA_VERSION = 1

PAYLOAD_FIELDS = {
    "league": {"season", "scoring_type", "stat_categories", "roster_positions"},
    "player": {"display_name", "team", "eligible_positions", "status"},
    "roster": {"player_keys", "coverage_type", "coverage_value"},
    "availability": {"players", "complete"},
    "matchup": {"coverage_type", "coverage_value", "teams"},
    "stat_window": {"player_key", "coverage_type", "coverage_value", "stats"},
}


class StorageError(Exception):
    """Safe persistence diagnostic."""


def timestamp(value: str) -> datetime:
    """Require timezone-aware times and normalize to UTC."""
    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        raise StorageError("Invalid timestamp.") from error
    if result.tzinfo is None:
        raise StorageError("Timestamp must include a timezone.")
    return result.astimezone(UTC)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def validate_record(record: dict[str, Any]) -> None:
    """Persist canonical facts only; reject accidental raw auth/transport metadata."""
    required = {"kind", "league_key", "entity_key", "payload"}
    optional = {"event_at", "source_updated_at"}
    if not required <= record.keys() or record.keys() - required - optional:
        raise StorageError("Invalid canonical record fields.")
    kind = record["kind"]
    if kind not in KINDS:
        raise StorageError("Unsupported entity kind.")
    if any(
        not isinstance(record[key], str) or not record[key]
        for key in ("league_key", "entity_key")
    ):
        raise StorageError("Missing canonical identifiers.")
    payload = record["payload"]
    if not isinstance(payload, dict) or payload.keys() != PAYLOAD_FIELDS[kind]:
        raise StorageError("Invalid canonical payload fields.")
    for key in optional:
        if record.get(key) is not None:
            timestamp(record[key])
    if kind == "stat_window" and payload["coverage_type"] not in (
        "season",
        "week",
        "date",
        "lastweek",
        "lastmonth",
    ):
        raise StorageError("Unsupported aggregate statistical coverage.")

    # Nested credentials must never sneak into a otherwise valid payload envelope.
    def reject_credentials(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in (
                    "access_token",
                    "refresh_token",
                    "client_secret",
                    "authorization",
                    "password",
                    "cookie",
                    "headers",
                    "raw_response",
                ):
                    raise StorageError(
                        "Credential or transport fields cannot be stored."
                    )
                reject_credentials(child)
        elif isinstance(value, list):
            for child in value:
                reject_credentials(child)

    reject_credentials(payload)


MIGRATION = """
CREATE TABLE sync_attempt (
    attempt_id VARCHAR PRIMARY KEY, source VARCHAR NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL, ingested_at TIMESTAMPTZ NOT NULL,
    status VARCHAR NOT NULL CHECK (status IN ('success', 'failed')),
    error_code VARCHAR, changed_rows INTEGER NOT NULL
);
CREATE TABLE watermark (
    source VARCHAR PRIMARY KEY, observed_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL, content_hash VARCHAR NOT NULL
);
""" + "\n".join(
    f"""CREATE TABLE {kind}_snapshot (
        source VARCHAR NOT NULL, league_key VARCHAR NOT NULL,
        entity_key VARCHAR NOT NULL, observed_at TIMESTAMPTZ NOT NULL,
        ingested_at TIMESTAMPTZ NOT NULL, event_at TIMESTAMPTZ,
        source_updated_at TIMESTAMPTZ, content_hash VARCHAR NOT NULL,
        payload JSON NOT NULL, source_watermark VARCHAR NOT NULL,
        PRIMARY KEY (source, league_key, entity_key, observed_at)
    );"""
    for kind in KINDS
)


class Store:
    """Single local database; resource batches commit or roll back together."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(str(path))
        try:
            self.migrate()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def migrate(self) -> None:
        connection = self.connection
        connection.execute("BEGIN TRANSACTION")
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migration "
                "(version INTEGER PRIMARY KEY, checksum VARCHAR NOT NULL)"
            )
            versions = connection.execute(
                "SELECT version, checksum FROM schema_migration ORDER BY version"
            ).fetchall()
            if versions and versions != [(SCHEMA_VERSION, digest(MIGRATION))]:
                raise StorageError("Unsupported or altered database schema.")
            if not versions:
                connection.execute(MIGRATION)
                connection.execute(
                    "INSERT INTO schema_migration VALUES (?, ?)",
                    [SCHEMA_VERSION, digest(MIGRATION)],
                )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def ingest(
        self,
        source: str,
        observed_at: datetime,
        records: list[dict[str, Any]],
        *,
        ingested_at: datetime | None = None,
        before_commit: Callable[[], None] | None = None,
    ) -> int:
        """Persist change-only entities; retain repeated-fetch watermarks separately."""
        observed_at = timestamp(observed_at.isoformat())
        ingested_at = timestamp((ingested_at or datetime.now(UTC)).isoformat())
        if observed_at > ingested_at:
            raise StorageError("Observation cannot be later than ingestion.")
        # Duplicates and input ordering do not define a new source observation.
        records = [
            json.loads(item) for item in sorted({canonical(row) for row in records})
        ]
        batch_hash = digest(canonical(records))
        attempt_id = digest(canonical([source, observed_at.isoformat(), batch_hash]))
        connection = self.connection
        connection.execute("BEGIN TRANSACTION")
        changed = 0
        try:
            for record in records:
                validate_record(record)
            previous = connection.execute(
                "SELECT epoch_us(observed_at), content_hash "
                "FROM watermark WHERE source = ?",
                [source],
            ).fetchone()
            observed_us = int(observed_at.timestamp() * 1_000_000)
            if previous and observed_us < previous[0]:
                raise StorageError("Out-of-order observation; latest state preserved.")
            if previous and observed_us == previous[0] and batch_hash != previous[1]:
                raise StorageError("Conflicting content at the same observation time.")
            seen: dict[tuple[str, str, str], str] = {}
            for record in records:
                kind = record["kind"]
                league_key, entity_key = record["league_key"], record["entity_key"]
                payload = canonical(record["payload"])
                content_hash = digest(canonical(record))
                key = (kind, league_key, entity_key)
                if key in seen:
                    if seen[key] != content_hash:
                        raise StorageError("Conflicting duplicate entity.")
                    continue
                seen[key] = content_hash
                latest = connection.execute(
                    f"SELECT content_hash FROM {kind}_snapshot "
                    "WHERE source = ? AND league_key = ? AND entity_key = ? "
                    "ORDER BY observed_at DESC LIMIT 1",
                    [source, league_key, entity_key],
                ).fetchone()
                if latest and latest[0] == content_hash:
                    continue
                connection.execute(
                    f"INSERT INTO {kind}_snapshot "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        source,
                        league_key,
                        entity_key,
                        observed_at,
                        ingested_at,
                        record.get("event_at"),
                        record.get("source_updated_at"),
                        content_hash,
                        payload,
                        batch_hash,
                    ],
                )
                changed += 1
            connection.execute(
                "INSERT OR REPLACE INTO watermark VALUES (?, ?, ?, ?)",
                [source, observed_at, ingested_at, batch_hash],
            )
            connection.execute(
                "INSERT OR REPLACE INTO sync_attempt VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    attempt_id,
                    source,
                    observed_at,
                    ingested_at,
                    "success",
                    None,
                    changed,
                ],
            )
            if before_commit:
                before_commit()
            connection.execute("COMMIT")
            return changed
        except Exception:
            connection.execute("ROLLBACK")
            self.failure(source, observed_at, ingested_at, attempt_id, "ingest_failed")
            raise

    def failure(
        self,
        source: str,
        observed_at: datetime,
        ingested_at: datetime,
        attempt_id: str,
        code: str = "fetch_failed",
    ) -> None:
        """Persist fixed error codes only, never exception text or raw responses."""
        if code not in ("fetch_failed", "ingest_failed"):
            raise StorageError("Unsupported failure code.")
        self.connection.execute(
            "INSERT OR REPLACE INTO sync_attempt VALUES (?, ?, ?, ?, ?, ?, ?)",
            [attempt_id, source, observed_at, ingested_at, "failed", code, 0],
        )

    def as_of(self, kind: str, as_of: datetime) -> list[dict[str, Any]]:
        """Require both observation and local ingestion to precede decision time."""
        if kind not in KINDS:
            raise StorageError("Unsupported entity kind.")
        as_of = timestamp(as_of.isoformat())
        rows = self.connection.execute(
            f"SELECT source, league_key, entity_key, payload FROM {kind}_snapshot "
            "WHERE observed_at <= ? AND ingested_at <= ? "
            "QUALIFY ROW_NUMBER() OVER ("
            "PARTITION BY source, league_key, entity_key "
            "ORDER BY observed_at DESC) = 1 "
            "ORDER BY source, league_key, entity_key",
            [as_of, as_of],
        ).fetchall()
        return [
            {
                "source": source,
                "league_key": league,
                "entity_key": entity,
                "payload": json.loads(payload),
            }
            for source, league, entity, payload in rows
        ]
