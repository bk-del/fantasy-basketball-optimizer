"""Offline entry point; Yahoo integration is not implemented."""

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Report the implemented scope without accessing credentials or the network."""
    parser = argparse.ArgumentParser(
        prog="fantasy",
        description="Personal, read-only fantasy basketball optimizer (planned).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Show project and data-access status")
    parser.parse_args(argv)
    print("Stage 00: repository foundation; forecasting and optimization are planned.")
    print("Yahoo access is unconfirmed; offline development only, no data loaded.")
    return 0
