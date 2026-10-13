"""Manual CLI for the fixture audit and gated read-only Yahoo probes."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from fantasy_optimizer.audit import audit
from fantasy_optimizer.context_fixture import context_fixture
from fantasy_optimizer.forecast_fixture import forecast_fixture
from fantasy_optimizer.forecasting import MODELS, ForecastError
from fantasy_optimizer.ingestion import sync_fixture
from fantasy_optimizer.matchup_fixture import matchup_fixture
from fantasy_optimizer.optimization_fixture import SCENARIOS, optimize_fixture
from fantasy_optimizer.storage import StorageError
from fantasy_optimizer.yahoo import (
    FixtureYahooClient,
    HttpYahooClient,
    YahooClient,
    YahooError,
    auth_status,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Make no live requests unless the owner explicitly declares approved access."""
    parser = argparse.ArgumentParser(
        prog="fantasy",
        description="Personal, read-only fantasy basketball optimizer (planned).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Show project and data-access status")
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
    optimize_command.add_argument("--seed", type=int, default=42)
    optimize_command.add_argument("--screening-samples", type=int, default=256)
    optimize_command.add_argument("--finalist-samples", type=int, default=4096)
    optimize_command.add_argument("--scenario", choices=SCENARIOS, default="baseline")
    optimize_command.add_argument("--backend", choices=("python", "cpp"), default="cpp")
    context_command = commands.add_parser(
        "context", help="Fixture count-shift diagnostics and data gaps"
    )
    context_command.add_argument("--fixture", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "status":
        print(
            "Stage 06: fixture context diagnostics; "
            "recency baseline retained; live access unverified."
        )
        print("Yahoo access is unconfirmed until audited; fixtures are synthetic.")
        return 0
    token_path = Path(os.environ.get("YAHOO_TOKEN_FILE", ".oauth/tokens.json"))
    approved = os.environ.get("YAHOO_ACCESS_APPROVED") == "1"
    try:
        if args.command == "context":
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
                output=args.output,
                evaluate=args.benchmark,
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
    except ForecastError as error:
        print(
            json.dumps({"error": "forecast_failed", "message": str(error)}),
            file=sys.stderr,
        )
        return 1
    except (StorageError, OSError, ValueError, duckdb.Error) as error:
        message = (
            str(error) if isinstance(error, StorageError) else "Fixture sync failed."
        )
        print(
            json.dumps({"error": "storage_failed", "message": message}), file=sys.stderr
        )
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0
