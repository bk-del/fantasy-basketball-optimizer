"""Small local fixture registry; one atomic document holds the model lifecycle."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from fantasy_optimizer.storage import canonical, digest, timestamp


class RegistryError(ValueError):
    """Registry operation refused without changing persisted state."""


def atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False
        ) as stream:
            temporary = stream.name
            stream.write(
                json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


class Registry:
    """Single-writer manual CLI. Reads never initialize or rewrite the file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "version": 1,
                "active": None,
                "models": {},
                "history": [],
                "holdouts": [],
                "outcomes": {},
            }
        try:

            def reject_constant(value: str) -> None:
                raise ValueError(f"Nonfinite registry value: {value}")

            value = json.loads(self.path.read_text(), parse_constant=reject_constant)
            if value["version"] != 1 or not isinstance(value["models"], dict):
                raise ValueError
            if value["active"] is not None and value["active"] not in value["models"]:
                raise ValueError
            if not isinstance(value["outcomes"], dict):
                raise ValueError
            if not isinstance(value["history"], list) or not isinstance(
                value["holdouts"], list
            ):
                raise ValueError
            if any(key not in value["models"] for key in value["history"]):
                raise ValueError
            for identity, entry in value["models"].items():
                if entry["state"] not in ("active", "candidate", "archived"):
                    raise ValueError
                if (entry["state"] == "active") != (identity == value["active"]):
                    raise ValueError
        except (ValueError, KeyError, TypeError) as error:
            raise RegistryError(
                "Invalid registry; refusing to overwrite it."
            ) from error
        return dict(value)

    def register(self, record: dict[str, Any], *, max_candidates: int) -> str:
        state = self.read()
        identity = digest(canonical(record))
        if identity in state["models"]:
            return identity
        if record["kind"] not in ("incumbent", "candidate"):
            raise RegistryError("Invalid registration kind.")
        if record["kind"] == "candidate":
            if state["holdouts"]:
                raise RegistryError(
                    "Final holdout opened; candidate selection is frozen."
                )
            trials = [
                entry
                for entry in state["models"].values()
                if entry["kind"] == "candidate"
                and entry["dataset_watermark"] == record["dataset_watermark"]
            ]
            if len(trials) >= max_candidates:
                raise RegistryError("Dataset candidate budget exhausted.")
        state["models"][identity] = {
            **record,
            "state": "candidate",
            "promotion_reason": None,
        }
        if record["kind"] == "incumbent" and state["active"] is None:
            state["active"] = identity
            state["models"][identity].update(
                state="active",
                promotion_reason=f"Provisional {record['model']} fixture incumbent",
            )
        atomic_write(self.path, state)
        return identity

    def promote(self, identity: str) -> dict[str, Any]:
        state = self.read()
        if state["holdouts"]:
            raise RegistryError("Final holdout opened; promotion is frozen.")
        candidate = state["models"].get(identity)
        active = state["models"].get(state["active"])
        if not candidate or candidate["state"] != "candidate" or not active:
            raise RegistryError("Promotion requires a candidate and active incumbent.")
        if (
            candidate["dataset_watermark"] != active["dataset_watermark"]
            or candidate["evaluation_hash"] != active["evaluation_hash"]
        ):
            raise RegistryError("Models must share the same chronological evaluation.")
        score, old = candidate["validation_pts_mae"], active["validation_pts_mae"]
        if score is None or old is None or score >= old:
            raise RegistryError("Candidate does not beat incumbent validation PTS MAE.")
        # At least as good as every constituent baseline; no training-score promotion.
        if score > min(candidate["baseline_pts_mae"].values()):
            raise RegistryError("Candidate does not beat the baseline comparison.")
        state["history"].append(state["active"])
        active["state"] = "archived"
        candidate.update(
            state="active",
            promotion_reason="Explicit fixture promotion: lower validation PTS MAE",
        )
        state["active"] = identity
        atomic_write(self.path, state)
        return state

    def rollback(self) -> dict[str, Any]:
        state = self.read()
        if not state["history"]:
            raise RegistryError("No previous active model to roll back to.")
        previous = state["history"].pop()
        state["models"][state["active"]]["state"] = "archived"
        state["models"][previous].update(
            state="active",
            promotion_reason="Explicit rollback to previous active model",
        )
        state["active"] = previous
        atomic_write(self.path, state)
        return state

    def consume_holdout(self, identity: str) -> None:
        state = self.read()
        if identity in state["holdouts"]:
            raise RegistryError(
                "Final holdout already consumed; obtain a new later period."
            )
        state["holdouts"].append(identity)
        atomic_write(self.path, state)

    def log_outcome(self, outcome: dict[str, Any]) -> str:
        """Preserve prediction/uncertainty separately from later observed results."""
        required = {
            "decision_run_id",
            "as_of",
            "evaluated_at",
            "predicted_utility",
            "mc_se",
            "model_uncertainty",
            "observed_outcome",
            "confounders",
            "counterfactual",
            "model_id",
        }
        if not isinstance(outcome, dict) or set(outcome) != required:
            raise RegistryError("Incomplete outcome contract.")
        if not isinstance(outcome["as_of"], str) or not isinstance(
            outcome["evaluated_at"], str
        ):
            raise RegistryError("Outcome timestamps must be explicit strings.")
        if timestamp(outcome["as_of"]) >= timestamp(outcome["evaluated_at"]):
            raise RegistryError("Outcome must follow the decision.")
        if (
            type(outcome["predicted_utility"]) not in (int, float)
            or type(outcome["mc_se"]) not in (int, float)
            or not 0 <= outcome["predicted_utility"] <= 1
            or not 0 <= outcome["mc_se"] <= 0.5
        ):
            raise RegistryError("Invalid prediction/uncertainty.")
        if (
            type(outcome["counterfactual"]) is not bool
            or not isinstance(outcome["confounders"], list)
            or not all(isinstance(item, str) for item in outcome["confounders"])
            or not isinstance(outcome["model_uncertainty"], str)
        ):
            raise RegistryError("Invalid uncertainty/confounder contract.")
        state = self.read()
        if outcome["model_id"] not in state["models"]:
            raise RegistryError("Unknown outcome model.")
        identity = outcome["decision_run_id"]
        if not isinstance(identity, str) or not identity:
            raise RegistryError("Missing run identity.")
        existing = state["outcomes"].get(identity)
        if existing is not None and existing != outcome:
            raise RegistryError("Outcome already logged; explicit revision required.")
        if existing is None:
            state["outcomes"][identity] = outcome
            atomic_write(self.path, state)
        # Outcomes never change model selection.
        return identity
