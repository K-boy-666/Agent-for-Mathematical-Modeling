"""Closed fault checkpoints used to prove persistence ordering."""

from __future__ import annotations

from enum import Enum
from typing import Mapping, Protocol


class FaultPoint(str, Enum):
    AFTER_ATTEMPT_CREATED = "AFTER_ATTEMPT_CREATED"
    AFTER_ATTEMPT_RUNNING = "AFTER_ATTEMPT_RUNNING"
    DURING_ARTIFACT_STAGING = "DURING_ARTIFACT_STAGING"
    AFTER_ARTIFACT_PUBLISHED = "AFTER_ARTIFACT_PUBLISHED"
    AFTER_DATABASE_COMMIT = "AFTER_DATABASE_COMMIT"


class FaultInjector(Protocol):
    def check(self, point: FaultPoint, context: Mapping[str, object]) -> None: ...


class NoFaults:
    def check(self, point: FaultPoint, context: Mapping[str, object]) -> None:
        del point, context


__all__ = ["FaultInjector", "FaultPoint", "NoFaults"]
