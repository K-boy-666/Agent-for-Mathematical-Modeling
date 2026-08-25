"""Concrete host-neutral orchestration for the six M1a use cases."""

from __future__ import annotations

import base64
import binascii
import threading
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, NoReturn, TypedDict, cast

from pydantic import TypeAdapter

from modeling_core.application.facade import ApplicationFacade
from modeling_core.application.idempotency import (
    create_project_request_hash,
    run_experiment_request_hash,
    validate_experiment_request_hash,
)
from modeling_core.contracts.canonical_json import (
    canonical_json_bytes,
    sha256_json,
    strict_json_loads,
)
from modeling_core.contracts.capability import (
    CancellationSignal,
    CanonicalInputRecord,
    CapabilityInputRejected,
    CapabilityInputResourceLimitExceeded,
    CapabilitySecurityViolation,
    ExecutionCancelled,
    ExecutionContext,
    ExecutionDeadlineExceeded,
    ExecutionOutcome,
    ExecutionResourceLimitExceeded,
    ResultSnapshotView,
    ValidationContext,
)
from modeling_core.contracts.common import (
    EntityId,
    JsonObject,
    ProjectSummary,
    RegistrySummary,
    Warning,
)
from modeling_core.contracts.errors import (
    ErrorDetails,
    ErrorResponse,
    ModelingError,
    UnsupportedVersionDetails,
)
from modeling_core.contracts.tools import (
    AnyValidationReportPayload,
    ArtifactManifest as PublicArtifactManifest,
    AssetSnapshotEntry,
    AttemptTrace,
    CapabilityContract,
    CanonicalCoupledHeaveInput,
    CanonicalRootFindingInput,
    ConfirmSubproblemMmirRequest,
    ConfirmSubproblemMmirResult,
    CreateProjectRequest,
    CreateProjectResult,
    CoupledHeaveInput,
    CoupledHeaveSuccessResultPayload,
    DataSnapshotReference,
    EnvironmentSummary,
    ExecutionOptions,
    ExperimentItems,
    ExperimentRecord,
    ExportEntry,
    ExportSubproblemRequest,
    ExportSubproblemResult,
    FailureResultPayload,
    GetProjectStatusExperimentRequest,
    GetProjectStatusExperimentResult,
    GetProjectStatusRequest,
    GetProjectStatusResult,
    GetProjectStatusSummaryRequest,
    GetProjectStatusSummaryResult,
    HealthCheck,
    HealthCheckRequest,
    HealthCheckResult,
    HealthVersions,
    ListCapabilitiesContractRequest,
    ListCapabilitiesContractResult,
    ListCapabilitiesRequest,
    ListCapabilitiesResult,
    ListCapabilitiesSummaryRequest,
    ListCapabilitiesSummaryResult,
    PutSubproblemMmirRequest,
    PutSubproblemMmirResult,
    RegisterProblemAssetsRequest,
    RegisterProblemAssetsResult,
    ResultPayload,
    ResultTrace,
    RunExperimentErroredResult,
    RunExperimentNumericalFailureResult,
    RunExperimentRequest,
    RunExperimentResult,
    RunExperimentStoppedResult,
    RunExperimentSucceededResult,
    SuccessResultPayload,
    ValidateExperimentErroredResult,
    ValidateExperimentRequest,
    ValidateExperimentResult,
    ValidateExperimentStoppedResult,
    ValidateExperimentSucceededResult,
    ValidationTrace,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.domain.models import (
    Artifact,
    Attempt,
    EnvironmentSnapshot,
    Experiment,
    InputSnapshot,
    Project,
    ResultSnapshot,
    Validation,
)
from modeling_core.domain.states import (
    AttemptStatus,
    ProjectState,
    ResultKind,
    TerminalReason,
    ValidationOutcome,
    ValidationStatus,
)
from modeling_core.ports.artifact_store import (
    ArtifactManifest,
    ArtifactStore,
    ArtifactStoreError,
    AttemptArtifactSink,
)
from modeling_core.ports.clock import Clock
from modeling_core.ports.faults import FaultInjector, FaultPoint, NoFaults
from modeling_core.ports.ids import IdGenerator
from modeling_core.ports.project_store import (
    BeginRunCommand,
    BeginValidationCommand,
    CompleteAttemptCommand,
    CompleteValidationCommand,
    CreateProjectCommand,
    ExperimentTraceQuery,
    ProjectStore,
    ProjectStoreError,
    VerifiedResult,
    WriteOperation,
)
from modeling_core.registry import CapabilityRegistry, RegistryError
from modeling_core.worker.runner import run_worker

_ENTITY_ID = TypeAdapter(EntityId)
_CANONICAL_PAYLOAD: TypeAdapter[
    CanonicalRootFindingInput | CanonicalCoupledHeaveInput
] = TypeAdapter(CanonicalRootFindingInput | CanonicalCoupledHeaveInput)
_RESULT_PAYLOAD: TypeAdapter[ResultPayload] = TypeAdapter(ResultPayload)
_VALIDATION_REPORT: TypeAdapter[AnyValidationReportPayload] = TypeAdapter(
    AnyValidationReportPayload
)
_MAX_RESPONSE_BYTES = 262144
_OFFICIAL_ASSET_SHA256 = frozenset(
    {
        "sha256:e29940eb9eb9382deb8eccb459c73cc47f0080483b8b75f9977830c987162253",
        "sha256:50a5dd70f04dfb0a57fb2602422dc7999b30aad54ddc02353f5b8f01423fd612",
        "sha256:c8eff812f5980d955b4f0e587c5f7a357b2571d8d903fcb4913fba77c7354d6d",
        "sha256:83ed6e0f2ebcdbdcb53e99a3bfebfbd8dc16141f91396eba8806e781d7809c7a",
        "sha256:cc0abbceff32f425e738a3d9c0534fc3fbab4b2a1d2d86b8dc4d51229fb820bf",
    }
)


class _CommonFields(TypedDict):
    tool_contract_version: Literal["modeling-tools/0.1.0", "modeling-tools/1.0.0"]
    correlation_id: str
    server_time: str


class _RunResultFields(_CommonFields):
    operation_id: str
    replayed: bool
    experiment_id: str
    attempt_id: str
    capability_id: str
    contract_version: str
    implementation_id: str
    implementation_version: str
    randomness: str
    seed: int | None
    warnings: tuple[Warning, ...]


class _ValidationResultFields(_CommonFields):
    operation_id: str
    replayed: bool
    validation_id: str
    attempt_id: str
    result_hash: str
    validator_id: Literal[
        "numerical.root_finding.residual",
        "dynamics.coupled_heave.linear",
        "dynamics.coupled_heave.power_law",
    ]
    validator_implementation_id: str
    validator_implementation_version: str
    policy_version: Literal["0.1.0", "1.0.0"]
    policy_hash: str


def _millisecond_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(microsecond=(value.microsecond // 1000) * 1000)


def _timestamp(value: datetime) -> str:
    value = _millisecond_utc(value)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _project_summary(project: Project) -> ProjectSummary:
    return ProjectSummary(
        project_id=project.project_id,
        display_name=project.display_name,
        project_format_version=project.project_format_version,
        project_state="READY",
        created_at=_timestamp(project.created_at),
    )


def _public_artifact(artifact: Artifact) -> PublicArtifactManifest:
    digest = artifact.sha256.removeprefix("sha256:")
    return PublicArtifactManifest(
        artifact_id=artifact.artifact_id,
        role=cast(Literal["result", "validation_report"], artifact.role),
        sha256=artifact.sha256,
        media_type=cast(Literal["application/json"], artifact.media_type),
        size_bytes=artifact.byte_size,
        project_relative_path=(
            f".modeling/artifacts/sha256/{digest[:2]}/{digest}.json"
        ),
    )


def _experiment_record(
    experiment: Experiment, versions: VersionSet
) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=experiment.experiment_id,
        project_id=experiment.project_id,
        capability_id=experiment.capability_id,
        contract_version=experiment.contract_version,
        canonical_input_schema_version=experiment.canonical_input_schema_version,
        canonical_payload=experiment.canonical_payload,
        canonical_payload_hash=experiment.canonical_payload_hash,
        canonicalization_version=versions.canonicalization_version,
        model_snapshot_hash=experiment.model_snapshot_hash,
        data_snapshot_references=experiment.data_snapshot_references,
        data_snapshot_set_hash=experiment.data_snapshot_set_hash,
        execution_policy=experiment.execution_policy,
        created_at=_timestamp(experiment.created_at),
    )


def _attempt_trace(attempt: Attempt) -> AttemptTrace:
    result = None
    if attempt.result is not None:
        result = ResultTrace(
            result_snapshot_id=attempt.result.result_snapshot_id,
            result_kind=attempt.result.result_kind.value,
            result_schema_version=attempt.result.result_schema_version,
            result_hash=attempt.result.result_hash,
            result_payload=attempt.result.result_payload,
        )
    return AttemptTrace(
        record_type="attempt",
        attempt_id=attempt.attempt_id,
        experiment_id=attempt.experiment_id,
        implementation_id=attempt.implementation_id,
        implementation_version=attempt.implementation_version,
        environment_summary=attempt.environment_summary,
        randomness=attempt.randomness,
        seed=attempt.seed,
        session_id=attempt.session_id,
        status=attempt.status.value,
        created_at=_timestamp(attempt.created_at),
        started_at=_timestamp(attempt.started_at) if attempt.started_at else None,
        finished_at=_timestamp(attempt.finished_at) if attempt.finished_at else None,
        warnings=attempt.warnings,
        result=result,
        system_error=attempt.system_error,
        numerical_failure=attempt.numerical_failure,
        terminal_reason=attempt.terminal_reason.value
        if attempt.terminal_reason
        else None,
    )


def _validation_trace(validation: Validation) -> ValidationTrace:
    return ValidationTrace(
        record_type="validation",
        validation_id=validation.validation_id,
        attempt_id=validation.attempt_id,
        expected_result_hash=validation.expected_result_hash,
        result_hash=validation.result_hash,
        validator_id=validation.validator_id,
        validator_implementation_id=validation.validator_implementation_id,
        validator_implementation_version=validation.validator_implementation_version,
        policy_version=validation.policy_version,
        policy=validation.policy,
        policy_hash=validation.policy_hash,
        status=validation.status.value,
        created_at=_timestamp(validation.created_at),
        started_at=_timestamp(validation.started_at) if validation.started_at else None,
        finished_at=_timestamp(validation.finished_at)
        if validation.finished_at
        else None,
        outcome=validation.outcome.value if validation.outcome else None,
        metrics=validation.metrics,
        validation_report_hash=validation.validation_report_hash,
        report_payload=validation.report_payload,
        operational_error=validation.operational_error,
        terminal_reason=validation.terminal_reason.value
        if validation.terminal_reason
        else None,
    )


class ModelingApplication(ApplicationFacade):
    """Coordinates registry, deterministic execution, and durable provenance."""

    def __init__(
        self,
        *,
        store: ProjectStore,
        registry: CapabilityRegistry,
        registry_summary: RegistrySummary,
        versions: VersionSet,
        clock: Clock,
        id_generator: IdGenerator,
        session_id: EntityId,
        environment_summary: EnvironmentSummary,
        cancellation: CancellationSignal,
        default_display_name: str,
        artifact_store: ArtifactStore | None = None,
        environment_document: JsonObject | None = None,
        fault_injector: FaultInjector | None = None,
        subproblem_exporter: Callable[
            [dict[str, JsonObject], JsonObject],
            tuple[tuple[str, str, str, bytes], ...],
        ]
        | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._registry_summary = registry_summary
        self._versions = versions
        self._clock = clock
        self._ids = id_generator
        self._session_id = _ENTITY_ID.validate_python(session_id, strict=True)
        self._environment_summary = environment_summary
        self._cancellation = cancellation
        self._schema_two = versions.database_schema_version == 2
        if self._schema_two:
            if artifact_store is None or environment_document is None:
                raise ValueError(
                    "schema 2 composition requires an artifact store and an "
                    "environment document"
                )
        elif artifact_store is not None or environment_document is not None:
            raise ValueError(
                "schema 1 composition does not accept artifacts or environment "
                "documents"
            )
        self._artifact_store = artifact_store
        self._environment_document = environment_document
        self._faults = fault_injector or NoFaults()
        self._subproblem_exporter = subproblem_exporter
        schema_version = versions.result_schema_version.rsplit("/", 1)[1]
        self._result_schema_id = (
            "https://schemas.math-modeling-mcp.local/common/"
            f"{schema_version}/modeling-result.schema.json"
        )
        self._report_schema_id = (
            "https://schemas.math-modeling-mcp.local/common/"
            f"{schema_version}/modeling-validation-report.schema.json"
        )
        if not 1 <= len(default_display_name) <= 128:
            raise ValueError("default_display_name must contain 1 to 128 characters")
        if unicodedata.normalize("NFC", default_display_name) != default_display_name:
            raise ValueError("default_display_name must be Unicode NFC")
        self._default_display_name = default_display_name
        self._write_gate = threading.Lock()

    def _artifact_record(self, manifest: ArtifactManifest) -> Artifact:
        return Artifact(
            artifact_id=manifest.artifact_id,
            role=manifest.role,
            media_type=manifest.media_type,
            byte_size=manifest.byte_size,
            sha256=manifest.sha256,
            schema_id=manifest.schema_id,
            created_at=datetime.fromisoformat(
                manifest.created_at.replace("Z", "+00:00")
            ),
        )

    def _common(self) -> _CommonFields:
        return {
            "tool_contract_version": self._versions.tool_contract_version,
            "correlation_id": self._ids.new_uuid4(),
            "server_time": _timestamp(self._clock.utc_now()),
        }

    def _raise_store(self, error: ProjectStoreError, correlation_id: str) -> NoReturn:
        details: object = error.details
        if error.code == "INTEGRITY_FAILURE" and error.details.get("subject") in {
            "result_artifact",
            "report_artifact",
        }:
            details = {**error.details, "subject": "artifact_content"}
        supported_versions = error.details.get("supported_versions")
        if error.code == "UNSUPPORTED_VERSION" and isinstance(supported_versions, list):
            details = {
                **error.details,
                "supported_versions": tuple(supported_versions),
            }
        response = ErrorResponse.model_validate(
            {
                "error_schema_version": self._versions.error_schema_version,
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "correlation_id": correlation_id,
                "details": details,
            }
        )
        raise ModelingError(response) from error

    def _raise_error(
        self,
        *,
        correlation_id: str,
        code: str,
        message: str,
        details: JsonObject | ErrorDetails,
        retryable: bool = False,
    ) -> NoReturn:
        raise ModelingError(
            self._error_response(
                correlation_id=correlation_id,
                code=code,
                message=message,
                details=details,
                retryable=retryable,
            )
        )

    def _error_response(
        self,
        *,
        correlation_id: str,
        code: str,
        message: str,
        details: JsonObject | ErrorDetails,
        retryable: bool = False,
    ) -> ErrorResponse:
        return ErrorResponse.model_validate(
            {
                "error_schema_version": self._versions.error_schema_version,
                "code": code,
                "message": message,
                "retryable": retryable,
                "correlation_id": correlation_id,
                "details": details,
            }
        )

    def _acquire_write(
        self,
        correlation_id: str,
    ) -> None:
        if not self._write_gate.acquire(blocking=False):
            self._raise_error(
                correlation_id=correlation_id,
                code="CONFLICT",
                message="another project write is in progress",
                retryable=True,
                details={
                    "conflict_type": "project_busy",
                    "retry_after_ms": 250,
                },
            )

    def _release_write(self) -> None:
        self._write_gate.release()

    def _require_ready(self, project_id: str, correlation_id: str) -> Project:
        inspection = self._store.inspect_project_state()
        integrity = self._store.inspect_integrity(deep=False)
        if (
            inspection.state is ProjectState.DEGRADED
            or integrity.state is ProjectState.DEGRADED
            or integrity.issues
        ):
            self._raise_error(
                correlation_id=correlation_id,
                code="PRECONDITION_FAILED",
                message="project is degraded",
                details={"condition": "project_degraded", "current_state": "DEGRADED"},
            )
        if inspection.state is not ProjectState.READY or inspection.project is None:
            self._raise_error(
                correlation_id=correlation_id,
                code="PRECONDITION_FAILED",
                message="project is not ready",
                details={
                    "condition": "project_not_ready",
                    "current_state": inspection.state.value,
                },
            )
        if inspection.project.project_id != project_id:
            self._raise_error(
                correlation_id=correlation_id,
                code="NOT_FOUND",
                message="project was not found",
                details={"resource_type": "project", "resource_id": project_id},
            )
        return inspection.project

    def health_check(self, request: HealthCheckRequest) -> HealthCheckResult:
        del request
        common = self._common()
        inspection = self._store.inspect_project_state()
        integrity = self._store.inspect_integrity(deep=False)
        degraded = inspection.state is ProjectState.DEGRADED or bool(integrity.issues)
        checks = (
            HealthCheck(name="mcp", status="OK", code="adapter_ready"),
            HealthCheck(
                name="sqlite",
                status="WARN" if degraded else "OK",
                code="degraded" if degraded else "available",
            ),
            HealthCheck(name="registry", status="OK", code="sealed"),
            HealthCheck(
                name="project",
                status="WARN"
                if inspection.state
                in {ProjectState.UNINITIALIZED, ProjectState.STORAGE_READY}
                else ("FAIL" if degraded else "OK"),
                code=inspection.state.value.lower(),
            ),
        )
        return HealthCheckResult(
            **common,
            status="DEGRADED" if degraded else "OK",
            project_state="DEGRADED" if degraded else inspection.state.value,
            ready_for_project_creation=inspection.state
            in {ProjectState.UNINITIALIZED, ProjectState.STORAGE_READY}
            and not degraded,
            versions=HealthVersions.from_version_set(self._versions),
            registry=self._registry_summary,
            checks=checks,
            warnings=(),
        )

    def create_project(self, request: CreateProjectRequest) -> CreateProjectResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        self._acquire_write(correlation_id)
        try:
            inspection = self._store.inspect_project_state()
            integrity = self._store.inspect_integrity(deep=False)
            state_inspection_failed = (
                inspection.state is ProjectState.DEGRADED
                or integrity.issues == ("project_state",)
            )
            if not state_inspection_failed and (
                inspection.state is ProjectState.DEGRADED
                or integrity.state is ProjectState.DEGRADED
                or integrity.issues
            ):
                self._raise_error(
                    correlation_id=correlation_id,
                    code="PRECONDITION_FAILED",
                    message="project is degraded",
                    details={
                        "condition": "project_degraded",
                        "current_state": "DEGRADED",
                    },
                )
            display_name = request.display_name
            if display_name is None:
                display_name = (
                    inspection.project.display_name
                    if inspection.project
                    else self._default_display_name
                )
            command = CreateProjectCommand(
                operation=WriteOperation(
                    operation_id=request.operation_id,
                    canonical_request_hash=create_project_request_hash(display_name),
                ),
                display_name=display_name,
            )
            try:
                stored = self._store.create_or_replay_project(command)
            except ProjectStoreError as error:
                metadata_mismatch = (
                    error.code == "CONFLICT"
                    and error.details.get("conflict_type")
                    == "project_metadata_mismatch"
                )
                if request.display_name is not None or not metadata_mismatch:
                    self._raise_store(error, correlation_id)
                locked_inspection = self._store.inspect_project_state()
                if (
                    locked_inspection.state is not ProjectState.READY
                    or locked_inspection.project is None
                ):
                    self._raise_store(error, correlation_id)
                locked_display_name = locked_inspection.project.display_name
                locked_command = CreateProjectCommand(
                    operation=WriteOperation(
                        operation_id=request.operation_id,
                        canonical_request_hash=create_project_request_hash(
                            locked_display_name
                        ),
                    ),
                    display_name=locked_display_name,
                )
                try:
                    stored = self._store.create_or_replay_project(locked_command)
                except ProjectStoreError as locked_error:
                    self._raise_store(locked_error, correlation_id)
            return CreateProjectResult(
                **common,
                operation_id=request.operation_id,
                replayed=stored.replayed,
                project_id=stored.project.project_id,
                display_name=stored.project.display_name,
                project_format_version=stored.project.project_format_version,
                project_state="READY",
                created=stored.created,
                created_at=_timestamp(stored.project.created_at),
            )
        finally:
            self._release_write()

    @staticmethod
    def _record_key(
        item: AttemptTrace | ValidationTrace,
    ) -> tuple[str, str, str]:
        return (
            item.created_at,
            item.record_type,
            item.attempt_id if isinstance(item, AttemptTrace) else item.validation_id,
        )

    @staticmethod
    def _encode_cursor(document: JsonObject) -> str:
        return (
            base64.urlsafe_b64encode(canonical_json_bytes(document))
            .decode("ascii")
            .rstrip("=")
        )

    def _decode_experiment_cursor(
        self,
        cursor: str,
        request: GetProjectStatusExperimentRequest,
        correlation_id: str,
    ) -> tuple[str, str, str]:
        def invalid() -> NoReturn:
            self._raise_error(
                correlation_id=correlation_id,
                code="INVALID_REQUEST",
                message="cursor is malformed or bound to another view or experiment",
                details={"field_path": "/cursor", "reason": "invalid_cursor"},
            )

        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
            decoded = strict_json_loads(raw)
        except (binascii.Error, UnicodeDecodeError, ValueError):
            invalid()
        if not isinstance(decoded, dict) or set(decoded) != {
            "view",
            "experiment_id",
            "created_at",
            "record_type",
            "entity_id",
        }:
            invalid()
        view = decoded.get("view")
        experiment_id = decoded.get("experiment_id")
        created_at = decoded.get("created_at")
        record_type = decoded.get("record_type")
        entity_id = decoded.get("entity_id")
        if (
            view != "experiment"
            or experiment_id != request.experiment_id
            or not isinstance(created_at, str)
            or not isinstance(record_type, str)
            or not isinstance(entity_id, str)
            or record_type not in {"attempt", "validation"}
        ):
            invalid()
        return (created_at, record_type, entity_id)

    @staticmethod
    def _record_cursor(
        item: AttemptTrace | ValidationTrace,
        experiment_id: str,
    ) -> JsonObject:
        if isinstance(item, AttemptTrace):
            return {
                "view": "experiment",
                "experiment_id": experiment_id,
                "created_at": item.created_at,
                "record_type": "attempt",
                "entity_id": item.attempt_id,
            }
        return {
            "view": "experiment",
            "experiment_id": experiment_id,
            "created_at": item.created_at,
            "record_type": "validation",
            "entity_id": item.validation_id,
        }

    def get_project_status(
        self, request: GetProjectStatusRequest
    ) -> GetProjectStatusResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        self._require_ready(request.project_id, correlation_id)
        try:
            if isinstance(request, GetProjectStatusSummaryRequest):
                snapshot = self._store.get_project_status(request.project_id)
                page_limit = request.limit if request.limit is not None else 20
                items = snapshot.experiments[:page_limit]
                truncated = snapshot.truncated or len(items) < len(snapshot.experiments)
                return GetProjectStatusSummaryResult(
                    **common,
                    view="summary",
                    project=_project_summary(snapshot.project),
                    attempt_status_counts=snapshot.attempt_status_counts,
                    validation_status_counts=snapshot.validation_status_counts,
                    registry_fingerprint=self._registry_summary.fingerprint,
                    last_activity_at=_timestamp(snapshot.last_activity_at),
                    experiments=ExperimentItems(
                        items=items, truncated=truncated, next_cursor=None
                    ),
                )
            assert isinstance(request, GetProjectStatusExperimentRequest)
            trace = self._store.get_experiment_trace(
                ExperimentTraceQuery(
                    project_id=request.project_id, experiment_id=request.experiment_id
                )
            )
        except ProjectStoreError as error:
            self._raise_store(error, correlation_id)
        page_limit = request.limit if request.limit is not None else 20
        records: list[AttemptTrace | ValidationTrace] = [
            *(_attempt_trace(item) for item in trace.attempts),
            *(_validation_trace(item) for item in trace.validations),
        ]
        records.sort(key=self._record_key)
        if request.cursor is not None:
            cursor_key = self._decode_experiment_cursor(
                request.cursor, request, correlation_id
            )
            records = [
                record for record in records if self._record_key(record) > cursor_key
            ]

        project = _project_summary(trace.project)
        experiment = _experiment_record(trace.experiment, self._versions)

        def response_bytes(page: list[AttemptTrace | ValidationTrace]) -> int:
            candidate = GetProjectStatusExperimentResult(
                **common,
                view="experiment",
                project=project,
                experiment=experiment,
                trace=tuple(page),
            )
            return len(
                canonical_json_bytes(
                    cast(JsonObject, candidate.model_dump(mode="json"))
                )
            )

        page: list[AttemptTrace | ValidationTrace] = []
        next_cursor: str | None = None
        for record in records:
            if len(page) >= page_limit:
                next_cursor = self._encode_cursor(
                    self._record_cursor(page[-1], request.experiment_id)
                )
                break
            candidate_page = page + [record]
            observed = response_bytes(candidate_page)
            if observed > _MAX_RESPONSE_BYTES:
                if not page:
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="RESOURCE_LIMIT_EXCEEDED",
                        message="inline response exceeds the byte budget",
                        details={
                            "resource": "inline_response_bytes",
                            "limit": _MAX_RESPONSE_BYTES,
                            "observed": observed,
                        },
                    )
                next_cursor = self._encode_cursor(
                    self._record_cursor(page[-1], request.experiment_id)
                )
                break
            page = candidate_page
        return GetProjectStatusExperimentResult(
            **common,
            view="experiment",
            project=project,
            experiment=experiment,
            trace=tuple(page),
            next_cursor=next_cursor,
        )

    def list_capabilities(
        self, request: ListCapabilitiesRequest
    ) -> ListCapabilitiesResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        state = self._store.inspect_project_state().state
        integrity = self._store.inspect_integrity(deep=False)
        if (
            state is ProjectState.DEGRADED
            or integrity.state is ProjectState.DEGRADED
            or integrity.issues
        ):
            self._raise_error(
                correlation_id=correlation_id,
                code="PRECONDITION_FAILED",
                message="project is degraded",
                details={"condition": "project_degraded", "current_state": "DEGRADED"},
            )
        if isinstance(request, ListCapabilitiesSummaryRequest):
            return ListCapabilitiesSummaryResult(
                **common,
                detail="summary",
                registry=self._registry_summary,
                capabilities=tuple(
                    self._registry.list_summaries(
                        request.category, request.capability_id
                    )
                ),
            )
        assert isinstance(request, ListCapabilitiesContractRequest)
        available = self._registry.list_summaries(None, request.capability_id)
        if not available:
            self._raise_error(
                correlation_id=correlation_id,
                code="NOT_FOUND",
                message="capability was not found",
                details={
                    "resource_type": "capability",
                    "resource_id": request.capability_id,
                },
            )
        if all(item.contract_version != request.contract_version for item in available):
            self._raise_error(
                correlation_id=correlation_id,
                code="UNSUPPORTED_VERSION",
                message="capability version is not supported",
                details=UnsupportedVersionDetails(
                    subject=f"capability_contract:{request.capability_id}",
                    requested_version=request.contract_version,
                    supported_versions=tuple(
                        item.contract_version for item in available
                    ),
                ),
            )
        try:
            descriptor = self._registry.resolve(
                request.capability_id, request.contract_version
            ).descriptor
        except RegistryError as error:
            self._raise_error(
                correlation_id=correlation_id,
                code=error.code,
                message=str(error),
                details=cast(JsonObject, error.details),
            )
        capability = CapabilityContract(
            capability_id=descriptor.capability_id,
            contract_version=descriptor.contract_version,
            title=descriptor.title,
            summary=descriptor.summary,
            category=descriptor.category,
            tags=descriptor.tags,
            determinism=descriptor.determinism,
            randomness=descriptor.randomness,
            input_schema_hash=descriptor.input_schema.schema_hash,
            canonical_input_schema_version=descriptor.canonical_input_schema.schema_version,
            canonical_input_schema_hash=descriptor.canonical_input_schema.schema_hash,
            success_schema_hash=descriptor.success_schema.schema_hash,
            failure_schema_hash=descriptor.failure_schema.schema_hash,
            capability_api_version=cast(
                Literal["modeling-capability/0.1.0", "modeling-capability/1.0.0"],
                descriptor.capability_api_version,
            ),
            implementation_id=descriptor.implementation_id,
            implementation_version=descriptor.implementation_version,
            input_schema=descriptor.input_schema.schema,
            canonical_input_schema=descriptor.canonical_input_schema.schema,
            success_schema=descriptor.success_schema.schema,
            failure_schema=descriptor.failure_schema.schema,
            default_limits=descriptor.default_limits,
            maximum_limits=descriptor.maximum_limits,
            artifact_roles=(),
            validators=descriptor.validators,
            context_ref=descriptor.context_ref,
        )
        return ListCapabilitiesContractResult(
            **common,
            detail="contract",
            registry=self._registry_summary,
            capability=capability,
        )

    def _run_result(
        self,
        *,
        common: _CommonFields,
        operation_id: str,
        replayed: bool,
        experiment: Experiment,
        attempt: Attempt,
        artifact: Artifact | None,
    ) -> RunExperimentResult:
        base: _RunResultFields = {
            **common,
            "operation_id": operation_id,
            "replayed": replayed,
            "experiment_id": experiment.experiment_id,
            "attempt_id": attempt.attempt_id,
            "capability_id": experiment.capability_id,
            "contract_version": experiment.contract_version,
            "implementation_id": attempt.implementation_id,
            "implementation_version": attempt.implementation_version,
            "randomness": attempt.randomness,
            "seed": attempt.seed,
            "warnings": attempt.warnings,
        }
        if attempt.status is AttemptStatus.SUCCEEDED:
            if attempt.result is None or not isinstance(
                attempt.result.result_payload,
                (SuccessResultPayload, CoupledHeaveSuccessResultPayload),
            ):
                raise ValueError("successful attempt is missing a success payload")
            return RunExperimentSucceededResult(
                **base,
                attempt_status="SUCCEEDED",
                result_kind="success",
                result_hash=attempt.result.result_hash,
                result_summary=attempt.result.result_payload.data,
                artifacts=(_public_artifact(artifact),) if artifact else None,
            )
        if attempt.status is AttemptStatus.NUMERICAL_FAILURE:
            if attempt.result is None or not isinstance(
                attempt.result.result_payload, FailureResultPayload
            ):
                raise ValueError(
                    "numerical-failure attempt is missing a failure payload"
                )
            return RunExperimentNumericalFailureResult(
                **base,
                attempt_status="NUMERICAL_FAILURE",
                result_kind="numerical_failure",
                result_hash=attempt.result.result_hash,
                result_summary=attempt.result.result_payload.data,
                artifacts=(_public_artifact(artifact),) if artifact else None,
            )
        if attempt.status is AttemptStatus.ERRORED:
            if attempt.system_error is None:
                raise ValueError("errored attempt is missing its system error")
            return RunExperimentErroredResult(
                **base,
                attempt_status="ERRORED",
                system_error=attempt.system_error,
            )
        if attempt.status in {AttemptStatus.TIMED_OUT, AttemptStatus.ABANDONED}:
            if attempt.terminal_reason is None:
                raise ValueError("stopped attempt is missing its terminal reason")
            return RunExperimentStoppedResult(
                **base,
                attempt_status=cast(
                    Literal["TIMED_OUT", "ABANDONED"],
                    attempt.status.value,
                ),
                terminal_reason=attempt.terminal_reason.value,
            )
        raise ValueError("synchronous run response cannot expose an active attempt")

    def run_experiment(self, request: RunExperimentRequest) -> RunExperimentResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        self._acquire_write(correlation_id)
        try:
            self._require_ready(request.project_id, correlation_id)
            # C1: MMIR must be confirmed before any experiment is run.
            # Only enforce when MMIR has been put (C1 context); M1a projects
            # without any MMIR proceed normally.
            if hasattr(self, "_mmir_revisions") and self._mmir_revisions:
                if not getattr(self, "_confirmed_mmir", None):
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="PRECONDITION_FAILED",
                        message="MMIR has not been confirmed for this project",
                        details={
                            "condition": "mmir_not_confirmed",
                            "current_state": "unconfirmed",
                        },
                    )
            if isinstance(request.payload, CoupledHeaveInput):
                confirmed = getattr(self, "_confirmed_mmir", {}).get(
                    request.payload.subproblem_id
                )
                if confirmed != request.payload.mmir_revision:
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="PRECONDITION_FAILED",
                        message="the exact MMIR revision is not confirmed",
                        details={
                            "condition": "mmir_not_confirmed",
                            "current_state": "stale_or_unconfirmed",
                        },
                    )
                registered = getattr(self, "_asset_snapshots", {})
                if any(
                    registered.get(item.label) != item
                    for item in request.payload.asset_snapshots
                ):
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="INTEGRITY_FAILURE",
                        message="asset snapshot does not match registered evidence",
                        details={"subject": "input_snapshot"},
                    )
            rerun_experiment: Experiment | None = None
            recorded_attempt: Attempt | None = None
            if request.mode == "rerun":
                try:
                    trace = self._store.get_experiment_trace(
                        ExperimentTraceQuery(
                            project_id=request.project_id,
                            experiment_id=cast(str, request.experiment_id),
                        )
                    )
                except ProjectStoreError as error:
                    self._raise_store(error, correlation_id)
                rerun_experiment = trace.experiment
                if not trace.attempts:
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="INTEGRITY_FAILURE",
                        message="rerun experiment has no recorded attempt",
                        details={"subject": "database_relation"},
                    )
                recorded_attempt = min(
                    trace.attempts, key=lambda item: (item.created_at, item.attempt_id)
                )
                capability_id = rerun_experiment.capability_id
                contract_version = rerun_experiment.contract_version
            else:
                capability_id = request.capability.capability_id
                contract_version = request.capability.contract_version
            try:
                capability = self._registry.resolve(capability_id, contract_version)
            except RegistryError as error:
                if request.mode == "rerun":
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="UNSUPPORTED_VERSION",
                        message="recorded capability contract is unavailable",
                        details=UnsupportedVersionDetails(
                            subject="capability_contract",
                            requested_version=contract_version,
                            supported_versions=(),
                        ),
                    )
                self._raise_error(
                    correlation_id=correlation_id,
                    code=error.code,
                    message=str(error),
                    details=cast(JsonObject, error.details),
                )
            descriptor = capability.descriptor
            if recorded_attempt is not None and (
                descriptor.implementation_id != recorded_attempt.implementation_id
                or descriptor.implementation_version
                != recorded_attempt.implementation_version
            ):
                self._raise_error(
                    correlation_id=correlation_id,
                    code="UNSUPPORTED_VERSION",
                    message="recorded capability implementation is unavailable",
                    details=UnsupportedVersionDetails(
                        subject="capability_implementation",
                        requested_version=recorded_attempt.implementation_version,
                        supported_versions=(descriptor.implementation_version,),
                    ),
                )
            execution = (
                rerun_experiment.execution_policy
                if rerun_experiment is not None
                else request.execution or ExecutionOptions()
            )
            if descriptor.randomness == "not_used" and execution.seed is not None:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INVALID_REQUEST",
                    message="deterministic capability does not accept a seed",
                    details={
                        "field_path": "/execution/seed",
                        "reason": "invalid_combination",
                    },
                )
            if execution.timeout_ms > descriptor.maximum_limits.timeout_ms:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INVALID_REQUEST",
                    message="requested timeout exceeds the capability maximum",
                    details={
                        "field_path": "/execution/timeout_ms",
                        "reason": "out_of_range",
                    },
                )
            try:
                if rerun_experiment is not None:
                    canonical = CanonicalInputRecord(
                        canonical_input_schema_version=(
                            rerun_experiment.canonical_input_schema_version
                        ),
                        canonical_payload=cast(
                            JsonObject,
                            rerun_experiment.canonical_payload.model_dump(mode="json"),
                        ),
                        canonical_payload_hash=(
                            rerun_experiment.canonical_payload_hash
                        ),
                        model_snapshot_hash=rerun_experiment.model_snapshot_hash,
                        data_snapshot_references=tuple(
                            item.model_dump(mode="json")
                            for item in rerun_experiment.data_snapshot_references
                        ),
                        data_snapshot_set_hash=(
                            rerun_experiment.data_snapshot_set_hash
                        ),
                    )
                else:
                    canonical = capability.normalize_and_validate(
                        cast(JsonObject, request.payload.model_dump(mode="json"))
                    )
            except CapabilityInputRejected as error:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INVALID_REQUEST",
                    message=str(error),
                    details={
                        "field_path": error.field_path,
                        "reason": error.reason,
                    },
                )
            except CapabilitySecurityViolation as error:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="SECURITY_VIOLATION",
                    message=str(error),
                    details={"rule": error.rule},
                )
            except CapabilityInputResourceLimitExceeded as error:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="RESOURCE_LIMIT_EXCEEDED",
                    message=str(error),
                    details={
                        "resource": error.resource,
                        "limit": error.limit,
                        "observed": error.observed,
                    },
                )

            operation = WriteOperation(
                operation_id=request.operation_id,
                canonical_request_hash=run_experiment_request_hash(
                    project_id=request.project_id,
                    mode=request.mode,
                    capability_id=request.capability.capability_id,
                    contract_version=request.capability.contract_version,
                    canonical_input=canonical,
                    execution=execution,
                    experiment_id=request.experiment_id,
                ),
            )
            created_at = _millisecond_utc(self._clock.utc_now())
            input_snapshot: InputSnapshot | None = None
            environment_snapshot: EnvironmentSnapshot | None = None
            if self._schema_two:
                if request.mode == "new":
                    input_snapshot = InputSnapshot(
                        input_snapshot_id=self._ids.new_uuid4(),
                        canonical_input_schema_version=(
                            canonical.canonical_input_schema_version
                        ),
                        canonical_payload_hash=canonical.canonical_payload_hash,
                        model_snapshot_hash=canonical.model_snapshot_hash,
                        data_snapshot_references=tuple(
                            DataSnapshotReference.model_validate(item, strict=True)
                            for item in canonical.data_snapshot_references
                        ),
                        data_snapshot_set_hash=canonical.data_snapshot_set_hash,
                        created_at=created_at,
                    )
                environment_document = cast(JsonObject, self._environment_document)
                environment_snapshot = EnvironmentSnapshot(
                    environment_snapshot_id=self._ids.new_uuid4(),
                    environment_document=environment_document,
                    environment_hash=sha256_json(environment_document),
                    created_at=created_at,
                )
            experiment = rerun_experiment or Experiment(
                experiment_id=self._ids.new_uuid4(),
                project_id=request.project_id,
                capability_id=descriptor.capability_id,
                contract_version=descriptor.contract_version,
                canonical_input_schema_version=cast(
                    Literal[
                        "numerical.root_finding.canonical-input/0.1.0",
                        "numerical.root_finding.canonical-input/1.0.0",
                        "dynamics.coupled_heave.canonical-input/0.1.0",
                    ],
                    canonical.canonical_input_schema_version,
                ),
                canonical_payload=_CANONICAL_PAYLOAD.validate_json(
                    canonical_json_bytes(canonical.canonical_payload), strict=True
                ),
                canonical_payload_hash=canonical.canonical_payload_hash,
                model_snapshot_hash=canonical.model_snapshot_hash,
                data_snapshot_references=tuple(
                    DataSnapshotReference.model_validate(item, strict=True)
                    for item in canonical.data_snapshot_references
                ),
                data_snapshot_set_hash=canonical.data_snapshot_set_hash,
                execution_policy=execution,
                created_at=created_at,
            )
            pending = Attempt(
                attempt_id=self._ids.new_uuid4(),
                experiment_id=experiment.experiment_id,
                implementation_id=descriptor.implementation_id,
                implementation_version=descriptor.implementation_version,
                environment_summary=self._environment_summary,
                randomness=descriptor.randomness,
                seed=execution.seed,
                session_id=self._session_id,
                status=AttemptStatus.PENDING,
                created_at=created_at,
            )
            try:
                begun = self._store.begin_run(
                    BeginRunCommand(
                        operation=operation,
                        experiment=experiment,
                        attempt=pending,
                        input_snapshot=input_snapshot,
                        environment_snapshot=environment_snapshot,
                        mode=request.mode,
                    )
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            if begun.replayed:
                return self._run_result(
                    common=common,
                    operation_id=request.operation_id,
                    replayed=True,
                    experiment=begun.experiment,
                    attempt=begun.attempt,
                    artifact=begun.artifact,
                )

            self._faults.check(
                FaultPoint.AFTER_ATTEMPT_CREATED,
                {"attempt_id": pending.attempt_id, "session_id": self._session_id},
            )

            started_at = _millisecond_utc(self._clock.utc_now())
            try:
                self._store.mark_attempt_running(
                    pending.attempt_id, started_at, self._session_id
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            self._faults.check(
                FaultPoint.AFTER_ATTEMPT_RUNNING,
                {"attempt_id": pending.attempt_id, "session_id": self._session_id},
            )
            deadline = self._clock.monotonic() + (
                min(
                    execution.timeout_ms,
                    descriptor.maximum_limits.timeout_ms,
                    60_000,
                )
                / 1000.0
            )
            artifact_sink: AttemptArtifactSink | None = None
            if self._schema_two and self._artifact_store is not None:
                artifact_sink = AttemptArtifactSink(
                    self._artifact_store, pending.attempt_id
                )
            result_snapshot: ResultSnapshot | None = None
            system_error: ErrorResponse | None = None
            terminal_reason: TerminalReason | None = None
            numerical_failure = None
            try:
                execution_context = ExecutionContext(
                    attempt_id=pending.attempt_id,
                    randomness=descriptor.randomness,
                    seed=execution.seed,
                    deadline=deadline,
                    clock=self._clock,
                    cancellation=self._cancellation,
                    artifact_sink=artifact_sink,
                )
                if descriptor.capability_id == "dynamics.coupled_heave":
                    worker_result = run_worker(
                        capability_id=descriptor.capability_id,
                        contract_version=descriptor.contract_version,
                        canonical_input_json=canonical.model_dump_json(),
                        execution_context=execution_context,
                        capability_registry_json=("m1b" if self._schema_two else "m1a"),
                    )
                    outcome = ExecutionOutcome(
                        result_kind=cast(
                            Literal["success", "numerical_failure"],
                            worker_result.result_kind,
                        ),
                        result_payload=_RESULT_PAYLOAD.validate_json(
                            canonical_json_bytes(worker_result.result_payload),
                            strict=True,
                        ),
                    )
                else:
                    outcome = capability.execute(canonical, execution_context)
                result_document = cast(
                    JsonObject,
                    outcome.result_payload.model_dump(mode="python"),
                )
                strict_result_payload = _RESULT_PAYLOAD.validate_python(
                    result_document, strict=True
                )
                if strict_result_payload.result_kind != outcome.result_kind:
                    raise ValueError("execution outcome payload kind does not match")
                result_hash = sha256_json(
                    cast(JsonObject, strict_result_payload.model_dump(mode="json"))
                )
                result_snapshot = ResultSnapshot(
                    result_snapshot_id=self._ids.new_uuid4(),
                    attempt_id=pending.attempt_id,
                    result_kind=ResultKind(outcome.result_kind),
                    result_schema_version=self._versions.result_schema_version,
                    result_hash=result_hash,
                    result_payload=strict_result_payload,
                )
                if outcome.result_kind == "success":
                    final_status = AttemptStatus.SUCCEEDED
                else:
                    final_status = AttemptStatus.NUMERICAL_FAILURE
                    if not isinstance(strict_result_payload, FailureResultPayload):
                        raise ValueError("numerical failure has the wrong payload type")
                    numerical_failure = strict_result_payload.data
            except ExecutionDeadlineExceeded:
                final_status = AttemptStatus.TIMED_OUT
                terminal_reason = TerminalReason.DEADLINE_EXCEEDED
            except ExecutionCancelled:
                final_status = AttemptStatus.ABANDONED
                terminal_reason = TerminalReason.HOST_CANCELLED
            except ExecutionResourceLimitExceeded as error:
                final_status = AttemptStatus.ERRORED
                system_error = self._error_response(
                    correlation_id=correlation_id,
                    code="RESOURCE_LIMIT_EXCEEDED",
                    message=str(error),
                    details={
                        "resource": error.resource,
                        "limit": error.limit,
                        "observed": error.observed,
                    },
                )
            except Exception:
                final_status = AttemptStatus.ERRORED
                system_error = self._error_response(
                    correlation_id=correlation_id,
                    code="INTERNAL_ERROR",
                    message="capability execution failed",
                    details={"event_id": self._ids.new_uuid4()},
                )

            result_artifact: Artifact | None = None
            if (
                self._schema_two
                and artifact_sink is not None
                and result_snapshot is not None
                and system_error is None
            ):
                try:
                    manifest = artifact_sink.publish_json(
                        "result",
                        result_snapshot.result_payload.model_dump(mode="json"),
                        self._result_schema_id,
                    )
                    if manifest.artifact_id != result_snapshot.result_hash:
                        raise ArtifactStoreError(
                            code="INTEGRITY_FAILURE",
                            message="published artifact identity does not match the "
                            "result hash",
                        )
                    result_artifact = self._artifact_record(manifest)
                except ArtifactStoreError as error:
                    result_snapshot = None
                    numerical_failure = None
                    final_status = AttemptStatus.ERRORED
                    if error.code == "RESOURCE_LIMIT_EXCEEDED":
                        system_error = self._error_response(
                            correlation_id=correlation_id,
                            code="RESOURCE_LIMIT_EXCEEDED",
                            message=str(error),
                            details=cast(ErrorDetails, cast(JsonObject, error.details)),
                        )
                    else:
                        system_error = self._error_response(
                            correlation_id=correlation_id,
                            code="INTERNAL_ERROR",
                            message="result artifact publication failed",
                            details={"event_id": self._ids.new_uuid4()},
                        )
                else:
                    self._faults.check(
                        FaultPoint.AFTER_ARTIFACT_PUBLISHED,
                        {
                            "attempt_id": pending.attempt_id,
                            "artifact_id": manifest.artifact_id,
                        },
                    )
                    if self._clock.monotonic() > deadline:
                        result_snapshot = None
                        numerical_failure = None
                        result_artifact = None
                        final_status = AttemptStatus.TIMED_OUT
                        terminal_reason = TerminalReason.DEADLINE_EXCEEDED

            final_attempt = Attempt(
                attempt_id=pending.attempt_id,
                experiment_id=pending.experiment_id,
                implementation_id=pending.implementation_id,
                implementation_version=pending.implementation_version,
                environment_summary=pending.environment_summary,
                randomness=pending.randomness,
                seed=pending.seed,
                session_id=pending.session_id,
                status=final_status,
                created_at=pending.created_at,
                started_at=started_at,
                finished_at=_millisecond_utc(self._clock.utc_now()),
                warnings=(),
                result=result_snapshot,
                system_error=system_error,
                numerical_failure=numerical_failure,
                terminal_reason=terminal_reason,
            )
            try:
                stored = self._store.complete_attempt(
                    CompleteAttemptCommand(
                        operation=operation,
                        attempt=final_attempt,
                        result_artifact=result_artifact,
                    )
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            self._faults.check(
                FaultPoint.AFTER_DATABASE_COMMIT,
                {"attempt_id": pending.attempt_id},
            )
            return self._run_result(
                common=common,
                operation_id=request.operation_id,
                replayed=False,
                experiment=experiment,
                attempt=stored.attempt,
                artifact=stored.artifact,
            )
        finally:
            self._release_write()

    def _validation_result(
        self,
        *,
        common: _CommonFields,
        operation_id: str,
        replayed: bool,
        validation: Validation,
        report_artifact: Artifact | None,
    ) -> ValidateExperimentResult:
        base: _ValidationResultFields = {
            **common,
            "operation_id": operation_id,
            "replayed": replayed,
            "validation_id": validation.validation_id,
            "attempt_id": validation.attempt_id,
            "result_hash": validation.result_hash,
            "validator_id": validation.validator_id,
            "validator_implementation_id": (validation.validator_implementation_id),
            "validator_implementation_version": (
                validation.validator_implementation_version
            ),
            "policy_version": validation.policy_version,
            "policy_hash": validation.policy_hash,
        }
        if validation.status is ValidationStatus.SUCCEEDED:
            if (
                validation.outcome is None
                or validation.metrics is None
                or validation.validation_report_hash is None
            ):
                raise ValueError("successful validation is missing its report")
            return ValidateExperimentSucceededResult(
                **base,
                validation_status="SUCCEEDED",
                outcome=validation.outcome.value,
                metrics=validation.metrics,
                validation_report_hash=validation.validation_report_hash,
                report_artifact=(
                    _public_artifact(report_artifact) if report_artifact else None
                ),
            )
        if validation.status is ValidationStatus.ERRORED:
            if validation.operational_error is None:
                raise ValueError("errored validation is missing its error")
            return ValidateExperimentErroredResult(
                **base,
                validation_status="ERRORED",
                operational_error=validation.operational_error,
            )
        if validation.status in {
            ValidationStatus.TIMED_OUT,
            ValidationStatus.ABANDONED,
        }:
            if validation.terminal_reason is None:
                raise ValueError("stopped validation is missing its reason")
            return ValidateExperimentStoppedResult(
                **base,
                validation_status=cast(
                    Literal["TIMED_OUT", "ABANDONED"],
                    validation.status.value,
                ),
                terminal_reason=validation.terminal_reason.value,
            )
        raise ValueError(
            "synchronous validation response cannot expose an active validation"
        )

    def validate_experiment(
        self, request: ValidateExperimentRequest
    ) -> ValidateExperimentResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        self._acquire_write(correlation_id)
        try:
            self._require_ready(request.project_id, correlation_id)
            try:
                source = self._store.get_validation_source(
                    request.project_id, request.attempt_id
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)

            payload_document = cast(
                JsonObject,
                source.experiment.canonical_payload.model_dump(mode="json"),
            )
            observed_input_hash = sha256_json(payload_document)
            if "expression_ast" in payload_document:
                observed_model_hash = sha256_json(
                    {
                        "language": "math-expr-v1",
                        "ast": payload_document["expression_ast"],
                    }
                )
            elif isinstance(payload_document.get("model"), dict):
                observed_model_hash = sha256_json(
                    cast(JsonObject, payload_document["model"])
                )
            else:
                observed_model_hash = ""
            data_documents = [
                cast(JsonObject, item.model_dump(mode="json"))
                for item in source.experiment.data_snapshot_references
            ]
            observed_data_hash = sha256_json(data_documents)
            if (
                observed_input_hash != source.experiment.canonical_payload_hash
                or observed_model_hash != source.experiment.model_snapshot_hash
                or observed_data_hash != source.experiment.data_snapshot_set_hash
            ):
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INTEGRITY_FAILURE",
                    message="committed input snapshot failed integrity checks",
                    details={
                        "subject": "input_snapshot",
                        "expected_hash": source.experiment.canonical_payload_hash,
                        "observed_hash": observed_input_hash,
                    },
                )
            if source.attempt.result is None:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="PRECONDITION_FAILED",
                    message="attempt has no success result",
                    details={
                        "condition": "missing_success_result",
                        "current_state": source.attempt.status.value,
                    },
                )
            result_document = cast(
                JsonObject,
                source.attempt.result.result_payload.model_dump(mode="json"),
            )
            observed_result_hash = sha256_json(result_document)
            if (
                observed_result_hash != source.attempt.result.result_hash
                or request.expected_result_hash != source.attempt.result.result_hash
            ):
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INTEGRITY_FAILURE",
                    message="result hash does not match committed evidence",
                    details={
                        "subject": "result_hash",
                        "expected_hash": request.expected_result_hash,
                        "observed_hash": observed_result_hash,
                    },
                )

            verified_result: VerifiedResult | None = None
            if self._schema_two:
                try:
                    verified_result = self._store.load_verified_result(
                        request.attempt_id
                    )
                except ProjectStoreError as error:
                    self._raise_store(error, correlation_id)
                assert verified_result is not None
                verified_payload = cast(
                    JsonObject,
                    verified_result.result_snapshot.result_payload.model_dump(
                        mode="json"
                    ),
                )
                if (
                    sha256_json(verified_payload)
                    != verified_result.result_snapshot.result_hash
                    or verified_result.result_snapshot.result_hash
                    != source.attempt.result.result_hash
                    or request.expected_result_hash
                    != verified_result.result_snapshot.result_hash
                    or verified_result.artifact is None
                    or verified_result.artifact.artifact_id
                    != verified_result.result_snapshot.result_hash
                ):
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="INTEGRITY_FAILURE",
                        message="verified result does not match committed evidence",
                        details={
                            "subject": "result_artifact",
                            "expected_hash": request.expected_result_hash,
                            "observed_hash": verified_result.result_snapshot.result_hash,
                        },
                    )

            try:
                validator = self._registry.resolve_validator(
                    request.validator_id,
                    source.experiment.capability_id,
                    source.experiment.contract_version,
                    request.policy_version,
                )
                capability = self._registry.resolve(
                    source.experiment.capability_id,
                    source.experiment.contract_version,
                )
            except RegistryError as error:
                self._raise_error(
                    correlation_id=correlation_id,
                    code=error.code,
                    message=str(error),
                    details=cast(JsonObject, error.details),
                )
            if request.policy:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INVALID_REQUEST",
                    message="M1a residual validation policy must be empty",
                    details={
                        "field_path": "/policy",
                        "reason": "unknown_field",
                    },
                )

            canonical = CanonicalInputRecord(
                canonical_input_schema_version=(
                    source.experiment.canonical_input_schema_version
                ),
                canonical_payload=payload_document,
                canonical_payload_hash=source.experiment.canonical_payload_hash,
                model_snapshot_hash=source.experiment.model_snapshot_hash,
                data_snapshot_references=tuple(data_documents),
                data_snapshot_set_hash=source.experiment.data_snapshot_set_hash,
            )
            policy_hash = sha256_json(request.policy)
            operation = WriteOperation(
                operation_id=request.operation_id,
                canonical_request_hash=validate_experiment_request_hash(
                    project_id=request.project_id,
                    attempt_id=request.attempt_id,
                    expected_result_hash=request.expected_result_hash,
                    validator_id=request.validator_id,
                    policy_version=request.policy_version,
                    policy=request.policy,
                    timeout_ms=request.timeout_ms,
                ),
            )
            pending = Validation(
                validation_id=self._ids.new_uuid4(),
                attempt_id=request.attempt_id,
                expected_result_hash=request.expected_result_hash,
                result_hash=source.attempt.result.result_hash,
                validator_id=cast(
                    Literal[
                        "numerical.root_finding.residual",
                        "dynamics.coupled_heave.linear",
                        "dynamics.coupled_heave.power_law",
                    ],
                    validator.descriptor.validator_id,
                ),
                validator_implementation_id=(validator.descriptor.implementation_id),
                validator_implementation_version=(
                    validator.descriptor.implementation_version
                ),
                policy_version=request.policy_version,
                policy=request.policy,
                policy_hash=policy_hash,
                status=ValidationStatus.PENDING,
                created_at=_millisecond_utc(self._clock.utc_now()),
            )
            try:
                begun = self._store.begin_validation(
                    BeginValidationCommand(
                        operation=operation,
                        validation=pending,
                    )
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            if begun.replayed:
                return self._validation_result(
                    common=common,
                    operation_id=request.operation_id,
                    replayed=True,
                    validation=begun.validation,
                    report_artifact=begun.report_artifact,
                )

            started_at = _millisecond_utc(self._clock.utc_now())
            try:
                self._store.mark_validation_running(pending.validation_id, started_at)
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            deadline = self._clock.monotonic() + (
                min(
                    request.timeout_ms,
                    capability.descriptor.maximum_limits.timeout_ms,
                    60_000,
                )
                / 1000.0
            )
            outcome: ValidationOutcome | None = None
            metrics = None
            report_hash: str | None = None
            report_payload = None
            operational_error: ErrorResponse | None = None
            terminal_reason: TerminalReason | None = None
            verified_view = (
                verified_result.result_snapshot
                if verified_result is not None
                else source.attempt.result
            )
            try:
                raw_report_payload = validator.validate(
                    canonical,
                    ResultSnapshotView(
                        result_snapshot_id=(verified_view.result_snapshot_id),
                        capability_id=source.experiment.capability_id,
                        contract_version=source.experiment.contract_version,
                        result_schema_version=(verified_view.result_schema_version),
                        result_hash=verified_view.result_hash,
                        result_payload=verified_view.result_payload,
                    ),
                    request.policy,
                    ValidationContext(
                        deadline=deadline,
                        clock=self._clock,
                        cancellation=self._cancellation,
                    ),
                )
                report_payload = _VALIDATION_REPORT.validate_python(
                    raw_report_payload.model_dump(mode="python", warnings="none"),
                    strict=True,
                )
                outcome = ValidationOutcome(report_payload.outcome)
                metrics = report_payload.metrics
                report_hash = sha256_json(
                    cast(
                        JsonObject,
                        report_payload.model_dump(mode="json"),
                    )
                )
                final_status = ValidationStatus.SUCCEEDED
            except ExecutionDeadlineExceeded:
                final_status = ValidationStatus.TIMED_OUT
                terminal_reason = TerminalReason.DEADLINE_EXCEEDED
            except ExecutionCancelled:
                final_status = ValidationStatus.ABANDONED
                terminal_reason = TerminalReason.HOST_CANCELLED
            except ExecutionResourceLimitExceeded as error:
                final_status = ValidationStatus.ERRORED
                operational_error = self._error_response(
                    correlation_id=correlation_id,
                    code="RESOURCE_LIMIT_EXCEEDED",
                    message=str(error),
                    details={
                        "resource": error.resource,
                        "limit": error.limit,
                        "observed": error.observed,
                    },
                )
            except Exception:
                final_status = ValidationStatus.ERRORED
                operational_error = self._error_response(
                    correlation_id=correlation_id,
                    code="INTERNAL_ERROR",
                    message="validator execution failed",
                    details={"event_id": self._ids.new_uuid4()},
                )

            report_artifact: Artifact | None = None
            if (
                self._schema_two
                and self._artifact_store is not None
                and final_status is ValidationStatus.SUCCEEDED
                and report_payload is not None
            ):
                try:
                    report_manifest = self._artifact_store.publish_json(
                        "validation_report",
                        report_payload.model_dump(mode="json"),
                        self._report_schema_id,
                    )
                    if report_manifest.artifact_id != report_hash:
                        raise ArtifactStoreError(
                            code="INTEGRITY_FAILURE",
                            message=(
                                "published report artifact identity does not match "
                                "the report hash"
                            ),
                        )
                    report_artifact = self._artifact_record(report_manifest)
                except ArtifactStoreError as error:
                    report_payload = None
                    metrics = None
                    outcome = None
                    report_hash = None
                    final_status = ValidationStatus.ERRORED
                    if error.code == "RESOURCE_LIMIT_EXCEEDED":
                        operational_error = self._error_response(
                            correlation_id=correlation_id,
                            code="RESOURCE_LIMIT_EXCEEDED",
                            message=str(error),
                            details=cast(ErrorDetails, cast(JsonObject, error.details)),
                        )
                    else:
                        operational_error = self._error_response(
                            correlation_id=correlation_id,
                            code="INTERNAL_ERROR",
                            message="report artifact publication failed",
                            details={"event_id": self._ids.new_uuid4()},
                        )

            final_validation = Validation(
                validation_id=pending.validation_id,
                attempt_id=pending.attempt_id,
                expected_result_hash=pending.expected_result_hash,
                result_hash=pending.result_hash,
                validator_id=pending.validator_id,
                validator_implementation_id=(pending.validator_implementation_id),
                validator_implementation_version=(
                    pending.validator_implementation_version
                ),
                policy_version=pending.policy_version,
                policy=pending.policy,
                policy_hash=pending.policy_hash,
                status=final_status,
                created_at=pending.created_at,
                started_at=started_at,
                finished_at=_millisecond_utc(self._clock.utc_now()),
                outcome=outcome,
                metrics=metrics,
                validation_report_hash=report_hash,
                report_payload=report_payload,
                operational_error=operational_error,
                terminal_reason=terminal_reason,
            )
            try:
                stored = self._store.complete_validation(
                    CompleteValidationCommand(
                        operation=operation,
                        validation=final_validation,
                        report_artifact=report_artifact,
                    )
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            if (
                source.experiment.capability_id == "dynamics.coupled_heave"
                and final_status is ValidationStatus.SUCCEEDED
                and outcome is ValidationOutcome.PASSED
                and isinstance(
                    source.experiment.canonical_payload,
                    CanonicalCoupledHeaveInput,
                )
                and isinstance(
                    source.attempt.result.result_payload,
                    CoupledHeaveSuccessResultPayload,
                )
            ):
                mode = source.experiment.canonical_payload.damping_mode
                if not hasattr(self, "_validation_results"):
                    self._validation_results: dict[str, bool] = {}
                    self._c1_results: dict[str, CoupledHeaveSuccessResultPayload] = {}
                self._validation_results[mode] = True
                self._c1_results[mode] = source.attempt.result.result_payload
                if not hasattr(self, "_c1_context"):
                    self._c1_context: dict[str, JsonObject] = {}
                self._c1_context[mode] = {
                    "mmir_revision": source.experiment.canonical_payload.mmir_revision,
                    "asset_snapshots": [
                        item.model_dump(mode="json")
                        for item in source.experiment.canonical_payload.asset_snapshots
                    ],
                    "model": source.experiment.canonical_payload.model,
                    "result_hash": source.attempt.result.result_hash,
                    "validation_report_hash": stored.validation.validation_report_hash,
                }
            return self._validation_result(
                common=common,
                operation_id=request.operation_id,
                replayed=False,
                validation=stored.validation,
                report_artifact=stored.report_artifact,
            )
        finally:
            self._release_write()

    def register_problem_assets(
        self, request: RegisterProblemAssetsRequest
    ) -> RegisterProblemAssetsResult:
        import hashlib
        import os
        import stat
        from pathlib import Path

        common = self._common()
        correlation_id = common["correlation_id"]
        try:
            self._acquire_write(correlation_id)
        except ProjectStoreError as error:
            self._raise_store(error, correlation_id)

        try:
            state = self._store.inspect_project_state()
            if state.state != ProjectState.READY:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="PRECONDITION_FAILED",
                    message="project is not ready",
                    details={
                        "condition": "project_not_ready",
                        "current_state": state.state.value,
                    },
                )

            project_root = self._store.project_root

            snapshots: list[AssetSnapshotEntry] = []
            for entry in request.asset_paths:
                raw_path = entry.path
                if not raw_path:
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="INVALID_REQUEST",
                        message="asset path is empty",
                        details={
                            "field_path": "/asset_paths/path",
                            "reason": "invalid_format",
                        },
                    )

                # Resolve the path against the project root
                raw = Path(raw_path)
                if raw.is_absolute():
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="SECURITY_VIOLATION",
                        message="asset path must be relative and within the project root",
                        details={
                            "rule": "path_outside_project",
                        },
                    )
                resolved = (project_root / raw_path).resolve()

                if (
                    not str(resolved).startswith(str(project_root.resolve()) + os.sep)
                    and resolved != project_root.resolve()
                ):
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="SECURITY_VIOLATION",
                        message="asset path resolves outside the project root",
                        details={
                            "rule": "path_outside_project",
                        },
                    )

                try:
                    st = os.lstat(resolved)
                except OSError:
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="NOT_FOUND",
                        message=f"asset file not found: {entry.label}",
                        details={
                            "resource_type": "asset",
                            "resource_id": entry.label,
                        },
                    )

                reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                if stat.S_ISLNK(st.st_mode) or (
                    getattr(st, "st_file_attributes", 0) & reparse_flag
                ):
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="SECURITY_VIOLATION",
                        message="asset path is a symlink or reparse point",
                        details={
                            "rule": "unsafe_reparse_point",
                        },
                    )

                if not stat.S_ISREG(st.st_mode):
                    self._raise_error(
                        correlation_id=correlation_id,
                        code="INVALID_REQUEST",
                        message="asset path is not a regular file",
                        details={
                            "field_path": "/asset_paths/path",
                            "reason": "invalid_format",
                        },
                    )

                content = resolved.read_bytes()
                sha256_hex = hashlib.sha256(content).hexdigest()
                sha256_str = f"sha256:{sha256_hex}"
                snapshots.append(
                    AssetSnapshotEntry(
                        snapshot_id=self._ids.new_uuid4(),
                        label=entry.label,
                        sha256=sha256_str,
                        official_match=sha256_str in _OFFICIAL_ASSET_SHA256,
                    )
                )

            self._asset_snapshots = {item.label: item for item in snapshots}

            return RegisterProblemAssetsResult(
                **common,
                operation_id=request.operation_id,
                replayed=False,
                project_id=request.project_id,
                snapshots=tuple(snapshots),
            )
        finally:
            self._release_write()

    def put_subproblem_mmir(
        self, request: PutSubproblemMmirRequest
    ) -> PutSubproblemMmirResult:
        from modeling_core.contracts.canonical_json import sha256_json

        common = self._common()
        correlation_id = common["correlation_id"]
        try:
            self._acquire_write(correlation_id)
        except ProjectStoreError as error:
            self._raise_store(error, correlation_id)

        try:
            state = self._store.inspect_project_state()
            if state.state != ProjectState.READY:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="PRECONDITION_FAILED",
                    message="project is not ready",
                    details={
                        "condition": "project_not_ready",
                        "current_state": state.state.value,
                    },
                )

            mmir_document = request.mmir.model_dump(mode="json")
            mmir_revision = sha256_json(mmir_document)

            # Store the revision for later confirmation validation
            if not hasattr(self, "_mmir_revisions"):
                self._mmir_revisions: dict[str, str] = {}
                self._mmir_contents: dict[str, JsonObject] = {}
            self._mmir_revisions[request.subproblem_id] = mmir_revision
            self._mmir_contents[request.subproblem_id] = cast(
                JsonObject, request.mmir.model_dump(mode="json")
            )

            return PutSubproblemMmirResult(
                **common,
                operation_id=request.operation_id,
                replayed=False,
                project_id=request.project_id,
                subproblem_id=request.subproblem_id,
                mmir_revision=mmir_revision,
                status="UNCONFIRMED",
            )
        finally:
            self._release_write()

    def confirm_subproblem_mmir(
        self, request: ConfirmSubproblemMmirRequest
    ) -> ConfirmSubproblemMmirResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        try:
            self._acquire_write(correlation_id)
        except ProjectStoreError as error:
            self._raise_store(error, correlation_id)

        try:
            state = self._store.inspect_project_state()
            if state.state != ProjectState.READY:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="PRECONDITION_FAILED",
                    message="project is not ready",
                    details={
                        "condition": "project_not_ready",
                        "current_state": state.state.value,
                    },
                )

            # Verify the subproblem was previously put
            if (
                not hasattr(self, "_mmir_revisions")
                or request.subproblem_id not in self._mmir_revisions
            ):
                self._raise_error(
                    correlation_id=correlation_id,
                    code="NOT_FOUND",
                    message="subproblem MMIR has not been put yet",
                    details={
                        "resource_type": "subproblem_mmir",
                        "resource_id": request.subproblem_id,
                    },
                )

            expected_revision = self._mmir_revisions[request.subproblem_id]
            if request.mmir_revision != expected_revision:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INTEGRITY_FAILURE",
                    message="MMIR revision does not match the previously put revision",
                    details={
                        "subject": "input_snapshot",
                        "expected_hash": expected_revision,
                        "observed_hash": request.mmir_revision,
                    },
                )

            if not hasattr(self, "_confirmed_mmir"):
                self._confirmed_mmir: dict[str, str] = {}
            self._confirmed_mmir[request.subproblem_id] = request.mmir_revision

            return ConfirmSubproblemMmirResult(
                **common,
                operation_id=request.operation_id,
                replayed=False,
                project_id=request.project_id,
                subproblem_id=request.subproblem_id,
                mmir_revision=request.mmir_revision,
                status="CONFIRMED",
            )
        finally:
            self._release_write()

    def export_subproblem(
        self, request: ExportSubproblemRequest
    ) -> ExportSubproblemResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        try:
            self._acquire_write(correlation_id)
        except ProjectStoreError as error:
            self._raise_store(error, correlation_id)

        try:
            self._require_ready(request.project_id, correlation_id)

            # C1: export is blocked unless both validations (linear + power-law) are PASSED
            if not hasattr(self, "_validation_results") or not self._validation_results:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="PRECONDITION_FAILED",
                    message="export blocked: no validations have been completed",
                    details={
                        "condition": "export_blocked_validation_not_passed",
                        "current_state": "no_validations",
                    },
                )

            linear_passed = self._validation_results.get("linear", False)
            power_law_passed = self._validation_results.get("power_law", False)
            if not linear_passed or not power_law_passed:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="PRECONDITION_FAILED",
                    message="export blocked: both validations must be PASSED",
                    details={
                        "condition": "export_blocked_validation_not_passed",
                        "current_state": "validations_not_passed",
                        "linear_passed": linear_passed,
                        "power_law_passed": power_law_passed,
                    },
                )

            if self._subproblem_exporter is None or self._artifact_store is None:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="PRECONDITION_FAILED",
                    message="C1 export publication is unavailable",
                    details={
                        "condition": "export_blocked_validation_not_passed",
                        "current_state": "exporter_unavailable",
                    },
                )
            provenance: JsonObject = {
                "subproblem_id": request.subproblem_id,
                "mmir_revision": getattr(self, "_confirmed_mmir", {}).get(
                    request.subproblem_id
                ),
                "mmir": getattr(self, "_mmir_contents", {}).get(request.subproblem_id),
                "cases": getattr(self, "_c1_context", {}),
            }
            generated = self._subproblem_exporter(
                {
                    mode: cast(
                        JsonObject,
                        payload.data.model_dump(mode="json"),
                    )
                    for mode, payload in self._c1_results.items()
                },
                provenance,
            )
            exports: list[ExportEntry] = []
            for kind, label, media_type, payload in generated:
                suffix = "." + label.rsplit(".", 1)[1]
                manifest = self._artifact_store.publish_bytes(
                    "export",
                    payload,
                    media_type,
                    cast(Literal[".xlsx", ".svg", ".json"], suffix),
                )
                exports.append(
                    ExportEntry(kind=kind, label=label, sha256=manifest.sha256)
                )

            return ExportSubproblemResult(
                **common,
                operation_id=request.operation_id,
                replayed=False,
                project_id=request.project_id,
                subproblem_id=request.subproblem_id,
                exports=tuple(exports),
            )
        finally:
            self._release_write()


__all__ = ["ModelingApplication"]
