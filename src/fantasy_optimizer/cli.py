"""Manual CLI for the fixture audit and gated read-only Yahoo probes."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import duckdb

from fantasy_optimizer.audit import audit
from fantasy_optimizer.context_fixture import context_fixture
from fantasy_optimizer.forecast_fixture import forecast_fixture
from fantasy_optimizer.forecasting import MODELS, ForecastError
from fantasy_optimizer.ingestion import sync_fixture
from fantasy_optimizer.learning import TrainingBudget
from fantasy_optimizer.learning_fixture import (
    backtest_fixture,
    train_fixture,
)
from fantasy_optimizer.matchup_fixture import matchup_fixture
from fantasy_optimizer.operations import (
    SCENARIOS as RUN_SCENARIOS,
)
from fantasy_optimizer.operations import (
    OperationError,
    instance_lock,
)
from fantasy_optimizer.operations import (
    run_fixture as operation_run,
)
from fantasy_optimizer.optimization_fixture import SCENARIOS, optimize_fixture
from fantasy_optimizer.registry import Registry, RegistryError
from fantasy_optimizer.storage import StorageError, timestamp
from fantasy_optimizer.yahoo import (
    FixtureYahooClient,
    HttpYahooClient,
    YahooClient,
    YahooError,
    auth_status,
)


def parse_as_of(value: str) -> datetime:
    try:
        return timestamp(value)
    except StorageError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main(argv: Sequence[str] | None = None) -> int:
    """Make no live requests unless the owner explicitly declares approved access."""
    parser = argparse.ArgumentParser(
        prog="fantasy",
        description="Personal, read-only fantasy basketball optimizer (planned).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    status_command = commands.add_parser(
        "status", help="Show project and data-access status"
    )
    status_command.add_argument("--fixture", action="store_true")
    status_command.add_argument(
        "--registry", type=Path, default=Path("models/fixture-registry.json")
    )
    auth = commands.add_parser("auth", help="Inspect local authorization metadata")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_commands.add_parser("status", help="Safe local metadata; no network check")
    audit_command = commands.add_parser(
        "audit", help="Audit fields with six read-only probes"
    )
    audit_command.add_argument(
        "--fixture", action="store_true", help="Use synthetic offline fixtures"
    )
    sync_command = commands.add_parser(
        "sync", help="Persist synthetic fixture snapshots"
    )
    sync_command.add_argument("--fixture", action="store_true")
    sync_command.add_argument("--dry-run", action="store_true")
    sync_command.add_argument(
        "--scenario", choices=("baseline", "changed"), default="baseline"
    )
    sync_command.add_argument(
        "--database", type=Path, default=Path("data/fixture.duckdb")
    )
    forecast_command = commands.add_parser(
        "forecast", help="Forecast synthetic weekly counts"
    )
    forecast_command.add_argument("--fixture", action="store_true")
    forecast_command.add_argument("--as-of", type=parse_as_of)
    forecast_command.add_argument("--dry-run", action="store_true")
    forecast_command.add_argument("--model", choices=MODELS, default="recency")
    forecast_command.add_argument("--seed", type=int, default=42)
    forecast_command.add_argument("--samples", type=int, default=256)
    forecast_command.add_argument("--benchmark", action="store_true")
    forecast_command.add_argument(
        "--output", type=Path, default=Path("models/weekly-counts-v1")
    )
    matchup_command = commands.add_parser(
        "simulate", help="Simulate handmade game fixtures"
    )
    matchup_command.add_argument("--fixture", action="store_true")
    matchup_command.add_argument("--seed", type=int, default=42)
    matchup_command.add_argument("--scenarios", type=int, default=1000)
    matchup_command.add_argument("--backend", choices=("python", "cpp"), default="cpp")
    matchup_command.add_argument("--benchmark", action="store_true")
    optimize_command = commands.add_parser(
        "optimize", help="Read-only handmade add/drop/HOLD suggestions"
    )
    optimize_command.add_argument("--fixture", action="store_true")
    optimize_command.add_argument("--as-of", type=parse_as_of)
    optimize_command.add_argument("--seed", type=int, default=42)
    optimize_command.add_argument("--screening-samples", type=int, default=256)
    optimize_command.add_argument("--finalist-samples", type=int, default=4096)
    optimize_command.add_argument("--scenario", choices=SCENARIOS, default="baseline")
    optimize_command.add_argument("--backend", choices=("python", "cpp"), default="cpp")
    context_command = commands.add_parser(
        "context", help="Fixture count-shift diagnostics and data gaps"
    )
    context_command.add_argument("--fixture", action="store_true")
    for name in ("train", "backtest", "run", "model"):
        command = commands.add_parser(name, help="Offline fixture model lifecycle")
        command.add_argument("--fixture", action="store_true")
        command.add_argument(
            "--registry", type=Path, default=Path("models/fixture-registry.json")
        )
        if name == "run":
            command.add_argument(
                "--database", type=Path, default=Path("data/operations-fixture.duckdb")
            )
            command.add_argument(
                "--output", type=Path, default=Path("data/fixture-runs")
            )
            command.add_argument(
                "--scenario", choices=RUN_SCENARIOS, default="baseline"
            )
            command.add_argument("--as-of", type=parse_as_of)
            command.add_argument("--dry-run", action="store_true")
            command.add_argument("--seed", type=int)
            command.add_argument("--screening-samples", type=int, default=256)
            command.add_argument("--finalist-samples", type=int, default=4096)
            command.add_argument("--backend", choices=("python", "cpp"), default="cpp")
        if name in ("train", "backtest"):
            command.add_argument("--as-of", type=parse_as_of)
            command.add_argument("--seed", type=int, default=42)
            command.add_argument("--samples", type=int, default=256)
            command.add_argument("--max-cases", type=int, default=32)
            command.add_argument("--max-candidates", type=int, default=3)
        if name == "train":
            command.add_argument("--model", choices=MODELS, default="recency")
        elif name == "backtest":
            command.add_argument("--final-holdout", action="store_true")
        elif name == "model":
            command.add_argument(
                "operation", choices=("status", "promote", "rollback", "log-outcome")
            )
            command.add_argument("--id")
            command.add_argument("--outcome", type=Path)
    args = parser.parse_args(argv)
    if args.command == "status":
        print(
            "Stage 08: manual fixture pipeline; "
            "recency baseline retained; live access unverified."
        )
        print("Yahoo access is unconfirmed until audited; fixtures are synthetic.")
        print(
            "Next: run fantasy run --fixture; review category effects and uncertainty."
        )
        print("Owner validation required; live history/rules/availability unverified.")
        try:
            state = Registry(args.registry).read()
            active_label = state["active"] or "provisional recency (uninitialized)"
            print(f"Active registry model: {active_label}")
        except RegistryError:
            print(
                "Registry invalid; restore a verified backup before running.",
                file=sys.stderr,
            )
            return 1
        return 0
    token_path = Path(os.environ.get("YAHOO_TOKEN_FILE", ".oauth/tokens.json"))
    approved = os.environ.get("YAHOO_ACCESS_APPROVED") == "1"
    try:
        if args.command in ("train", "backtest", "run", "model"):
            if not args.fixture:
                print(
                    json.dumps(
                        {
                            "error": "live_learning_unavailable",
                            "message": "Use --fixture; Yahoo histories are unverified.",
                        }
                    ),
                    file=sys.stderr,
                )
                return 1
            registry = Registry(args.registry)
            if args.command in ("train", "backtest") and args.as_of is not None:
                from fantasy_optimizer.learning_fixture import fixture_plan

                cutoff = (
                    fixture_plan().holdout_end
                    if args.command == "backtest" and args.final_holdout
                    else fixture_plan().validation_end
                )
                if args.as_of < cutoff:
                    raise OperationError(
                        "This fixed evaluation protocol is not yet known at --as-of."
                    )
            if args.command in ("train", "backtest"):
                try:
                    budget = TrainingBudget(
                        args.seed, args.samples, args.max_cases, args.max_candidates
                    )
                except ValueError as error:
                    raise RegistryError(str(error)) from error
                if args.command == "train":
                    result = train_fixture(registry, model=args.model, budget=budget)
                else:
                    result = backtest_fixture(
                        registry, final=args.final_holdout, budget=budget
                    )
            elif args.command == "run":
                result = operation_run(
                    args.database,
                    args.output,
                    registry,
                    scenario=args.scenario,
                    as_of=args.as_of,
                    dry_run=args.dry_run,
                    seed=args.seed,
                    screening_samples=args.screening_samples,
                    finalist_samples=args.finalist_samples,
                    backend=args.backend,
                )
            elif args.operation == "status":
                result = registry.read()
            elif args.operation == "rollback":
                result = registry.rollback()
            elif args.operation == "promote":
                if not args.id:
                    raise RegistryError("Promotion requires --id from train output.")
                result = registry.promote(args.id)
            else:
                if args.outcome is None:
                    raise RegistryError("Logging requires --outcome JSON file.")
                result = {
                    "logged": registry.log_outcome(
                        json.loads(args.outcome.read_text())
                    ),
                    "policy_evidence": "One outcome does not establish policy quality.",
                }
        elif args.command == "context":
            if not args.fixture:
                print(
                    json.dumps(
                        {
                            "error": "live_context_unavailable",
                            "message": (
                                "Use --fixture; verified Yahoo "
                                "context/history is missing."
                            ),
                        }
                    ),
                    file=sys.stderr,
                )
                return 1
            result = context_fixture()
        elif args.command == "optimize":
            if not args.fixture:
                print(
                    json.dumps(
                        {
                            "error": "live_optimization_unavailable",
                            "message": (
                                "Use --fixture; Yahoo transaction rules "
                                "and forecasts are unverified."
                            ),
                        }
                    ),
                    file=sys.stderr,
                )
                return 1
            try:
                result = optimize_fixture(
                    seed=args.seed,
                    screening_samples=args.screening_samples,
                    finalist_samples=args.finalist_samples,
                    scenario=args.scenario,
                    backend=args.backend,
                    as_of=args.as_of,
                )
            except (ValueError, ImportError) as error:
                print(
                    json.dumps({"error": "optimization_failed", "message": str(error)}),
                    file=sys.stderr,
                )
                return 1
        elif args.command == "simulate":
            if not args.fixture:
                print(
                    json.dumps(
                        {
                            "error": "live_simulation_unavailable",
                            "message": (
                                "Use --fixture; live game forecasts "
                                "and rules are unverified."
                            ),
                        }
                    ),
                    file=sys.stderr,
                )
                return 1
            try:
                result = matchup_fixture(
                    seed=args.seed,
                    scenarios=args.scenarios,
                    backend=args.backend,
                    benchmark=args.benchmark,
                )
            except (ValueError, ImportError) as error:
                print(
                    json.dumps({"error": "simulation_failed", "message": str(error)}),
                    file=sys.stderr,
                )
                return 1
        elif args.command == "forecast":
            if not args.fixture:
                print(
                    json.dumps(
                        {
                            "error": "live_forecast_unavailable",
                            "message": (
                                "Live forecasts require verified stat windows; "
                                "use --fixture."
                            ),
                        }
                    ),
                    file=sys.stderr,
                )
                return 1
            result = forecast_fixture(
                seed=args.seed,
                samples=args.samples,
                model=args.model,
                output=None if args.dry_run else args.output,
                evaluate=args.benchmark,
                as_of=args.as_of,
            )
        elif args.command == "sync":
            if not args.fixture:
                print(
                    json.dumps(
                        {
                            "error": "live_sync_unavailable",
                            "message": (
                                "Live sync requires verified Yahoo samples; "
                                "use sync --fixture."
                            ),
                        }
                    ),
                    file=sys.stderr,
                )
                return 1
            if args.dry_run:
                import tempfile

                with tempfile.TemporaryDirectory(
                    prefix="fantasy-sync-dry-run-"
                ) as folder:
                    result = sync_fixture(
                        Path(folder) / "fixture.duckdb", args.scenario
                    )
                result.update(dry_run=True, saved=False)
            else:
                with instance_lock(args.database):
                    result = sync_fixture(args.database, args.scenario)
        elif args.command == "auth":
            result = auth_status(token_path, approved)
        else:
            client: YahooClient
            if args.fixture:
                client = FixtureYahooClient()
            else:
                client = HttpYahooClient(
                    approved=approved,
                    token_path=token_path,
                    league_key=os.environ.get("YAHOO_LEAGUE_KEY", ""),
                    team_key=os.environ.get("YAHOO_TEAM_KEY", ""),
                )
            result = audit(client)
    except YahooError as error:
        print(json.dumps({"error": error.code, "message": str(error)}), file=sys.stderr)
        return 1
    except (OperationError, ImportError) as error:
        print(
            json.dumps(
                {
                    "error": "operation_failed",
                    "message": str(error)
                    if isinstance(error, OperationError)
                    else "Native backend unavailable; use --backend python.",
                }
            ),
            file=sys.stderr,
        )
        return 1
    except RegistryError as error:
        print(
            json.dumps({"error": "registry_failed", "message": str(error)}),
            file=sys.stderr,
        )
        return 1
    except ForecastError as error:
        print(
            json.dumps({"error": "forecast_failed", "message": str(error)}),
            file=sys.stderr,
        )
        return 1
    except (StorageError, OSError, ValueError, duckdb.Error) as error:
        message = (
            str(error)
            if isinstance(error, StorageError)
            else "Operation failed; check inputs, state paths and configured backend."
        )
        print(
            json.dumps({"error": "storage_failed", "message": message}), file=sys.stderr
        )
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0
