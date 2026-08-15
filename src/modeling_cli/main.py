"""Top-level command-line parser."""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from modeling_core import APPLICATION_VERSION
from modeling_core.contracts.versions import VersionSet
from modeling_harness.verify import add_verify_parser
from modeling_infrastructure.storage import StorageError, bootstrap_storage
from modeling_cli.doctor import run_doctor

CommandHandler = Callable[[argparse.Namespace], int]


def _not_implemented(_: argparse.Namespace) -> int:
    print("command not implemented in this increment")
    return 2


def _bootstrap(arguments: argparse.Namespace) -> int:
    try:
        metadata = bootstrap_storage(arguments.project_root, VersionSet.m1a())
    except StorageError as error:
        print(
            json.dumps(
                {
                    "code": error.code,
                    "details": error.details,
                    "message": str(error),
                    "retryable": error.retryable,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "created": metadata.created,
                "database_schema_version": metadata.database_schema_version,
                "project_state": metadata.project_state.value,
                "storage_instance_id": metadata.storage_instance_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def _doctor(arguments: argparse.Namespace) -> int:
    return run_doctor(
        arguments.project_root,
        arguments.deep,
        arguments.json,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the stable top-level command parser."""
    parser = argparse.ArgumentParser(prog="modeling")
    parser.add_argument("--version", action="version", version=APPLICATION_VERSION)
    subparsers = parser.add_subparsers(dest="command")

    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--project-root", required=True, type=Path)
    bootstrap_parser.set_defaults(handler=_bootstrap)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--project-root", required=True, type=Path)
    doctor_parser.add_argument("--deep", action="store_true")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.set_defaults(handler=_doctor)

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
