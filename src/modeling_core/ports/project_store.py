"""Use-case-shaped, typed persistence boundary for one project."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

from pydantic import TypeAdapter

from modeling_core.contracts.common import ProjectSummary
from modeling_core.contracts.tools import (
    CreateProjectRequest,
    CreateProjectResult,
    GetProjectStatusExperimentRequest,
    GetProjectStatusExperimentResult,
    RunExperimentRequest,
    RunExperimentResult,
    ValidateExperimentRequest,
    ValidateExperimentResult,
)
from modeling_core.domain.models import (
    Attempt,
    Experiment,
    Project,
    ResultSnapshot,
    Validation,
)
from modeling_core.domain.states import ProjectState


def _validate(value: object, annotation: Any) -> Any:
    return cast(Any, TypeAdapter(annotation).validate_python(value, strict=True))


@dataclass(frozen=True)
class ProjectStateInspection:
    state: ProjectState
    project: Project | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", _validate(self.state, ProjectState))
        if self.project is not None:
            object.__setattr__(self, "project", _validate(self.project, Project))


@dataclass(frozen=True)
class CreateProjectCommand:
    request: CreateProjectRequest

    def __post_init__(self) -> None:
        object.__setattr__(self, "request", _validate(self.request, CreateProjectRequest))


@dataclass(frozen=True)
class ProjectWriteResult:
    result: CreateProjectResult

    def __post_init__(self) -> None:
        object.__setattr__(self, "result", _validate(self.result, CreateProjectResult))


@dataclass(frozen=True)
class ExperimentTraceQuery:
    request: GetProjectStatusExperimentRequest

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request",
            _validate(self.request, GetProjectStatusExperimentRequest),
        )


@dataclass(frozen=True)
class ExperimentTrace:
    result: GetProjectStatusExperimentResult

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "result",
            _validate(self.result, GetProjectStatusExperimentResult),
        )


@dataclass(frozen=True)
class BeginRunCommand:
    request: RunExperimentRequest

    def __post_init__(self) -> None:
        object.__setattr__(self, "request", _validate(self.request, RunExperimentRequest))


@dataclass(frozen=True)
class BeginRunResult:
    experiment: Experiment
    attempt: Attempt

    def __post_init__(self) -> None:
        object.__setattr__(self, "experiment", _validate(self.experiment, Experiment))
        object.__setattr__(self, "attempt", _validate(self.attempt, Attempt))


@dataclass(frozen=True)
class CompleteAttemptCommand:
    attempt: Attempt
    result: ResultSnapshot | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt", _validate(self.attempt, Attempt))
        if self.result is not None:
            object.__setattr__(self, "result", _validate(self.result, ResultSnapshot))


@dataclass(frozen=True)
class StoredRunResult:
    result: RunExperimentResult

    def __post_init__(self) -> None:
        object.__setattr__(self, "result", _validate(self.result, RunExperimentResult))


@dataclass(frozen=True)
class BeginValidationCommand:
    request: ValidateExperimentRequest

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request", _validate(self.request, ValidateExperimentRequest)
        )


@dataclass(frozen=True)
class BeginValidationResult:
    validation: Validation

    def __post_init__(self) -> None:
        object.__setattr__(self, "validation", _validate(self.validation, Validation))


@dataclass(frozen=True)
class CompleteValidationCommand:
    validation: Validation

    def __post_init__(self) -> None:
        object.__setattr__(self, "validation", _validate(self.validation, Validation))


@dataclass(frozen=True)
class StoredValidationResult:
    result: ValidateExperimentResult

    def __post_init__(self) -> None:
        object.__setattr__(self, "result", _validate(self.result, ValidateExperimentResult))


@dataclass(frozen=True)
class StoreIntegrityReport:
    state: ProjectState
    issues: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", _validate(self.state, ProjectState))
        object.__setattr__(self, "issues", _validate(self.issues, tuple[str, ...]))


class ProjectStore(Protocol):
    def inspect_project_state(self) -> ProjectStateInspection: ...

    def create_or_replay_project(
        self, command: CreateProjectCommand
    ) -> ProjectWriteResult: ...

    def get_project_summary(self, project_id: str) -> ProjectSummary: ...

    def get_experiment_trace(self, query: ExperimentTraceQuery) -> ExperimentTrace: ...

    def begin_run(self, command: BeginRunCommand) -> BeginRunResult: ...

    def mark_attempt_running(
        self, attempt_id: str, started_at: datetime, session_id: str
    ) -> None: ...

    def complete_attempt(self, command: CompleteAttemptCommand) -> StoredRunResult: ...

    def begin_validation(
        self, command: BeginValidationCommand
    ) -> BeginValidationResult: ...

    def mark_validation_running(self, validation_id: str, started_at: datetime) -> None: ...

    def complete_validation(
        self, command: CompleteValidationCommand
    ) -> StoredValidationResult: ...

    def inspect_integrity(self, deep: bool) -> StoreIntegrityReport: ...
