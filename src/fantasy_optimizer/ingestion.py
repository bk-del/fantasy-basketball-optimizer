"""Explicitly synthetic, normalized fixture ingestion; live sync is not enabled."""

import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from time import perf_counter
from typing import Any

from fantasy_optimizer.storage import SCHEMA_VERSION, Store, digest, timestamp


def fixture_batches(scenario: str) -> list[dict[str, Any]]:
    if scenario not in ("baseline", "changed"):
        raise ValueError("Unknown fixture scenario.")
    content = files("fantasy_optimizer").joinpath("fixtures", "ingestion.json")
    batches: list[dict[str, Any]] = json.loads(content.read_text())[scenario]
    return batches


def sync_fixture(
    path: Path,
    scenario: str = "baseline",
    *,
    failed_sources: frozenset[str] = frozenset(),
    ingested_at: datetime | None = None,
) -> dict[str, Any]:
    """Commit each resource atomically; a failed fetch cannot erase prior state."""
    started = perf_counter()
    store = Store(path)
    changed = 0
    failures: list[str] = []
    completed: list[str] = []
    try:
        for batch in fixture_batches(scenario):
            source = batch["source"]
            observed_at = timestamp(batch["observed_at"])
            persisted_at = ingested_at or datetime.now(UTC)
            if source in failed_sources:
                store.failure(
                    source,
                    observed_at,
                    persisted_at,
                    digest(f"{source}:{observed_at.isoformat()}:fetch_failed"),
                )
                failures.append(source)
                continue
            changed += store.ingest(
                source, observed_at, batch["records"], ingested_at=persisted_at
            )
            completed.append(source)
    finally:
        store.close()
    return {
        "mode": "fixture",
        "synthetic": True,
        "schema_version": SCHEMA_VERSION,
        "scenario": scenario,
        "changed_rows": changed,
        "completed_sources": completed,
        "failed_sources": failures,
        "database_bytes": path.stat().st_size,
        "duration_seconds": round(perf_counter() - started, 6),
        "limitations": [
            "Fixture availability/status are candidate contracts, not verified fields.",
            "Stat windows retain aggregate coverage; no player-game rows exist.",
            "Fixture observation times are synthetic; ingestion time is local UTC.",
            "Partial runs are resource-atomic; inspect failures before downstream use.",
        ],
    }
