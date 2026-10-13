"""Manual fixture pipeline, with a single database lock and derived-only caches."""

import fcntl
import importlib
import json
import logging
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import numpy as np

from fantasy_optimizer.forecast_fixture import fixture_history
from fantasy_optimizer.forecasting import (
    FEATURE_VERSION,
    MODEL_VERSION,
    forecast,
    known_windows,
)
from fantasy_optimizer.optimization import SearchConfig, optimize, validate_inputs
from fantasy_optimizer.optimization_fixture import fixture_inputs
from fantasy_optimizer.registry import Registry, atomic_write
from fantasy_optimizer.simulation import CATEGORIES
from fantasy_optimizer.storage import Store, canonical, digest, timestamp

LOGGER = logging.getLogger(__name__)
SCENARIOS = (
    "baseline",
    "new_stats",
    "transaction",
    "partial_ingestion",
    "unknown_settings",
)


class OperationError(ValueError):
    """Safe operation failure; messages never contain payloads or credentials."""


def event(name: str, **fields: str | bool | int) -> None:
    LOGGER.warning(canonical({"event": name, **fields}))


@contextmanager
def instance_lock(database: Path) -> Iterator[None]:
    """Persistent advisory lock: process exit releases it; never unlink its inode."""
    database = database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    with database.with_suffix(database.suffix + ".lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise OperationError(
                "Another sync/run holds this database lock; retry later."
            ) from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def code_watermark() -> str:
    names = (
        "operations.py",
        "forecasting.py",
        "optimization.py",
        "simulation.py",
        "optimization_fixture.py",
        "storage.py",
        "registry.py",
    )
    return digest(
        canonical(
            {
                name: files("fantasy_optimizer").joinpath(name).read_text()
                for name in names
            }
        )
    )


def fixture_bundle(scenario: str, as_of: datetime | None = None) -> dict[str, Any]:
    """Re-date handmade game inputs once to align fixture clocks, never derive games."""
    if scenario not in SCENARIOS:
        raise OperationError("Unknown operations fixture scenario.")
    windows, origin = fixture_history()
    scenario_time = origin + timedelta(
        minutes=0 if scenario == "partial_ingestion" else SCENARIOS.index(scenario)
    )
    decision = timestamp((as_of or scenario_time).isoformat())
    if decision < scenario_time:
        raise OperationError("No ownership/rule snapshot exists at this earlier as-of.")
    inputs = fixture_inputs(
        "unknown_settings" if scenario == "unknown_settings" else "baseline"
    )
    players, tx, rules, games, opponent, observed, old_origin = inputs
    offset = origin - old_origin
    context_time = origin if scenario == "new_stats" else scenario_time
    players = tuple(
        replace(p, observed_at=context_time, ingested_at=context_time) for p in players
    )
    tx = replace(
        tx,
        observed_at=context_time,
        ingested_at=context_time,
        effective_at=decision,
        acquisitions_remaining=0
        if scenario == "transaction"
        else tx.acquisitions_remaining,
    )
    rules = replace(
        rules,
        period_start=rules.period_start + offset,
        period_end=rules.period_end + offset,
    )
    games = tuple(
        replace(g, starts_at=g.starts_at + offset, ends_at=g.ends_at + offset)
        for g in games
    )
    if decision >= min(game.starts_at for game in games):
        raise OperationError(
            "Later as-of requires updated observed game totals; unavailable in fixture."
        )
    if scenario == "new_stats":
        row = windows[-1]
        counts = list(row.counts)
        assert counts[1] is not None
        counts[1] += 2
        windows.append(
            replace(
                row,
                counts=tuple(counts),
                observed_at=scenario_time,
                ingested_at=scenario_time,
            )
        )
    selected = known_windows(windows, decision)

    def record(kind: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": kind,
            "entity_key": key,
            "league_key": "operations.fixture",
            "payload": payload,
        }

    batches = {
        "operations:rules": [
            record(
                "league",
                "operations.fixture",
                {
                    "season": "2026",
                    "scoring_type": rules.scoring,
                    "stat_categories": list(CATEGORIES),
                    "roster_positions": list(rules.slots),
                },
            )
        ],
        "operations:roster": [
            record(
                "roster",
                "ours",
                {
                    "player_keys": list(rules.rosters[0]),
                    "coverage_type": "week",
                    "coverage_value": origin.isoformat(),
                },
            )
        ],
        "operations:availability": [
            record(
                "availability",
                "pool",
                {
                    "players": [
                        asdict(p)
                        | {
                            "observed_at": p.observed_at.isoformat(),
                            "ingested_at": p.ingested_at.isoformat(),
                        }
                        for p in players
                    ],
                    "complete": True,
                },
            )
        ],
        "operations:stats": [
            record(
                "stat_window",
                f"{row.player_key}:{row.start.isoformat()}",
                {
                    "player_key": row.player_key,
                    "coverage_type": "week",
                    "coverage_value": row.start.isoformat(),
                    "stats": row.payload()["counts"],
                },
            )
            for row in selected
        ],
    }
    # Transaction settings aren't claimed as verified Yahoo payload fields. Their
    # complete proposed contract belongs to the separately hashed fixture inputs.
    return {
        "windows": selected,
        "players": players,
        "tx": tx,
        "rules": rules,
        "games": games,
        "opponent": opponent,
        "observed": observed,
        "as_of": decision,
        "origin": origin,
        "snapshot_at": scenario_time,
        "batches": batches,
    }


