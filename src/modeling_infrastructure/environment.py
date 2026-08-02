"""Minimal, host-neutral environment evidence for an M1a attempt."""

from __future__ import annotations

import hashlib
import platform
from pathlib import Path
from typing import Literal, cast

from modeling_core.contracts.tools import EnvironmentSummary


def capture_environment_summary(
    *, lock_file: Path, application_version: str = "0.1.0"
) -> EnvironmentSummary:
    if application_version != "0.1.0":
        raise ValueError("application_version must equal 0.1.0 for M1a")
    raw_lock = lock_file.read_bytes()
    return EnvironmentSummary(
        python_version=platform.python_version(),
        application_version=cast(Literal["0.1.0"], application_version),
        lock_hash="sha256:" + hashlib.sha256(raw_lock).hexdigest(),
    )


__all__ = ["capture_environment_summary"]
