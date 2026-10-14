"""Execute frozen chronological hypothetical-league decision research."""

import argparse
import json
import resource
import time
from pathlib import Path

from fantasy_optimizer.decision_replay import run_replay
from fantasy_optimizer.registry import atomic_write

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", type=Path, default=Path("data/nba_data"))
parser.add_argument(
    "--output", type=Path, default=Path("docs/benchmarks/nba-decision-replay.json")
)
parser.add_argument("--baseline-only", action="store_true")
args = parser.parse_args()
start = time.monotonic()
report = run_replay(args.root, include_frozen_models=not args.baseline_only)
report["performance"] = {
    "seconds": time.monotonic() - start,
    "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    "device": "CPU",
}
atomic_write(args.output, report)
print(
    json.dumps(
        {
            "summary": report["summary"],
            "performance": report["performance"],
            "output": str(args.output),
        },
        indent=2,
    )
)
