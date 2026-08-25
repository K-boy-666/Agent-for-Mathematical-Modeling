"""Closed state and outcome vocabularies for durable domain records."""

from enum import StrEnum


class ProjectState(StrEnum):
    UNINITIALIZED = "UNINITIALIZED"
    STORAGE_READY = "STORAGE_READY"
    READY = "READY"
    DEGRADED = "DEGRADED"


class AttemptStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"
    ERRORED = "ERRORED"
    TIMED_OUT = "TIMED_OUT"
    ABANDONED = "ABANDONED"


class ValidationStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    ERRORED = "ERRORED"
    TIMED_OUT = "TIMED_OUT"
    ABANDONED = "ABANDONED"


class ValidationOutcome(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


class TerminalReason(StrEnum):
    DEADLINE_EXCEEDED = "deadline_exceeded"
    HOST_CANCELLED = "host_cancelled"
    SERVER_RECOVERY = "server_recovery"


class ResultKind(StrEnum):
    SUCCESS = "success"
    NUMERICAL_FAILURE = "numerical_failure"
