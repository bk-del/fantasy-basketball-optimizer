"""Research source gates and point-in-time contract on the authorized local cache."""

import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from fantasy_optimizer.advanced_features import counts_from_primitives
from fantasy_optimizer.intelligence_data import observations, verified_manifest


def test_manifest_rejects_corruption_and_unsafe_paths(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw/file").write_bytes(b"bad")
    manifest = {"files": [{"path": "file", "bytes": 3, "sha256": "wrong"}]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="checksum"):
        verified_manifest(tmp_path)
    manifest["files"][0]["path"] = "../outside"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Unsafe"):
        verified_manifest(tmp_path)


def test_cached_espn_identity_arithmetic_and_temporal_gate() -> None:
    root = Path("data/nba_data")
    if not (root / "manifest.json").exists():
        pytest.skip("Ignored owner-authorized NBA cache is absent.")
    records, provenance = observations(root, "retrospective_next_day", (2021,))
    assert len(records) == 23053
    assert len({(r["player"], r["id"]) for r in records}) == len(records)
    assert provenance["espn_seasons"]["2020"]["missing_games"] == 88
    assert provenance["espn_seasons"]["2026"]["missing_games"] == 2
    assert provenance["espn_seasons"]["2025"]["source_null_team_ids"] == 26303
    for row in records:
        assert row["player"].startswith("nba:")
        assert row["id"] == "espn:" + row["nba_game_id"]
        assert row["team"] > 1_610_000_000
        assert row["available"] == row["end"] + timedelta(hours=12)
        assert row["observed_at"] is None
        assert row["availability_status"] == "unknown"
        assert row["ingested_at"] > row["end"]
        np.testing.assert_array_equal(
            row["counts"], counts_from_primitives(row["primitive"])
        )
    strict, _ = observations(root, "strict", (2021,))
    assert all(r["available"] == r["ingested_at"] for r in strict)
    with pytest.raises(ValueError, match="Incomplete"):
        observations(root, "strict", (2020,))
    with pytest.raises(ValueError, match="Incomplete"):
        observations(root, "strict", (2026,))
    with pytest.raises(ValueError, match="Unknown availability"):
        observations(root, "pretend_pregame", (2021,))