def synchronize(
    store: Store, bundle: dict[str, Any], *, partial: bool
) -> dict[str, Any]:
    changed = 0
    for source, records in bundle["batches"].items():
        if partial and source == "operations:availability":
            store.failure(
                source,
                bundle["snapshot_at"],
                bundle["snapshot_at"],
                digest("operations-fixture-fetch-failed"),
            )
            event("run_failed", reason="partial_ingestion")
            raise OperationError(
                "Availability ingestion failed; retry a complete run. No result saved."
            )
        changed += store.ingest(
            source, bundle["snapshot_at"], records, ingested_at=bundle["snapshot_at"]
        )
    watermarks = store.connection.execute(
        "SELECT source, content_hash FROM watermark ORDER BY source"
    ).fetchall()
    expected = sorted(
        (
            source,
            digest(
                canonical(
                    [
                        json.loads(value)
                        for value in sorted({canonical(row) for row in records})
                    ]
                )
            ),
        )
        for source, records in bundle["batches"].items()
    )
    if watermarks != expected:
        raise OperationError("Source validation failed; no recommendation saved.")
    return {"changed_rows": changed, "input_watermark": digest(canonical(watermarks))}


def cached(
    path: Path, key: str, compute: Callable[[], dict[str, Any]]
) -> tuple[dict[str, Any], bool]:
    destination = path / f"{key}.json"
    if destination.exists():
        try:
            envelope = json.loads(destination.read_text())
            if (
                envelope["key"] != key
                or digest(canonical(envelope["result"])) != envelope["checksum"]
            ):
                raise ValueError
            return dict(envelope["result"]), True
        except (ValueError, KeyError, TypeError):
            event("cache_invalid", recompute=True)
    result: dict[str, Any] = compute()
    atomic_write(
        destination,
        {"key": key, "result": result, "checksum": digest(canonical(result))},
    )
    return result, False


