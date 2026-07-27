"""Transition guards for the closed attempt and validation state machines."""

from modeling_core.domain.states import AttemptStatus, ValidationStatus


_ATTEMPT_EDGES = frozenset(
    {
        (AttemptStatus.PENDING, AttemptStatus.RUNNING),
        (AttemptStatus.PENDING, AttemptStatus.ABANDONED),
        (AttemptStatus.RUNNING, AttemptStatus.SUCCEEDED),
        (AttemptStatus.RUNNING, AttemptStatus.NUMERICAL_FAILURE),
        (AttemptStatus.RUNNING, AttemptStatus.ERRORED),
        (AttemptStatus.RUNNING, AttemptStatus.TIMED_OUT),
        (AttemptStatus.RUNNING, AttemptStatus.ABANDONED),
    }
)

_VALIDATION_EDGES = frozenset(
    {
        (ValidationStatus.PENDING, ValidationStatus.RUNNING),
        (ValidationStatus.PENDING, ValidationStatus.ABANDONED),
        (ValidationStatus.RUNNING, ValidationStatus.SUCCEEDED),
        (ValidationStatus.RUNNING, ValidationStatus.ERRORED),
        (ValidationStatus.RUNNING, ValidationStatus.TIMED_OUT),
        (ValidationStatus.RUNNING, ValidationStatus.ABANDONED),
    }
)


def validate_attempt_transition(before: AttemptStatus, after: AttemptStatus) -> None:
    """Raise when an attempt transition is not an explicitly legal edge."""
    if (before, after) not in _ATTEMPT_EDGES:
        raise ValueError(f"illegal attempt transition: {before} -> {after}")


def validate_validation_transition(
    before: ValidationStatus, after: ValidationStatus
) -> None:
    """Raise when a validation transition is not an explicitly legal edge."""
    if (before, after) not in _VALIDATION_EDGES:
        raise ValueError(f"illegal validation transition: {before} -> {after}")
