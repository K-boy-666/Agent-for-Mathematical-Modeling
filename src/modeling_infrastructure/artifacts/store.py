"""Content-addressed artifact store backed by the local filesystem."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from modeling_core.contracts.canonical_json import (
    canonical_json_bytes,
    strict_json_loads,
)
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.ports.artifact_store import (
    ArtifactInspectionReport,
    ArtifactManifest,
    ArtifactRole,
    ArtifactStoreError,
)
from modeling_infrastructure.project_paths import ProjectPaths, is_reparse_point

_MAX_PAYLOAD_BYTES = 64 * 1024 * 1024  # 64 MiB
_VALID_ROLES: frozenset[str] = frozenset(
    {
        "result",
        "validation_report",
        "input_snapshot",
        "environment_snapshot",
    }
)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class ContentAddressedArtifactStore:
    """Stores immutable JSON artifacts under
    .modeling/artifacts/sha256/{first_two_hex}/{full_hex}.json.
    """

    def __init__(self, paths: ProjectPaths, schema_version: str = "0.1.0") -> None:
        self._paths = paths
        self._schema_catalog = SchemaCatalog.load_packaged(schema_version)

    def _resolve_validator(self, schema_id: str) -> Draft202012Validator:
        """Resolve a common-schema $id or a 'tool.kind' identifier."""
        common = self._schema_catalog.common_schemas.get(schema_id)
        if common is not None:
            return Draft202012Validator(common)
        schema_id_parts = schema_id.rsplit(".", 1)
        if len(schema_id_parts) != 2:
            raise ArtifactStoreError(
                code="INVALID_SCHEMA_ID",
                message=f"schema_id must be a common $id or 'tool.kind', "
                f"got: {schema_id!r}",
            )
        tool, kind = schema_id_parts
        return self._schema_catalog.validator(tool, kind)

    # ------------------------------------------------------------------
    # publish_json
    # ------------------------------------------------------------------

    def publish_json(
        self,
        role: ArtifactRole,
        payload: dict[str, object],
        schema_id: str,
    ) -> ArtifactManifest:
        # 1. Enforce closed role set
        if role not in _VALID_ROLES:
            raise ArtifactStoreError(
                code="INVALID_ROLE",
                message=f"Unknown artifact role: {role!r}",
            )

        # 2. Reject any single payload above 64 MiB
        #    (size measured on canonical bytes computed in step 3)
        # 3. Compute canonical JSON bytes
        canonical_bytes = canonical_json_bytes(payload)
        if len(canonical_bytes) > _MAX_PAYLOAD_BYTES:
            raise ArtifactStoreError(
                code="PAYLOAD_TOO_LARGE",
                message=(
                    f"Payload canonical size {len(canonical_bytes)} bytes "
                    f"exceeds {_MAX_PAYLOAD_BYTES} bytes limit"
                ),
            )

        # 4. Write canonical bytes under staging with unique filename
        staging_dir = self._paths.staging
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging_path = staging_dir / f"{uuid.uuid4()}.json"
        with open(staging_path, "wb") as fh:
            fh.write(canonical_bytes)
            # 5. Flush and os.fsync before closing
            fh.flush()
            os.fsync(fh.fileno())

        # 6. Calculate SHA-256 of the canonical bytes
        full_hex = hashlib.sha256(canonical_bytes).hexdigest()
        artifact_id = f"sha256:{full_hex}"

        # 7. Validate decoded content with SchemaCatalog
        try:
            _decoded = strict_json_loads(canonical_bytes)
            _validator = self._resolve_validator(schema_id)
            _validator.validate(_decoded)
        except ArtifactStoreError:
            _cleanup_staging(staging_path)
            raise
        except Exception as exc:
            _cleanup_staging(staging_path)
            raise ArtifactStoreError(
                code="SCHEMA_VALIDATION_FAILED",
                message=f"Schema validation failed for {schema_id}: {exc}",
            ) from exc

        # 8. Derive the destination
        first_two = full_hex[:2]
        destination = self._paths.artifacts / "sha256" / first_two / f"{full_hex}.json"

        # 9. Create first-two-hex directory if it doesn't exist
        destination.parent.mkdir(parents=True, exist_ok=True)

        # 10. If destination exists, verify and reuse
        if destination.exists():
            if is_reparse_point(destination):
                _cleanup_staging(staging_path)
                raise ArtifactStoreError(
                    code="REPARSE_POINT",
                    message=f"Artifact path is a reparse point: {destination}",
                )
            _verify_existing_or_raise(destination, canonical_bytes, full_hex)
            # 14. Remove staging file after verified reuse
            _cleanup_staging(staging_path)
            return self._make_manifest(artifact_id, role, canonical_bytes, schema_id)

        # 11. Atomic rename staging → destination (NOT os.replace)
        try:
            os.rename(staging_path, destination)
        except FileExistsError:
            # 12. Platform collision → verify existing target
            if is_reparse_point(destination):
                _cleanup_staging(staging_path)
                raise ArtifactStoreError(
                    code="REPARSE_POINT",
                    message=f"Artifact path is a reparse point: {destination}",
                )
            _verify_existing_or_raise(destination, canonical_bytes, full_hex)
            # 14. Remove staging file after verified reuse
            _cleanup_staging(staging_path)
            return self._make_manifest(artifact_id, role, canonical_bytes, schema_id)
        except OSError as exc:
            # 13. Any other rename failure
            _cleanup_staging(staging_path)
            raise ArtifactStoreError(
                code="RENAME_FAILED",
                message=f"Failed to rename staging file to artifact: {exc}",
            ) from exc

        return self._make_manifest(artifact_id, role, canonical_bytes, schema_id)

    # ------------------------------------------------------------------
    # read_verified
    # ------------------------------------------------------------------

    def read_verified(
        self,
        artifact_id: str,
        expected_size: int,
        expected_sha256: str,
    ) -> bytes:
        # 1. Extract full_hex from artifact_id (strip "sha256:" prefix)
        if not artifact_id.startswith("sha256:"):
            raise ArtifactStoreError(
                code="INVALID_ARTIFACT_ID",
                message=f"Artifact ID must start with 'sha256:': {artifact_id!r}",
            )
        full_hex = artifact_id[len("sha256:") :]

        # 2. Derive the path
        first_two = full_hex[:2]
        file_path = self._paths.artifacts / "sha256" / first_two / f"{full_hex}.json"

        # 3. Verify file exists and is a regular file (not symlink/reparse)
        if not file_path.exists():
            raise ArtifactStoreError(
                code="ARTIFACT_NOT_FOUND",
                message=f"Artifact not found on disk: {artifact_id}",
            )
        if is_reparse_point(file_path):
            raise ArtifactStoreError(
                code="REPARSE_POINT",
                message=f"Artifact path is a reparse point: {file_path}",
            )
        if not file_path.is_file():
            raise ArtifactStoreError(
                code="NOT_A_FILE",
                message=f"Artifact path is not a regular file: {file_path}",
            )

        # 4. Read the file bytes
        data = file_path.read_bytes()

        # 5. Verify byte size matches expected_size
        if len(data) != expected_size:
            raise ArtifactStoreError(
                code="SIZE_MISMATCH",
                message=(
                    f"Expected {expected_size} bytes but read {len(data)} "
                    f"for {artifact_id}"
                ),
            )

        # 6. Verify SHA-256 matches expected_sha256
        actual_hex = hashlib.sha256(data).hexdigest()
        expected_hex = expected_sha256.removeprefix("sha256:")
        if actual_hex != expected_hex:
            raise ArtifactStoreError(
                code="HASH_MISMATCH",
                message=f"SHA-256 mismatch for {artifact_id}",
            )

        # 7. Return the bytes
        return data

    # ------------------------------------------------------------------
    # inspect
    # ------------------------------------------------------------------

    def inspect(
        self,
        referenced_artifact_ids: frozenset[str],
    ) -> ArtifactInspectionReport:
        sha256_dir = self._paths.artifacts / "sha256"
        referenced = set(referenced_artifact_ids)

        present: list[ArtifactManifest] = []
        missing: list[str] = []
        orphans: list[ArtifactManifest] = []
        staging_files: list[str] = []
        found_ids: set[str] = set()

        # 1–2. Scan artifacts directory and list all .json files
        if sha256_dir.exists():
            for json_file in sha256_dir.rglob("*.json"):
                if is_reparse_point(json_file):
                    continue
                if not json_file.is_file():
                    continue
                full_hex = json_file.stem
                if len(full_hex) != 64 or not all(
                    c in "0123456789abcdef" for c in full_hex
                ):
                    continue
                artifact_id = f"sha256:{full_hex}"
                found_ids.add(artifact_id)

                # 3. Classify as present or orphan
                if artifact_id in referenced:
                    try:
                        data = json_file.read_bytes()
                        file_hex = hashlib.sha256(data).hexdigest()
                        if file_hex == full_hex:
                            present.append(
                                ArtifactManifest(
                                    artifact_id=artifact_id,
                                    role="result",
                                    media_type="application/json",
                                    byte_size=len(data),
                                    sha256=artifact_id,
                                    schema_id="unknown",
                                    created_at="1970-01-01T00:00:00.000Z",
                                )
                            )
                        else:
                            missing.append(artifact_id)
                    except Exception:
                        missing.append(artifact_id)
                else:
                    # Orphan: not in referenced set
                    try:
                        data = json_file.read_bytes()
                        file_hex = hashlib.sha256(data).hexdigest()
                        if file_hex == full_hex:
                            orphans.append(
                                ArtifactManifest(
                                    artifact_id=artifact_id,
                                    role="result",
                                    media_type="application/json",
                                    byte_size=len(data),
                                    sha256=artifact_id,
                                    schema_id="unknown",
                                    created_at="1970-01-01T00:00:00.000Z",
                                )
                            )
                    except Exception:
                        pass

        # 4. Report missing artifacts (referenced but not found on disk)
        for ref_id in sorted(referenced):
            if ref_id not in found_ids:
                missing.append(ref_id)

        # 5. Check staging directory for stale files
        staging_dir = self._paths.staging
        if staging_dir.exists():
            try:
                for entry in staging_dir.iterdir():
                    if entry.is_file() and not is_reparse_point(entry):
                        staging_files.append(entry.name)
            except OSError:
                pass

        return ArtifactInspectionReport(
            referenced_artifact_ids=tuple(sorted(referenced)),
            present_artifacts=tuple(present),
            missing_artifacts=tuple(sorted(missing)),
            orphan_artifacts=tuple(orphans),
            staging_files=tuple(sorted(staging_files)),
        )

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _make_manifest(
        self,
        artifact_id: str,
        role: str,
        canonical_bytes: bytes,
        schema_id: str,
    ) -> ArtifactManifest:
        return ArtifactManifest(
            artifact_id=artifact_id,
            role=role,
            media_type="application/json",
            byte_size=len(canonical_bytes),
            sha256=artifact_id,
            schema_id=schema_id,
            created_at=_now_utc(),
        )


# ------------------------------------------------------------------
# module-level helpers
# ------------------------------------------------------------------


def _cleanup_staging(path: Path) -> None:
    """Best-effort removal of a staging file."""
    try:
        os.unlink(path)
    except OSError:
        pass


def _verify_existing_or_raise(
    destination: Path,
    canonical_bytes: bytes,
    full_hex: str,
) -> None:
    """Verify an existing artifact file matches expected content."""
    existing_bytes = destination.read_bytes()
    if len(existing_bytes) != len(canonical_bytes):
        raise ArtifactStoreError(
            code="INTEGRITY_FAILURE",
            message="Existing artifact size does not match canonical bytes",
        )
    existing_hex = hashlib.sha256(existing_bytes).hexdigest()
    if existing_hex != full_hex:
        raise ArtifactStoreError(
            code="INTEGRITY_FAILURE",
            message="Existing artifact SHA-256 does not match canonical bytes",
        )