def run_fixture(
    database: Path,
    output: Path,
    registry: Registry,
    *,
    scenario: str = "baseline",
    as_of: datetime | None = None,
    dry_run: bool = False,
    seed: int | None = None,
    screening_samples: int = 256,
    finalist_samples: int = 4096,
    backend: Literal["python", "cpp"] = "cpp",
) -> dict[str, Any]:
    if dry_run:
        with tempfile.TemporaryDirectory(prefix="fantasy-dry-run-") as scratch:
            result = run_fixture(
                Path(scratch) / "fixture.duckdb",
                Path(scratch) / "runs",
                registry,
                scenario=scenario,
                as_of=as_of,
                seed=seed,
                screening_samples=screening_samples,
                finalist_samples=finalist_samples,
                backend=backend,
            )
            result.update(dry_run=True, saved=False, artifact=None)
            return result
    bundle = fixture_bundle(scenario, as_of)
    state = registry.read()
    active = state["models"].get(state["active"])
    if active and timestamp(active["training_cutoff"]) > bundle["as_of"]:
        raise OperationError(
            "Active model was trained after this as-of; select a known model."
        )
    if active and timestamp(active["plan"]["validation_end"]) > bundle["as_of"]:
        raise OperationError("Active model selection is later than this as-of.")
    model = active["model"] if active else "recency"
    budget = active["budget"] if active else {"seed": 42, "samples": 256}
    rng_seed = budget["seed"] if seed is None else seed
    config = SearchConfig(
        seed=rng_seed,
        screening_samples=screening_samples,
        finalist_samples=finalist_samples,
        backend=backend,
    )
    try:
        validate_inputs(
            bundle["players"], bundle["tx"], bundle["rules"], bundle["as_of"], config
        )
    except ValueError as error:
        raise OperationError(str(error)) from error
    code = code_watermark()
    native_hash = None
    if backend == "cpp":
        from hashlib import sha256

        native = importlib.import_module("_matchup")

        if native.__file__ is None:
            raise OperationError(
                "Native module path unavailable; use --backend python."
            )
        native_hash = sha256(Path(native.__file__).read_bytes()).hexdigest()
    with instance_lock(database):
        event("run_start", fixture=True)
        store = Store(database)
        try:
            synced = synchronize(store, bundle, partial=scenario == "partial_ingestion")
        finally:
            store.close()
        event("sync_complete", changed_rows=synced["changed_rows"])
        asof = bundle["as_of"]
        forecast_key = digest(
            canonical(
                {
                    "windows": [row.payload() for row in bundle["windows"]],
                    "as_of": asof.isoformat(),
                    "model": model,
                    "active": state["active"],
                    "budget": budget,
                    "seed": rng_seed,
                    "code": digest(
                        canonical(
                            {
                                name: files("fantasy_optimizer")
                                .joinpath(name)
                                .read_text()
                                for name in ("forecasting.py", "forecast_fixture.py")
                            }
                        )
                    ),
                    "summary_version": 1,
                    "feature": FEATURE_VERSION,
                    "version": MODEL_VERSION,
                }
            )
        )

        def infer() -> dict[str, Any]:
            return {
                "active_baseline": model,
                "model_version": MODEL_VERSION,
                "seed": rng_seed,
                "samples": budget["samples"],
                "forecasts": [
                    forecast(
                        bundle["windows"],
                        key,
                        asof,
                        model=model,
                        seed=rng_seed,
                        samples=budget["samples"],
                    ).payload()
                    for key in sorted({row.player_key for row in bundle["windows"]})
                ],
            }

        def summarize() -> dict[str, Any]:
            result = infer()
            for prediction in result["forecasts"]:
                prediction.pop("joint_samples")
            return result

        weekly, forecast_hit = cached(
            output / "cache" / "weekly", forecast_key, summarize
        )
        decision_key = digest(
            canonical(
                {
                    "inputs": repr(
                        (
                            bundle["players"],
                            bundle["tx"],
                            bundle["rules"],
                            bundle["games"],
                            bundle["opponent"],
                            bundle["observed"],
                            asof,
                        )
                    ),
                    "config": repr(config),
                    "code": code,
                    "native": native_hash,
                    "numpy": np.__version__,
                }
            )
        )

        def decide() -> dict[str, Any]:
            return optimize(
                bundle["players"],
                bundle["tx"],
                bundle["rules"],
                bundle["games"],
                bundle["opponent"],
                bundle["observed"],
                asof,
                config=config,
            )

        decision, decision_hit = cached(
            output / "cache" / "decision", decision_key, decide
        )
        identity = digest(
            canonical(
                {
                    "watermark": synced["input_watermark"],
                    "weekly": forecast_key,
                    "decision": decision_key,
                }
            )
        )
        result = {
            "mode": "fixture",
            "scenario": scenario,
            "synthetic": True,
            "run_id": identity,
            "as_of": asof.isoformat(),
            "seed": rng_seed,
            "training_requested": False,
            "registry_modified": False,
            "registry_active": state["active"],
            "input_watermark": synced["input_watermark"],
            "code_hash": code,
            "feature_version": FEATURE_VERSION,
            "weekly": weekly,
            "optimization": decision,
            "freshness": {
                "snapshot_at": bundle["snapshot_at"].isoformat(),
                "snapshot_age_seconds": (asof - bundle["snapshot_at"]).total_seconds(),
                "last_week_end": max(row.end for row in bundle["windows"]).isoformat(),
                "fixture_clock": "Observation/ingestion times are synthetic.",
            },
            "league_rules": {"source": "handmade fixture", "live_verified": False},
            "limitations": [
                "Weekly and game forecasts are separate fixture sources.",
                "Game samples are handmade; no weekly-to-game conversion is assumed.",
                "Monte Carlo SE is sampling precision; model uncertainty uncalibrated.",
                "Live rules unverified. Owner review required; not production-ready.",
            ],
        }
        destination = output / f"{identity}.json"
        if (
            not destination.exists()
            or destination.read_text()
            != json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
        ):
            atomic_write(destination, result)
        event(
            "run_complete",
            forecast_cache_hit=forecast_hit,
            decision_cache_hit=decision_hit,
        )
        return {
            **result,
            "cache": {"weekly_hit": forecast_hit, "decision_hit": decision_hit},
            "sync": synced,
            "saved": True,
            "dry_run": False,
            "artifact": str(destination),
        }
