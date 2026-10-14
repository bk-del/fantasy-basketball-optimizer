"""Reproduce frozen pre-holdout learners/calibration without reopening outcomes."""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from fantasy_optimizer.advanced_benchmark import (
    add_minute_calibration,
    advanced_code_hash,
    baselines,
    restore,
    subset,
)
from fantasy_optimizer.advanced_features import prepare_dataset
from fantasy_optimizer.advanced_models import fit_calibrator, fit_model, predict_model
from fantasy_optimizer.registry import atomic_write

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--verify",
    action="store_true",
    help="Actually refit and compare every frozen artifact, including existing files",
)
args = parser.parse_args()
report = json.loads(Path("docs/benchmarks/nba-advanced.json").read_text())
if report["code_hash"] != advanced_code_hash():
    raise ValueError("Frozen scientific source/dependencies differ.")
data = prepare_dataset(Path("data/nba_data"))
if data["identity"] != report["data_identity"]:
    raise ValueError("Frozen feature/source identity differs.")
protocol = report["protocol"]
train = subset(data, None, protocol["fit_end"])
cal = subset(data, protocol["fit_end"], protocol["calibration_end"])
cases = [data["cases"][i] for i in cal]


def materialize(reference, value):
    with tempfile.TemporaryDirectory(prefix="fantasy-model-replay-") as name:
        temporary = Path(name) / "artifact.json"
        atomic_write(temporary, value)
        checksum = hashlib.sha256(temporary.read_bytes()).hexdigest()
        if checksum != reference["sha256"]:
            raise ValueError(
                "Reproduced artifact differs from frozen SHA256; "
                "no replacement or retuning allowed."
            )
    destination = Path(reference["path"])
    if not destination.exists():
        atomic_write(destination, value)
    restore(reference)
    print("verified", destination, checksum, flush=True)


for label, reference in report["models"].items():
    if Path(reference["path"]).exists() and not args.verify:
        restore(reference)
        continue
    model = fit_model(
        data,
        train,
        protocol["candidates"][label],
        seed=protocol["seed"],
        threads=protocol["threads"],
    )
    materialize(reference, model)
for label, item in report["calibration"].items():
    reference = item["artifact"]
    if Path(reference["path"]).exists() and not args.verify:
        restore(reference)
        continue
    prediction = (
        predict_model(restore(report["models"][label]), data, cal)
        if label in report["models"]
        else baselines(data, cal, label)
    )
    calibrator = fit_calibrator(prediction["primitive"], data["primitive"][cal], cases)
    add_minute_calibration(calibrator, prediction, data, cal)
    materialize(reference, calibrator)
print(
    "Frozen pre-holdout artifacts verified; "
    "no final target scores or selection computed."
)
