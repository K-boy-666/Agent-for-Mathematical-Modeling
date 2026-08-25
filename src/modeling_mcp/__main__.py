"""Process entry point; concrete application assembly is imported lazily."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import importlib
from pathlib import Path


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="modeling-mcp")
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="project directory bound to this MCP process",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Parse process arguments, then delegate all assembly to the composition root."""
    arguments = _argument_parser().parse_args(argv)
    composition = importlib.import_module("modeling_bootstrap.composition")
    runner = getattr(composition, "run_mcp_server")
    runner(arguments.project_root)


if __name__ == "__main__":  # pragma: no cover
    main()
