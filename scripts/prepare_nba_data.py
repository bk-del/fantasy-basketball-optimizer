"""Download a pinned processed NBA snapshot and prepare offline DuckDB views."""

import argparse
import hashlib
import json
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import duckdb

REPOSITORY = "llimllib/nba_data"
COMMIT = "62df92a05f16b57498851167b8289cf9ec316aea"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=90) as response:
        return response.read()


def selected(path: str) -> bool:
    return path in {"README.md", "docs/DATA_DICTIONARY.md", "docs/v2.md"} or (
        path.startswith("data/")
        and len(path.split("/")) <= 3
        and path.endswith((".parquet", ".json"))
        and not (path.startswith("data/espn/") and path.endswith(".json"))
    )


def prepare(root: Path, offline: bool) -> None:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    if offline:
        manifest = json.loads(manifest_path.read_text())
        if manifest["commit"] != COMMIT:
            raise ValueError("Manifest does not match the pinned commit")
    else:
        tree = json.loads(
            fetch(
                f"https://api.github.com/repos/{REPOSITORY}/git/trees/{COMMIT}?recursive=1"
            )
        )
        if tree.get("truncated"):
            raise ValueError("Incomplete upstream file listing")
        manifest = {
            "repository": f"https://github.com/{REPOSITORY}",
            "commit": COMMIT,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "scope": "Published v1 Parquet, summary JSON and upstream docs",
            "excluded": "Raw daily ESPN JSON responses; v2 remote object storage",
            "files": [],
        }
        for entry in tree["tree"]:
            if entry["type"] != "blob" or not selected(entry["path"]):
                continue
            path = root / "raw" / entry["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = path.read_bytes() if path.exists() else b""
            blob = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload)
            if blob.hexdigest() != entry["sha"]:
                payload = fetch(
                    f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/{entry['path']}"
                )
            blob = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload)
            if len(payload) != entry["size"] or blob.hexdigest() != entry["sha"]:
                raise ValueError(f"Upstream content mismatch: {entry['path']}")
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(path)
            manifest["files"].append(
                {
                    "path": entry["path"],
                    "bytes": len(payload),
                    "git_blob": entry["sha"],
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    report = {"commit": COMMIT, "tables": {}, "json_files": 0}
    catalog = root / "nba.duckdb"
    temporary_catalog = root / "nba.preparing.duckdb"
    temporary_catalog.unlink(missing_ok=True)
    try:
        with duckdb.connect(str(temporary_catalog)) as connection:
            for entry in manifest["files"]:
                path = root / "raw" / entry["path"]
                if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                    raise ValueError(f"Local checksum mismatch: {entry['path']}")
                if path.suffix == ".json":
                    json.loads(path.read_text())
                    report["json_files"] += 1
                if path.suffix != ".parquet":
                    continue
                name = ("espn_" if "/espn/" in entry["path"] else "") + path.stem
                if not re.fullmatch(r"[a-z_0-9]+", name):
                    raise ValueError("Invalid table name")
                literal = str(path).replace("'", "''")
                connection.execute(
                    f"CREATE VIEW \"{name}\" AS SELECT * FROM read_parquet('{literal}')"
                )
                rows = connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()
                columns = connection.execute(f'DESCRIBE "{name}"').fetchall()
                report["tables"][name] = {
                    "rows": rows[0],
                    "columns": [{"name": c[0], "type": c[1]} for c in columns],
                }
            report["player_log_quality"] = {}
            for name in report["tables"]:
                if not re.fullmatch(r"playerlog_[0-9]{4}", name):
                    continue
                quality = connection.execute(
                    f"SELECT count(*), count(DISTINCT gameId), "
                    f"count(*) - count(DISTINCT (gameId, personId, teamId)), "
                    f"count(*) FILTER (WHERE fieldGoalsMade > fieldGoalsAttempted "
                    f"OR freeThrowsMade > freeThrowsAttempted "
                    f"OR threePointersMade > fieldGoalsMade), "
                    f"count(*) FILTER (WHERE personId IS NULL OR gameId IS NULL) "
                    f'FROM "{name}"'
                ).fetchone()
                report["player_log_quality"][name] = dict(
                    zip(
                        [
                            "rows",
                            "distinct_games",
                            "duplicate_keys",
                            "invalid_makes",
                            "null_keys",
                        ],
                        quality,
                        strict=True,
                    )
                )
        temporary_catalog.replace(catalog)
    finally:
        temporary_catalog.unlink(missing_ok=True)
    (root / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "catalog": str(catalog),
                "files": len(manifest["files"]),
                "bytes": sum(f["bytes"] for f in manifest["files"]),
                "tables": len(report["tables"]),
                "json_files": report["json_files"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("data/nba_data"))
    parser.add_argument(
        "--offline", action="store_true", help="Verify and rebuild without network"
    )
    args = parser.parse_args()
    prepare(args.directory, args.offline)
