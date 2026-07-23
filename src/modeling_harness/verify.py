"""Milestone verification command wiring."""

from __future__ import annotations

import argparse
import sys
from typing import cast

from modeling_core import Milestone


def run_verification(milestone: Milestone) -> int:
    """Report the selected milestone until verification checks are registered."""
    print(milestone.value, flush=True)
    print("verification checks are not registered", file=sys.stderr)
    return 2


def _execute(arguments: argparse.Namespace) -> int:
    milestone = cast(Milestone, arguments.milestone)
    return run_verification(milestone)


def add_verify_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the verification subcommand."""
    parser = subparsers.add_parser("verify")
    parser.add_argument(
        "--milestone",
        type=Milestone,
        choices=tuple(Milestone),
        required=True,
    )
    parser.set_defaults(handler=_execute)
