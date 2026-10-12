"""Manual CLI for the fixture audit and gated read-only Yahoo probes."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from fantasy_optimizer.audit import audit
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
    args = parser.parse_args(argv)
    if args.command == "status":
        print("Stage 01: capability audit; forecasting and optimization are planned.")
        print("Yahoo access is unconfirmed until audited; fixtures are synthetic.")
        return 0
    token_path = Path(os.environ.get("YAHOO_TOKEN_FILE", ".oauth/tokens.json"))
    approved = os.environ.get("YAHOO_ACCESS_APPROVED") == "1"
    try:
        if args.command == "auth":
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
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0
