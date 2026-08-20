"""Test-only byte-pipe server that terminates at one selected B7 fault point."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Mapping

from modeling_bootstrap.composition import build_composition
from modeling_core.contracts.tools import RunExperimentRequest
from modeling_core.ports.faults import FaultPoint


class ScriptedProcessExitFaults:
    """Crash exactly once at the point selected by the parent test process."""

    def __init__(self, selected: FaultPoint) -> None:
        self._selected = selected

    def check(self, point: FaultPoint, context: Mapping[str, object]) -> None:
        del context
        if point is self._selected:
            os._exit(91)


def main() -> int:
    project_root = Path(sys.argv[1])
    selected = FaultPoint(sys.argv[2])
    request_bytes = sys.stdin.buffer.readline()
    request = RunExperimentRequest.model_validate_json(request_bytes, strict=True)
    composition = build_composition(
        project_root,
        fault_injector=ScriptedProcessExitFaults(selected),
    )
    with composition:
        result = composition.application.run_experiment(request)
        sys.stdout.buffer.write(
            json.dumps(
                result.model_dump(mode="json", exclude_none=True),
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
