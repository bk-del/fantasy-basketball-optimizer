"""Recovery, change-only snapshots, and point-in-time persistence contracts."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from fantasy_optimizer.cli import main
from fantasy_optimizer.ingestion import fixture_batches, sync_fixture
from fantasy_optimizer.storage import KINDS, StorageError, Store, timestamp

T0 = datetime(2026, 10, 12, 12, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)


def counts(store: Store) -> list[int]:
    return [
        store.connection.execute(f"SELECT count(*) FROM {kind}_snapshot").fetchone()[0]
        for kind in KINDS
    ]


def test_migration_reopen_and_reject_future_schema(tmp_path: Path) -> None:
    path = tmp_path / "store.duckdb"
    store = Store(path)
    assert counts(store) == [0] * 6
    store.close()
    store = Store(path)
    assert store.connection.execute(
        "SELECT version FROM schema_migration"
    ).fetchall() == [(1,)]
    store.connection.execute("UPDATE schema_migration SET version = 2")
    store.close()
    with pytest.raises(StorageError, match="Unsupported"):
        Store(path)
    connection = duckdb.connect(str(path))
    assert connection.execute("SELECT version FROM schema_migration").fetchall() == [
        (2,)
    ]
    connection.close()


def test_migration_rolls_back_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fantasy_optimizer.storage as module

    path = tmp_path / "store.duckdb"
    original = module.MIGRATION
    monkeypatch.setattr(module, "MIGRATION", original + "\nINVALID SQL;")
    with pytest.raises(duckdb.Error):
        Store(path)
    monkeypatch.setattr(module, "MIGRATION", original)
    store = Store(path)
    assert counts(store) == [0] * 6
    store.close()


def test_unchanged_and_changed_fixture_snapshots(tmp_path: Path) -> None:
    path = tmp_path / "store.duckdb"
    first = sync_fixture(path, ingested_at=T0)
    assert first["changed_rows"] == 7
    assert first["database_bytes"] > 0
    assert first["duration_seconds"] >= 0
    assert sync_fixture(path, ingested_at=T0)["changed_rows"] == 0
    assert sync_fixture(path, "changed", ingested_at=T1)["changed_rows"] == 3
    assert sync_fixture(path, "changed", ingested_at=T1)["changed_rows"] == 0
    store = Store(path)
    assert counts(store) == [1, 3, 2, 2, 1, 1]
    assert store.as_of("roster", T0)[0]["payload"]["player_keys"] == ["fixture.p.1"]
    assert store.as_of("roster", T1)[0]["payload"]["player_keys"] == ["fixture.p.2"]
    assert store.as_of("player", T0)[0]["payload"]["status"] is None
    assert store.as_of("player", T1)[0]["payload"]["status"] == "DTD"
    assert (
        store.as_of("availability", T0)[0]["payload"]["players"][0]["player_key"]
        == "fixture.p.2"
    )
    assert store.as_of("stat_window", T1)[0]["payload"]["coverage_type"] == "season"
    assert store.connection.execute(
        "SELECT epoch_us(min(observed_at)) FROM watermark"
    ).fetchone()[0] == int(T1.timestamp() * 1_000_000)
    store.close()


def test_duplicate_entities_and_reordered_batch_are_idempotent(tmp_path: Path) -> None:
    store = Store(tmp_path / "store.duckdb")
    batch = fixture_batches("baseline")[1]
    records = batch["records"]
    assert store.ingest(batch["source"], T0, records + records, ingested_at=T0) == 2
    assert (
        store.ingest(batch["source"], T0, list(reversed(records)), ingested_at=T0) == 0
    )
    assert counts(store)[1] == 2
    store.close()


def test_late_ingestion_does_not_leak_into_earlier_as_of(tmp_path: Path) -> None:
    store = Store(tmp_path / "store.duckdb")
    batch = fixture_batches("baseline")[1]
    store.ingest(batch["source"], T0, batch["records"], ingested_at=T1)
    assert store.as_of("player", T0) == []
    assert len(store.as_of("player", T1)) == 2
    store.close()


def test_partial_fetch_failure_preserves_prior_data_and_retries(tmp_path: Path) -> None:
    path = tmp_path / "store.duckdb"
    sync_fixture(path, ingested_at=T0)
    result = sync_fixture(
        path, "changed", failed_sources=frozenset({"fixture:roster"}), ingested_at=T1
    )
    assert result["failed_sources"] == ["fixture:roster"]
    assert result["changed_rows"] == 2
    store = Store(path)
    assert store.as_of("roster", T1)[0]["payload"]["player_keys"] == ["fixture.p.1"]
    assert store.connection.execute(
        "SELECT epoch_us(observed_at) FROM watermark WHERE source = 'fixture:roster'"
    ).fetchone()[0] == int(T0.timestamp() * 1_000_000)
    store.close()
    assert sync_fixture(path, "changed", ingested_at=T1)["changed_rows"] == 1
    store = Store(path)
    assert store.as_of("roster", T1)[0]["payload"]["player_keys"] == ["fixture.p.2"]
    assert store.connection.execute(
        "SELECT error_code FROM sync_attempt WHERE status = 'failed'"
    ).fetchall() == [("fetch_failed",)]
    store.close()


def test_transaction_failure_rolls_back_rows_and_watermark(tmp_path: Path) -> None:
    store = Store(tmp_path / "store.duckdb")
    batch = fixture_batches("baseline")[1]

    def fail() -> None:
        raise RuntimeError("private transport body must not be persisted")

    with pytest.raises(RuntimeError):
        store.ingest(
            batch["source"], T0, batch["records"], ingested_at=T0, before_commit=fail
        )
    assert counts(store) == [0] * 6
    assert store.connection.execute("SELECT * FROM watermark").fetchall() == []
    assert store.connection.execute(
        "SELECT error_code FROM sync_attempt"
    ).fetchall() == [("ingest_failed",)]
    assert store.ingest(batch["source"], T0, batch["records"], ingested_at=T0) == 2
    assert store.connection.execute("SELECT status FROM sync_attempt").fetchall() == [
        ("success",)
    ]
    store.close()


def test_conflicting_duplicates_and_old_observations_are_rejected(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "store.duckdb")
    batch = fixture_batches("baseline")[1]
    duplicate = deepcopy(batch["records"][0])
    duplicate["payload"]["status"] = "DTD"
    with pytest.raises(StorageError, match="Conflicting duplicate"):
        store.ingest(
            batch["source"], T0, batch["records"] + [duplicate], ingested_at=T0
        )
    assert counts(store) == [0] * 6
    store.ingest(batch["source"], T1, batch["records"], ingested_at=T1)
    with pytest.raises(StorageError, match="Out-of-order"):
        store.ingest(batch["source"], T0, [duplicate], ingested_at=T1)
    with pytest.raises(StorageError, match="same observation"):
        store.ingest(batch["source"], T1, [duplicate], ingested_at=T1)
    assert counts(store)[1] == 2
    store.close()


def test_empty_roster_is_an_explicit_changed_snapshot(tmp_path: Path) -> None:
    store = Store(tmp_path / "store.duckdb")
    batch = fixture_batches("baseline")[2]
    store.ingest(batch["source"], T0, batch["records"], ingested_at=T0)
    batch["records"][0]["payload"]["player_keys"] = []
    assert store.ingest(batch["source"], T1, batch["records"], ingested_at=T1) == 1
    assert store.as_of("roster", T1)[0]["payload"]["player_keys"] == []
    store.close()


def test_timezone_contract_and_future_observation(tmp_path: Path) -> None:
    assert timestamp("2026-10-12T14:00:00+02:00") == T0
    with pytest.raises(StorageError, match="timezone"):
        timestamp("2026-10-12T12:00:00")
    store = Store(tmp_path / "store.duckdb")
    with pytest.raises(StorageError, match="later"):
        store.ingest("fixture:players", T1, [], ingested_at=T0)
    store.close()


def test_cli_fixture_and_live_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "cli.duckdb"
    assert main(["sync", "--database", str(path)]) == 1
    assert not path.exists()
    assert "live_sync_unavailable" in capsys.readouterr().err
    assert main(["sync", "--fixture", "--database", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["synthetic"] is True
    assert result["changed_rows"] == 7
    assert main(["sync", "--fixture", "--database", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["changed_rows"] == 0


def test_invalid_metadata_and_nested_credentials_roll_back(tmp_path: Path) -> None:
    store = Store(tmp_path / "store.duckdb")
    batch = fixture_batches("baseline")[4]
    batch["records"][0]["payload"]["teams"][0]["access_token"] = "synthetic-secret"
    with pytest.raises(StorageError, match="Credential"):
        store.ingest(batch["source"], T0, batch["records"], ingested_at=T0)
    assert counts(store) == [0] * 6
    assert store.connection.execute("SELECT * FROM watermark").fetchall() == []
    record = fixture_batches("baseline")[0]["records"][0]
    record["event_at"] = "2026-10-12T12:00:00"
    with pytest.raises(StorageError, match="timezone"):
        store.ingest("fixture:settings", T0, [record], ingested_at=T0)
    store.close()
