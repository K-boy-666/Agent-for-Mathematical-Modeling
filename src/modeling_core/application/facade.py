"""The six-operation public application boundary consumed by adapters."""

from __future__ import annotations

from typing import Protocol

from modeling_core.contracts.tools import (
    CreateProjectRequest,
    CreateProjectResult,
    GetProjectStatusRequest,
    GetProjectStatusResult,
    HealthCheckRequest,
    HealthCheckResult,
    ListCapabilitiesRequest,
    ListCapabilitiesResult,
    RunExperimentRequest,
    RunExperimentResult,
    ValidateExperimentRequest,
    ValidateExperimentResult,
)


class ApplicationFacade(Protocol):
    def health_check(self, request: HealthCheckRequest) -> HealthCheckResult: ...

    def create_project(self, request: CreateProjectRequest) -> CreateProjectResult: ...

    def get_project_status(
        self, request: GetProjectStatusRequest
    ) -> GetProjectStatusResult: ...

    def list_capabilities(
        self, request: ListCapabilitiesRequest
    ) -> ListCapabilitiesResult: ...

    def run_experiment(self, request: RunExperimentRequest) -> RunExperimentResult: ...

    def validate_experiment(
        self, request: ValidateExperimentRequest
    ) -> ValidateExperimentResult: ...
