"""Audit existing immutable NBA/ESPN cache; never downloads or trains models."""

import argparse
import json
from pathlib import Path

from fantasy_optimizer.intelligence_data import audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/nba_data"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/benchmarks/nba-intelligence-data.json"),
    )
    args = parser.parse_args()
    report = audit(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "complete_espn_seasons": [
                    year
                    for year, value in report["espn_seasons"].items()
                    if value["complete"]
                ],
                "verified_files": report["verified_files"],
            }
        )
    )


if __name__ == "__main__":
    main()
