"""The six-operation public application boundary consumed by adapters."""

from __future__ import annotations

from typing import Protocol

from modeling_core.contracts.tools import (
    ConfirmSubproblemMmirRequest,
    ConfirmSubproblemMmirResult,
    CreateProjectRequest,
    CreateProjectResult,
    ExportSubproblemRequest,
    ExportSubproblemResult,
    GetProjectStatusRequest,
    GetProjectStatusResult,
    HealthCheckRequest,
    HealthCheckResult,
    ListCapabilitiesRequest,
    ListCapabilitiesResult,
    PutSubproblemMmirRequest,
    PutSubproblemMmirResult,
    RegisterProblemAssetsRequest,
    RegisterProblemAssetsResult,
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

    def register_problem_assets(
        self, request: RegisterProblemAssetsRequest
    ) -> RegisterProblemAssetsResult: ...

    def put_subproblem_mmir(
        self, request: PutSubproblemMmirRequest
    ) -> PutSubproblemMmirResult: ...

    def confirm_subproblem_mmir(
        self, request: ConfirmSubproblemMmirRequest
    ) -> ConfirmSubproblemMmirResult: ...

    def export_subproblem(
        self, request: ExportSubproblemRequest
    ) -> ExportSubproblemResult: ...
