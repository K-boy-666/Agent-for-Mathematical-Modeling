"""Immutable contracts for explicitly composed built-in capabilities."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias, cast, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_validator,
)

from modeling_core.contracts.canonical_json import (
    canonical_json_bytes,
    strict_json_loads,
)
from modeling_core.contracts.common import (
    EntityId,
    Hash,
    JsonObject,
    StrictModel,
)
from modeling_core.contracts.tools import (
    CapabilityLimits,
    ResultPayload,
    ValidationReportPayload,
    ValidatorSummary,
)
from modeling_core.ports.clock import Clock

CapabilityKey: TypeAlias = tuple[str, str]
ValidatorKey: TypeAlias = tuple[str, str]

_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_ENTITY_ID = TypeAdapter(EntityId)


def _semver(value: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(value)
    if match is None:
        raise ValueError("version must be a three-part SemVer core")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


class SchemaReference(StrictModel):
    """One versioned in-memory JSON Schema and its declared canonical hash."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        serialize_by_alias=True,
    )

    schema_version: str
    schema_bytes: bytes = Field(alias="schema", repr=False)
    schema_hash: Hash

    def __init__(
        self,
        *,
        schema_version: str,
        schema: JsonObject,
        schema_hash: str,
    ) -> None:
        BaseModel.__init__(
            self,
            schema_version=schema_version,
            schema=schema,
            schema_hash=schema_hash,
        )

    @property
    def schema(self) -> JsonObject:  # type: ignore[override]
        return cast(JsonObject, strict_json_loads(self.schema_bytes))

    @field_validator("schema_bytes", mode="before")
    @classmethod
    def store_immutable_schema(cls, value: object) -> bytes:
        if not isinstance(value, dict):
            raise ValueError("schema must be a JSON object")
        return canonical_json_bytes(cast(JsonObject, value))

    @field_serializer("schema_bytes")
    def serialize_schema(self, value: bytes) -> JsonObject:
        return cast(JsonObject, strict_json_loads(value))

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if not value:
            raise ValueError("schema_version must not be empty")
        return value


class SupportedCapabilityRange(StrictModel):
    """Inclusive capability-contract range supported by one validator."""

    capability_id: str
    minimum_contract_version: str
    maximum_contract_version: str

    @field_validator("capability_id")
    @classmethod
    def validate_capability_id(cls, value: str) -> str:
        if not value:
            raise ValueError("capability_id must not be empty")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> SupportedCapabilityRange:
        if _semver(self.minimum_contract_version) > _semver(
            self.maximum_contract_version
        ):
            raise ValueError("minimum contract version exceeds maximum")
        return self

    def includes(self, contract_version: str) -> bool:
        requested = _semver(contract_version)
        return (
            _semver(self.minimum_contract_version)
            <= requested
            <= _semver(self.maximum_contract_version)
        )


