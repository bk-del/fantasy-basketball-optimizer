"""Manual CLI for the fixture audit and gated read-only Yahoo probes."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from fantasy_optimizer.audit import audit
from fantasy_optimizer.ingestion import sync_fixture
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
    args = parser.parse_args(argv)
    if args.command == "status":
        print("Stage 02: fixture storage; forecasting and optimization are planned.")
        print("Yahoo access is unconfirmed until audited; fixtures are synthetic.")
        return 0
    token_path = Path(os.environ.get("YAHOO_TOKEN_FILE", ".oauth/tokens.json"))
    approved = os.environ.get("YAHOO_ACCESS_APPROVED") == "1"
    try:
        if args.command == "sync":
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
