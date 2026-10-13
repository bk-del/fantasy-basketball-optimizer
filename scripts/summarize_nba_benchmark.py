"""Keep full-population replay evidence locally compressed, summaries in Git."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from fantasy_optimizer.registry import atomic_write
from fantasy_optimizer.storage import canonical


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path, default=Path("docs/benchmarks/nba-population.json")
    )
    parser.add_argument(
        "--replays",
        type=Path,
        default=Path("data/nba_data/features/population-replays"),
    )
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    args.replays.mkdir(parents=True, exist_ok=True)
    for horizon in report["results"].values():
        for period in ("holdout", "replication"):
            for info in horizon[period]["models"].values():
                if "replay" not in info:
                    continue
                cases = info.pop("replay")
                raw = canonical(cases).encode()
                checksum = hashlib.sha256(raw).hexdigest()
                compressed = gzip.compress(raw, mtime=0)
                artifact = args.replays / f"{checksum}.json.gz"
                artifact.write_bytes(compressed)
                info.update(
                    replay_artifact=str(artifact),
                    replay_sha256=checksum,
                    replay_cases=len(cases),
                    compressed_bytes=len(compressed),
                )
    atomic_write(args.report, report)
    print(f"Saved summary {args.report}: {args.report.stat().st_size} bytes")


if __name__ == "__main__":
    main()