class CapabilityDescriptor(StrictModel):
    """Complete immutable Built-in Capability registration descriptor."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        serialize_by_alias=True,
    )

    kind: Literal["built_in"]
    capability_api_version: str
    capability_id: str
    contract_version: str
    implementation_id: str
    implementation_version: str
    title: str
    summary: str
    category: str
    tags: tuple[str, ...]
    determinism: str
    randomness: str
    input_schema: SchemaReference
    canonical_input_schema: SchemaReference
    success_schema: SchemaReference
    failure_schema: SchemaReference
    default_limits: CapabilityLimits
    maximum_limits: CapabilityLimits
    artifact_roles: tuple[str, ...]
    validator_summary_bytes: tuple[bytes, ...] = Field(alias="validators", repr=False)
    context_ref: str

    @property
    def validators(self) -> tuple[ValidatorSummary, ...]:
        return tuple(
            ValidatorSummary.model_validate_json(item)
            for item in self.validator_summary_bytes
        )

    @field_validator("validator_summary_bytes", mode="before")
    @classmethod
    def store_immutable_validator_summaries(
        cls, value: object
    ) -> tuple[bytes, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("validators must be an array")
        result: list[bytes] = []
        for item in value:
            if isinstance(item, ValidatorSummary):
                document = item.model_dump(mode="json")
            elif isinstance(item, dict):
                document = ValidatorSummary.model_validate(item).model_dump(mode="json")
            else:
                raise ValueError("invalid validator summary")
            result.append(canonical_json_bytes(cast(JsonObject, document)))
        return tuple(result)

    @field_serializer("validator_summary_bytes")
    def serialize_validator_summaries(
        self, value: tuple[bytes, ...]
    ) -> list[JsonObject]:
        return [cast(JsonObject, strict_json_loads(item)) for item in value]

    @field_validator(
        "capability_api_version",
        "capability_id",
        "contract_version",
        "implementation_id",
        "implementation_version",
        "title",
        "summary",
        "category",
        "determinism",
        "randomness",
        "context_ref",
    )
    @classmethod
    def validate_nonempty_text(cls, value: str) -> str:
        if not value:
            raise ValueError("descriptor text fields must not be empty")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not tag for tag in value):
            raise ValueError("tags must not contain empty values")
        if value != tuple(sorted(set(value))):
            raise ValueError("tags must be unique and sorted")
        return value

    @field_validator("artifact_roles")
    @classmethod
    def validate_m1a_artifact_roles(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if value:
            raise ValueError("M1a Built-in Capabilities have no artifact roles")
        return value

    @model_validator(mode="after")
    def validate_limits(self) -> CapabilityDescriptor:
        for name in ("timeout_ms", "max_iterations", "max_evaluations"):
            if getattr(self.default_limits, name) > getattr(
                self.maximum_limits, name
            ):
                raise ValueError(f"default {name} exceeds maximum")
        return self


class ValidatorDescriptor(StrictModel):
    """Complete immutable registration descriptor for an independent validator."""

    kind: Literal["built_in"]
    validator_id: str
    supported_capabilities: tuple[SupportedCapabilityRange, ...]
    implementation_id: str
    implementation_version: str
    policy_version: str
    policy_schema: SchemaReference
    report_schema: SchemaReference
    summary: str

    @field_validator(
        "validator_id",
        "implementation_id",
        "implementation_version",
        "policy_version",
        "summary",
    )
    @classmethod
    def validate_nonempty_text(cls, value: str) -> str:
        if not value:
            raise ValueError("validator descriptor fields must not be empty")
        return value

    @field_validator("supported_capabilities")
    @classmethod
    def validate_supported_capabilities(
        cls, value: tuple[SupportedCapabilityRange, ...]
    ) -> tuple[SupportedCapabilityRange, ...]:
        if not value:
            raise ValueError("a validator must support at least one capability range")
        ordered = tuple(
            sorted(
                value,
                key=lambda item: (
                    item.capability_id,
                    _semver(item.minimum_contract_version),
                    _semver(item.maximum_contract_version),
                ),
            )
        )
        identities = {
            (
                item.capability_id,
                item.minimum_contract_version,
                item.maximum_contract_version,
            )
            for item in value
        }
        if len(identities) != len(value) or value != ordered:
            raise ValueError("supported capability ranges must be unique and sorted")
        return value


class CanonicalInputRecord(StrictModel):
    """Frozen canonical input snapshot handed to a Built-in Capability."""

    canonical_input_schema_version: str
    canonical_payload: JsonObject
    canonical_payload_hash: Hash
    model_snapshot_hash: Hash
    data_snapshot_references: tuple[JsonObject, ...] = ()
    data_snapshot_set_hash: Hash


class ExecutionOutcome(StrictModel):
    """A mathematical success or expected numerical failure."""

    result_kind: Literal["success", "numerical_failure"]
    result_payload: ResultPayload

    @model_validator(mode="after")
    def validate_matching_kind(self) -> ExecutionOutcome:
        if self.result_payload.result_kind != self.result_kind:
            raise ValueError("execution outcome kind must match its result payload")
        return self

    @classmethod
    def success(cls, payload: ResultPayload) -> ExecutionOutcome:
        return cls(result_kind="success", result_payload=payload)

    @classmethod
    def numerical_failure(cls, payload: ResultPayload) -> ExecutionOutcome:
        return cls(result_kind="numerical_failure", result_payload=payload)


class ResultSnapshotView(StrictModel):
    """Verified committed result view supplied to a validator."""

    result_snapshot_id: EntityId
    capability_id: str
    contract_version: str
    result_schema_version: str
    result_hash: Hash
    result_payload: ResultPayload


ValidationReport: TypeAlias = ValidationReportPayload


@runtime_checkable
class CancellationSignal(Protocol):
    def is_cancelled(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """The entire M1a authority surface available during execution."""

    attempt_id: str
    randomness: str
    seed: int | None
    deadline: float
    clock: Clock
    cancellation: CancellationSignal

    def __post_init__(self) -> None:
        _ENTITY_ID.validate_python(self.attempt_id, strict=True)
        if not self.randomness:
            raise ValueError("randomness must not be empty")
        if isinstance(self.seed, bool) or (
            self.seed is not None and not isinstance(self.seed, int)
        ):
            raise ValueError("seed must be an integer or None")
        if self.randomness == "not_used" and self.seed is not None:
            raise ValueError("randomness=not_used requires seed is None")
        if not isinstance(self.deadline, float) or not math.isfinite(self.deadline):
            raise ValueError("deadline must be a finite monotonic float")


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """The entire M1a authority surface available during validation."""

    deadline: float
    clock: Clock
    cancellation: CancellationSignal

    def __post_init__(self) -> None:
        if not isinstance(self.deadline, float) or not math.isfinite(self.deadline):
            raise ValueError("deadline must be a finite monotonic float")


@runtime_checkable
class BuiltInCapability(Protocol):
    @property
    def descriptor(self) -> CapabilityDescriptor: ...

    def normalize_and_validate(
        self, raw_payload: JsonObject
    ) -> CanonicalInputRecord: ...

    def execute(
        self, canonical_input: CanonicalInputRecord, context: ExecutionContext
    ) -> ExecutionOutcome: ...


@runtime_checkable
class CapabilityValidator(Protocol):
    @property
    def descriptor(self) -> ValidatorDescriptor: ...

    def validate(
        self,
        canonical_input: CanonicalInputRecord,
        result_snapshot: ResultSnapshotView,
        policy: JsonObject,
        context: ValidationContext,
    ) -> ValidationReport: ...


__all__ = [
    "BuiltInCapability",
    "CancellationSignal",
    "CapabilityDescriptor",
    "CapabilityKey",
    "CapabilityValidator",
    "CanonicalInputRecord",
    "ExecutionContext",
    "ExecutionOutcome",
    "ResultSnapshotView",
    "SchemaReference",
    "SupportedCapabilityRange",
    "ValidationContext",
    "ValidationReport",
    "ValidatorDescriptor",
    "ValidatorKey",
]
