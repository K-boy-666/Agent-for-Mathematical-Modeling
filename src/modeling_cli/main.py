"""Top-level command-line parser."""

import argparse
from collections.abc import Callable, Sequence
from typing import cast

from modeling_core import APPLICATION_VERSION
from modeling_harness.verify import add_verify_parser

CommandHandler = Callable[[argparse.Namespace], int]


def _not_implemented(_: argparse.Namespace) -> int:
    print("command not implemented in this increment")
    return 2


def build_parser() -> argparse.ArgumentParser:
    """Build the stable top-level command parser."""
    parser = argparse.ArgumentParser(prog="modeling")
    parser.add_argument("--version", action="version", version=APPLICATION_VERSION)
    subparsers = parser.add_subparsers(dest="command")

    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.set_defaults(handler=_not_implemented)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.set_defaults(handler=_not_implemented)

    add_verify_parser(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch the selected command."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if not hasattr(arguments, "handler"):
        parser.print_help()
        return 0
    handler = cast(CommandHandler, arguments.handler)
    return handler(arguments)
