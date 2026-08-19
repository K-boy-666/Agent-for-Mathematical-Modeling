"""Content-addressed artifact store port for immutable JSON artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol, cast, runtime_checkable

from pydantic import Field, TypeAdapter

from modeling_core.contracts.canonical_json import canonical_json_bytes
from modeling_core.contracts.common import EntityId, Hash, JsonObject, Timestamp

ArtifactRole = Literal[
    "result", "validation_report", "input_snapshot", "environment_snapshot"
]

_MAX_ARTIFACTS_PER_ATTEMPT = 16
_MAX_CUMULATIVE_ARTIFACT_BYTES = 64 * 1024 * 1024

_ARTIFACT_ROLE: TypeAdapter[ArtifactRole] = TypeAdapter(ArtifactRole)
_ENTITY_ID: TypeAdapter[EntityId] = TypeAdapter(EntityId)
_HASH = TypeAdapter(Hash)
_TIMESTAMP = TypeAdapter(Timestamp)
_STR = TypeAdapter(str)
_INT_GE0: TypeAdapter[int] = TypeAdapter(Annotated[int, Field(ge=0)])
_BOOL = TypeAdapter(bool)
_JSON_OBJECT = TypeAdapter(JsonObject)
_STR_TUPLE = TypeAdapter(tuple[str, ...])


def _validate(value: object, annotation: Any) -> Any:
    return cast(Any, TypeAdapter(annotation).validate_python(value, strict=True))


@dataclass(frozen=True)
class ArtifactManifest:
    artifact_id: str
    role: str
    media_type: str
    byte_size: int
    sha256: str
    schema_id: str
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _HASH.validate_python(self.artifact_id, strict=True)
        )
        object.__setattr__(
            self, "role", _ARTIFACT_ROLE.validate_python(self.role, strict=True)
        )
        object.__setattr__(
            self, "media_type", _STR.validate_python(self.media_type, strict=True)
        )
        object.__setattr__(
            self, "byte_size", _INT_GE0.validate_python(self.byte_size, strict=True)
        )
        object.__setattr__(
            self, "sha256", _HASH.validate_python(self.sha256, strict=True)
        )
        object.__setattr__(
            self, "schema_id", _STR.validate_python(self.schema_id, strict=True)
        )
        object.__setattr__(
            self, "created_at", _TIMESTAMP.validate_python(self.created_at, strict=True)
        )


@dataclass(frozen=True)
class ArtifactInspectionReport:
    referenced_artifact_ids: tuple[str, ...]
    present_artifacts: tuple[ArtifactManifest, ...]
    missing_artifacts: tuple[str, ...]
    orphan_artifacts: tuple[ArtifactManifest, ...]
    staging_files: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "referenced_artifact_ids",
            _STR_TUPLE.validate_python(self.referenced_artifact_ids, strict=True),
        )
        object.__setattr__(
            self,
            "present_artifacts",
            _validate(self.present_artifacts, tuple[ArtifactManifest, ...]),
        )
        object.__setattr__(
            self,
            "missing_artifacts",
            _STR_TUPLE.validate_python(self.missing_artifacts, strict=True),
        )
        object.__setattr__(
            self,
            "orphan_artifacts",
            _validate(self.orphan_artifacts, tuple[ArtifactManifest, ...]),
        )
        object.__setattr__(
            self,
            "staging_files",
            _STR_TUPLE.validate_python(self.staging_files, strict=True),
        )


class ArtifactStoreError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool = False,
        details: dict[str, object] | None = None,
    ) -> None:
        validated_code = _STR.validate_python(code, strict=True)
        if not validated_code:
            raise ValueError("error code must not be empty")
        validated_message = _STR.validate_python(message, strict=True)
        if not validated_message:
            raise ValueError("error message must not be empty")
        validated_retryable = _BOOL.validate_python(retryable, strict=True)
        if details is not None:
            _JSON_OBJECT.validate_python(details, strict=True)
        super().__init__(validated_message)
        self._code = validated_code
        self._message = validated_message
        self._retryable = validated_retryable
        self._details = details if details is not None else {}

    @property
    def code(self) -> str:
        return self._code

    @property
    def message(self) -> str:
        return self._message

    @property
    def retryable(self) -> bool:
        return self._retryable

    @property
    def details(self) -> dict[str, object]:
        return self._details


class ArtifactStore(Protocol):
    def publish_json(
        self,
        role: ArtifactRole,
        payload: dict[str, object],
        schema_id: str,
    ) -> ArtifactManifest: ...

    def read_verified(
        self,
        artifact_id: str,
        expected_size: int,
        expected_sha256: str,
    ) -> bytes: ...

    def inspect(
        self,
        referenced_artifact_ids: frozenset[str],
    ) -> ArtifactInspectionReport: ...


@runtime_checkable
class ArtifactSink(Protocol):
    """Write-only, attempt-scoped JSON publication surface for capabilities."""

    def publish_json(
        self,
        role: ArtifactRole,
        payload: JsonObject,
        schema_id: str,
    ) -> ArtifactManifest: ...


class AttemptArtifactSink:
    """The sole write authority granted to one Attempt execution.

    Enforces the per-Attempt artifact budget (at most sixteen artifacts and
    sixty-four cumulative MiB) before staging anything. It never exposes
    paths, reads, deletes or database methods.
    """

    def __init__(self, store: ArtifactStore, attempt_id: str) -> None:
        self._store = store
        self._attempt_id = _ENTITY_ID.validate_python(attempt_id, strict=True)
        self._published_count = 0
        self._published_bytes = 0

    @property
    def attempt_id(self) -> str:
        return self._attempt_id

    @property
    def published_count(self) -> int:
        return self._published_count

    @property
    def published_bytes(self) -> int:
        return self._published_bytes

    def publish_json(
        self,
        role: ArtifactRole,
        payload: JsonObject,
        schema_id: str,
    ) -> ArtifactManifest:
        canonical = canonical_json_bytes(payload)
        observed_count = self._published_count + 1
        if observed_count > _MAX_ARTIFACTS_PER_ATTEMPT:
            raise ArtifactStoreError(
                code="RESOURCE_LIMIT_EXCEEDED",
                message=("attempt artifact count exceeds the per-attempt budget"),
                details={
                    "resource": "attempt_artifacts",
                    "limit": _MAX_ARTIFACTS_PER_ATTEMPT,
                    "observed": observed_count,
                },
            )
        observed_bytes = self._published_bytes + len(canonical)
        if observed_bytes > _MAX_CUMULATIVE_ARTIFACT_BYTES:
            raise ArtifactStoreError(
                code="RESOURCE_LIMIT_EXCEEDED",
                message="attempt artifact bytes exceed the per-attempt budget",
                details={
                    "resource": "attempt_artifact_bytes",
                    "limit": _MAX_CUMULATIVE_ARTIFACT_BYTES,
                    "observed": observed_bytes,
                },
            )
        manifest = self._store.publish_json(
            role, cast(dict[str, object], payload), schema_id
        )
        self._published_count = observed_count
        self._published_bytes = observed_bytes
        return manifest


__all__ = [
    "ArtifactInspectionReport",
    "ArtifactManifest",
    "ArtifactRole",
    "ArtifactSink",
    "ArtifactStore",
    "ArtifactStoreError",
    "AttemptArtifactSink",
]
