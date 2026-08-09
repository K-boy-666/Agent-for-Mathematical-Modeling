from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from modeling_core.contracts.common import EntityId, Hash, StrictModel

ErrorCode: TypeAlias = Literal[
    "INVALID_REQUEST",
    "NOT_FOUND",
    "UNSUPPORTED_VERSION",
    "CONFLICT",
    "PRECONDITION_FAILED",
    "SECURITY_VIOLATION",
    "RESOURCE_LIMIT_EXCEEDED",
    "INTEGRITY_FAILURE",
    "INTERNAL_ERROR",
]

ALL_ERROR_CODES = frozenset(
    {
        "INVALID_REQUEST",
        "NOT_FOUND",
        "UNSUPPORTED_VERSION",
        "CONFLICT",
        "PRECONDITION_FAILED",
        "SECURITY_VIOLATION",
        "RESOURCE_LIMIT_EXCEEDED",
        "INTEGRITY_FAILURE",
        "INTERNAL_ERROR",
    }
)
TOOL_ERROR_CODES: dict[str, frozenset[str]] = {
    "health_check": frozenset(
        {"INVALID_REQUEST", "RESOURCE_LIMIT_EXCEEDED", "INTERNAL_ERROR"}
    ),
    "create_project": ALL_ERROR_CODES - frozenset({"NOT_FOUND"}),
    "get_project_status": ALL_ERROR_CODES
    - frozenset({"CONFLICT", "SECURITY_VIOLATION"}),
    "list_capabilities": ALL_ERROR_CODES
    - frozenset({"CONFLICT", "SECURITY_VIOLATION", "INTEGRITY_FAILURE"}),
    "run_experiment": ALL_ERROR_CODES,
    "validate_experiment": ALL_ERROR_CODES,
}


class InvalidRequestDetails(StrictModel):
    field_path: str
    reason: Literal[
        "missing_required",
        "unknown_field",
        "invalid_type",
        "invalid_format",
        "out_of_range",
        "invalid_combination",
        "expression_parse_error",
        "capability_payload_violation",
        "invalid_cursor",
    ]


class NotFoundDetails(StrictModel):
    resource_type: str
    resource_id: str


class UnsupportedVersionDetails(StrictModel):
    subject: str
    requested_version: str
    supported_versions: tuple[str, ...]


class ConflictDetails(StrictModel):
    conflict_type: Literal[
        "idempotency_mismatch",
        "operation_in_progress",
        "project_busy",
        "project_metadata_mismatch",
        "duplicate_registration",
    ]
    existing_resource_id: str | None = None
    retry_after_ms: Annotated[int | None, Field(ge=0)] = None


class PreconditionFailedDetails(StrictModel):
    condition: Literal[
        "project_not_ready",
        "project_degraded",
        "attempt_not_succeeded",
        "missing_success_result",
        "validator_incompatible",
    ]
    current_state: str


class SecurityViolationDetails(StrictModel):
    rule: Literal[
        "math_expr_forbidden_syntax",
        "path_outside_project",
        "unsafe_reparse_point",
        "stdout_protocol_violation",
    ]


class ResourceLimitExceededDetails(StrictModel):
    resource: Literal[
        "mcp_request_bytes",
        "inline_response_bytes",
        "expression_bytes",
        "ast_nodes",
        "ast_depth",
        "numeric_literal_chars",
        "function_evaluations",
        "warnings",
    ]
    limit: Annotated[int, Field(ge=0)]
    observed: Annotated[int | None, Field(ge=0)] = None


class IntegrityFailureDetails(StrictModel):
    subject: Literal[
        "project_metadata",
        "database_relation",
        "result_hash",
        "validation_report_hash",
        "input_snapshot",
    ]
    expected_hash: Hash | None = None
    observed_hash: Hash | None = None


class InternalErrorDetails(StrictModel):
    event_id: EntityId


ErrorDetails: TypeAlias = (
    InvalidRequestDetails
    | NotFoundDetails
    | UnsupportedVersionDetails
    | ConflictDetails
    | PreconditionFailedDetails
    | SecurityViolationDetails
    | ResourceLimitExceededDetails
    | IntegrityFailureDetails
    | InternalErrorDetails
)

_DETAIL_BY_CODE: dict[str, type[StrictModel]] = {
    "INVALID_REQUEST": InvalidRequestDetails,
    "NOT_FOUND": NotFoundDetails,
    "UNSUPPORTED_VERSION": UnsupportedVersionDetails,
    "CONFLICT": ConflictDetails,
    "PRECONDITION_FAILED": PreconditionFailedDetails,
    "SECURITY_VIOLATION": SecurityViolationDetails,
    "RESOURCE_LIMIT_EXCEEDED": ResourceLimitExceededDetails,
    "INTEGRITY_FAILURE": IntegrityFailureDetails,
    "INTERNAL_ERROR": InternalErrorDetails,
}


class ErrorResponse(StrictModel):
    error_schema_version: Literal["modeling-error/0.1.0"]
    code: ErrorCode
    message: Annotated[str, Field(min_length=1, max_length=1024)]
    retryable: bool
    correlation_id: EntityId
    details: ErrorDetails

    @model_validator(mode="after")
    def validate_discriminated_details(self) -> ErrorResponse:
        if not isinstance(self.details, _DETAIL_BY_CODE[self.code]):
            raise ValueError(f"details do not match error code {self.code}")
        if self.retryable and not (
            self.code == "CONFLICT"
            and isinstance(self.details, ConflictDetails)
            and self.details.conflict_type in {"operation_in_progress", "project_busy"}
        ):
            raise ValueError("only transient conflicts can be retryable")
        return self


class ModelingError(Exception):
    def __init__(self, response: ErrorResponse) -> None:
        super().__init__(response.message)
        self.response = response
