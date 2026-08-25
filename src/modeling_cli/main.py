"""Top-level command-line parser."""

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from modeling_core import APPLICATION_VERSION
from modeling_core.contracts.versions import VersionSet
from modeling_harness.capability_scaffold import scaffold_builtin_capability
from modeling_harness.evidence import EvidenceValidationError
from modeling_harness.release_evidence import (
    ReleaseEvidenceInputs,
    assemble_release_bundle,
    validate_release_bundle,
)
from modeling_harness.verify import add_verify_parser
from modeling_infrastructure.storage import StorageError, bootstrap_storage
from modeling_cli.doctor import run_doctor
from modeling_cli.tool_command import run_tool

CommandHandler = Callable[[argparse.Namespace], int]
_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


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


def _tool(arguments: argparse.Namespace) -> int:
    return run_tool(
        arguments.project_root,
        arguments.tool_name,
        arguments.input,
    )


def _capability_scaffold(arguments: argparse.Namespace) -> int:
    try:
        _ = scaffold_builtin_capability(
            arguments.capability_id,
            arguments.destination,
            arguments.tests_destination,
        )
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


def _hash_argument(value: str) -> str:
    if _HASH_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("expected sha256:<64 lowercase hex>")
    return value


def _evidence_assemble(arguments: argparse.Namespace) -> int:
    try:
        manifest = assemble_release_bundle(
            ReleaseEvidenceInputs(
                windows_report=arguments.windows_report,
                ubuntu_report=arguments.ubuntu_report,
                codex_transcript=arguments.codex_transcript,
            ),
            arguments.destination,
        )
    except (EvidenceValidationError, FileExistsError, OSError, ValueError):
        print("release evidence assembly failed", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "commit": manifest.commit,
                "file_count": len(manifest.files),
                "source_fingerprint": manifest.source_fingerprint,
                "status": "PASSED",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def _evidence_validate(arguments: argparse.Namespace) -> int:
    try:
        report = validate_release_bundle(arguments.bundle, arguments.source_fingerprint)
    except (EvidenceValidationError, OSError, ValueError):
        print("release evidence validation failed", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "commit": report.commit,
                "file_count": report.file_count,
                "source_fingerprint": report.source_fingerprint,
                "status": "PASSED",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


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

    tool_parser = subparsers.add_parser("tool")
    tool_parser.add_argument("--project-root", required=True, type=Path)
    tool_parser.add_argument("tool_name")
    tool_parser.add_argument("--input", required=True, type=str)
    tool_parser.set_defaults(handler=_tool)

    capability_parser = subparsers.add_parser("capability")
    capability_sub = capability_parser.add_subparsers(dest="capability_command")
    scaffold_parser = capability_sub.add_parser("scaffold")
    scaffold_parser.add_argument("capability_id")
    scaffold_parser.add_argument("--destination", required=True, type=Path)
    scaffold_parser.add_argument("--tests-destination", required=True, type=Path)
    scaffold_parser.set_defaults(handler=_capability_scaffold)

    evidence_parser = subparsers.add_parser("evidence")
    evidence_sub = evidence_parser.add_subparsers(dest="evidence_command")
    assemble_parser = evidence_sub.add_parser("assemble")
    assemble_parser.add_argument("--windows-report", required=True, type=Path)
    assemble_parser.add_argument("--ubuntu-report", required=True, type=Path)
    assemble_parser.add_argument("--codex-transcript", required=True, type=Path)
    assemble_parser.add_argument("--destination", required=True, type=Path)
    assemble_parser.set_defaults(handler=_evidence_assemble)
    validate_parser = evidence_sub.add_parser("validate")
    validate_parser.add_argument("--bundle", required=True, type=Path)
    validate_parser.add_argument(
        "--source-fingerprint", required=True, type=_hash_argument
    )
    validate_parser.set_defaults(handler=_evidence_validate)

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
