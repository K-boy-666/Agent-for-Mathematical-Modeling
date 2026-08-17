"""Contract tests for the content-addressed ArtifactStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from modeling_core.contracts.canonical_json import canonical_json_bytes, sha256_json
from modeling_core.contracts.versions import VersionSet
from modeling_core.ports.artifact_store import (
    ArtifactInspectionReport,
    ArtifactStoreError,
)
from modeling_infrastructure.artifacts.store import ContentAddressedArtifactStore
from modeling_infrastructure.project_paths import ProjectPaths
from modeling_infrastructure.storage import bootstrap_storage

# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

VALID_SCHEMA_ID = "health_check.request"
VALID_PAYLOAD: dict[str, object] = {}


def _make_store(tmp_path: Path) -> ContentAddressedArtifactStore:
    bootstrap_storage(tmp_path, VersionSet.m1b())
    paths = ProjectPaths.bind(tmp_path)
    return ContentAddressedArtifactStore(paths)


def _artifact_path(project_root: Path, full_hex: str) -> Path:
    return (
        project_root
        / ".modeling"
        / "artifacts"
        / "sha256"
        / full_hex[:2]
        / f"{full_hex}.json"
    )


# ---------------------------------------------------------------------------
# 1. TestPublishAndRead
# ---------------------------------------------------------------------------


class TestPublishAndRead:
    def test_publish_and_read_verified_roundtrip(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD
        expected = canonical_json_bytes(payload)

        manifest = store.publish_json("result", payload, VALID_SCHEMA_ID)

        result = store.read_verified(
            manifest.artifact_id,
            expected_size=manifest.byte_size,
            expected_sha256=manifest.sha256,
        )
        assert result == expected


# ---------------------------------------------------------------------------
# 2. TestArtifactIdentity
# ---------------------------------------------------------------------------


class TestArtifactIdentity:
    def test_artifact_id_format(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        expected_sha = sha256_json(VALID_PAYLOAD)

        manifest = store.publish_json("result", VALID_PAYLOAD, VALID_SCHEMA_ID)

        assert manifest.artifact_id == expected_sha
        assert manifest.artifact_id.startswith("sha256:")
        assert len(manifest.artifact_id) == 71  # "sha256:" + 64 hex

    def test_sha256_field_matches_artifact_id(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD

        manifest = store.publish_json("result", payload, VALID_SCHEMA_ID)

        assert manifest.sha256 == manifest.artifact_id


# ---------------------------------------------------------------------------
# 3. TestPathDerivation
# ---------------------------------------------------------------------------


class TestPathDerivation:
    def test_path_uses_sha256_prefix_tree(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD
        full_hex = sha256_json(payload).removeprefix("sha256:")

        _ = store.publish_json("result", payload, VALID_SCHEMA_ID)

        expected_path = _artifact_path(tmp_path, full_hex)
        assert expected_path.exists()
        assert expected_path.is_file()
        assert expected_path.parent.name == full_hex[:2]
        assert expected_path.name == f"{full_hex}.json"


# ---------------------------------------------------------------------------
# 4. TestByteSize
# ---------------------------------------------------------------------------


class TestByteSize:
    def test_byte_size_matches_canonical_form(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD
        expected_bytes = canonical_json_bytes(payload)

        manifest = store.publish_json("result", payload, VALID_SCHEMA_ID)

        assert manifest.byte_size == len(expected_bytes)
        assert manifest.byte_size > 0


# ---------------------------------------------------------------------------
# 5. TestRoleAndMediaType
# ---------------------------------------------------------------------------


class TestRoleAndMediaType:
    def test_role_preserved_and_media_type_is_json(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        manifest = store.publish_json("result", VALID_PAYLOAD, VALID_SCHEMA_ID)

        assert manifest.role == "result"
        assert manifest.media_type == "application/json"

    def test_schema_id_preserved(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        manifest = store.publish_json("result", VALID_PAYLOAD, VALID_SCHEMA_ID)

        assert manifest.schema_id == VALID_SCHEMA_ID


# ---------------------------------------------------------------------------
# 6. TestIdenticalReuse
# ---------------------------------------------------------------------------


class TestIdenticalReuse:
    def test_same_content_returns_same_id_no_duplicate(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD
        full_hex = sha256_json(payload).removeprefix("sha256:")

        m1 = store.publish_json("result", payload, VALID_SCHEMA_ID)
        m2 = store.publish_json("validation_report", payload, VALID_SCHEMA_ID)

        assert m1.artifact_id == m2.artifact_id
        # Only one file should exist for this hash
        prefix_dir = _artifact_path(tmp_path, full_hex).parent
        assert len(list(prefix_dir.iterdir())) == 1

    def test_different_roles_preserved_on_reuse(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD

        m1 = store.publish_json("result", payload, VALID_SCHEMA_ID)
        m2 = store.publish_json("validation_report", payload, VALID_SCHEMA_ID)

        assert m1.artifact_id == m2.artifact_id
        assert m1.role == "result"
        assert m2.role == "validation_report"


# ---------------------------------------------------------------------------
# 7. TestExistingByteMismatch
# ---------------------------------------------------------------------------


class TestExistingByteMismatch:
    def test_different_content_at_existing_path_rejected(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD
        full_hex = sha256_json(payload).removeprefix("sha256:")

        store.publish_json("result", payload, VALID_SCHEMA_ID)

        # Tamper with the file on disk
        artifact_file = _artifact_path(tmp_path, full_hex)
        artifact_file.write_bytes(b'{"corrupted":true}')

        with pytest.raises(ArtifactStoreError) as exc_info:
            store.publish_json("result", payload, VALID_SCHEMA_ID)
        assert exc_info.value.code == "INTEGRITY_FAILURE"


# ---------------------------------------------------------------------------
# 8. TestInvalidSchema
# ---------------------------------------------------------------------------


class TestInvalidSchema:
    def test_payload_failing_schema_validation_rejected(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        # health_check.request has additionalProperties: false
        invalid_payload: dict[str, object] = {"extra": "field"}

        with pytest.raises(ArtifactStoreError) as exc_info:
            store.publish_json("result", invalid_payload, VALID_SCHEMA_ID)
        assert exc_info.value.code == "SCHEMA_VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# 9. TestInvalidRole
# ---------------------------------------------------------------------------


class TestInvalidRole:
    def test_invalid_role_rejected(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        with pytest.raises(ArtifactStoreError) as exc_info:
            store.publish_json("invalid_role", VALID_PAYLOAD, VALID_SCHEMA_ID)  # type: ignore[arg-type]
        assert exc_info.value.code == "INVALID_ROLE"


# ---------------------------------------------------------------------------
# 10. TestPayloadTooLarge
# ---------------------------------------------------------------------------


class TestPayloadTooLarge:
    def test_payload_exceeding_64mib_rejected(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        big = "x" * (64 * 1024 * 1024 + 1)
        payload: dict[str, object] = {"data": big}

        with pytest.raises(ArtifactStoreError) as exc_info:
            store.publish_json("result", payload, VALID_SCHEMA_ID)
        assert exc_info.value.code == "PAYLOAD_TOO_LARGE"


# ---------------------------------------------------------------------------
# 11. TestTamperedRead
# ---------------------------------------------------------------------------


class TestTamperedRead:
    def test_tampered_content_fails_read_verified(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD
        full_hex = sha256_json(payload).removeprefix("sha256:")

        manifest = store.publish_json("result", payload, VALID_SCHEMA_ID)

        # Tamper with same-size but different content
        _artifact_path(tmp_path, full_hex).write_bytes(b"xx")
        with pytest.raises(ArtifactStoreError) as exc_info:
            store.read_verified(
                manifest.artifact_id,
                expected_size=manifest.byte_size,
                expected_sha256=manifest.sha256,
            )
        assert exc_info.value.code == "HASH_MISMATCH"

    def test_wrong_size_fails_read_verified(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD

        manifest = store.publish_json("result", payload, VALID_SCHEMA_ID)

        with pytest.raises(ArtifactStoreError) as exc_info:
            store.read_verified(
                manifest.artifact_id,
                expected_size=manifest.byte_size + 1,
                expected_sha256=manifest.sha256,
            )
        assert exc_info.value.code == "SIZE_MISMATCH"

    def test_deleted_file_fails_read_verified(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD
        full_hex = sha256_json(payload).removeprefix("sha256:")

        manifest = store.publish_json("result", payload, VALID_SCHEMA_ID)
        _artifact_path(tmp_path, full_hex).unlink()

        with pytest.raises(ArtifactStoreError) as exc_info:
            store.read_verified(
                manifest.artifact_id,
                expected_size=manifest.byte_size,
                expected_sha256=manifest.sha256,
            )
        assert exc_info.value.code == "ARTIFACT_NOT_FOUND"


# ---------------------------------------------------------------------------
# 12. TestInspect
# ---------------------------------------------------------------------------


class TestInspect:
    def test_inspect_present_and_missing(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD
        full_hex = sha256_json(payload).removeprefix("sha256:")
        artifact_id = f"sha256:{full_hex}"

        store.publish_json("result", payload, VALID_SCHEMA_ID)

        report = store.inspect(frozenset({artifact_id, "sha256:" + "f" * 64}))

        assert isinstance(report, ArtifactInspectionReport)
        assert len(report.present_artifacts) == 1
        assert report.present_artifacts[0].artifact_id == artifact_id
        assert report.missing_artifacts == ("sha256:" + "f" * 64,)

    def test_inspect_reports_orphans(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD
        full_hex = sha256_json(payload).removeprefix("sha256:")

        store.publish_json("result", payload, VALID_SCHEMA_ID)

        # Create an orphan file whose filename matches the SHA-256 of its content
        orphan_payload = {"orphan": True}
        orphan_bytes = canonical_json_bytes(orphan_payload)
        orphan_hex = sha256_json(orphan_payload).removeprefix("sha256:")
        orphan_path = _artifact_path(tmp_path, orphan_hex)
        orphan_path.parent.mkdir(parents=True, exist_ok=True)
        orphan_path.write_bytes(orphan_bytes)

        report = store.inspect(frozenset({f"sha256:{full_hex}"}))

        assert len(report.orphan_artifacts) >= 1
        orphan_ids = [o.artifact_id for o in report.orphan_artifacts]
        assert f"sha256:{orphan_hex}" in orphan_ids

    def test_orphan_not_deleted_by_inspect(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        payload = VALID_PAYLOAD
        full_hex = sha256_json(payload).removeprefix("sha256:")

        store.publish_json("result", payload, VALID_SCHEMA_ID)

        # Create an orphan file whose filename matches the SHA-256 of its content
        orphan_payload = {"orphan": True}
        orphan_bytes = canonical_json_bytes(orphan_payload)
        orphan_hex = sha256_json(orphan_payload).removeprefix("sha256:")
        orphan_path = _artifact_path(tmp_path, orphan_hex)
        orphan_path.parent.mkdir(parents=True, exist_ok=True)
        orphan_path.write_bytes(orphan_bytes)

        store.inspect(frozenset({f"sha256:{full_hex}"}))

        assert orphan_path.exists()


# ---------------------------------------------------------------------------
# 13. TestErrorContracts
# ---------------------------------------------------------------------------


class TestErrorContracts:
    def test_error_structure(self) -> None:
        error = ArtifactStoreError(
            code="INTEGRITY_FAILURE",
            message="hash mismatch",
            retryable=False,
            details={"artifact_id": "sha256:" + "a" * 64},
        )
        assert isinstance(error, Exception)
        assert error.code == "INTEGRITY_FAILURE"
        assert error.message == "hash mismatch"
        assert error.retryable is False
        assert error.details == {"artifact_id": "sha256:" + "a" * 64}

    def test_error_code_and_message_required(self) -> None:
        with pytest.raises((TypeError, ValueError)):
            ArtifactStoreError(message="no code")  # type: ignore[call-arg]
        with pytest.raises((TypeError, ValueError)):
            ArtifactStoreError(code="INTEGRITY_FAILURE")  # type: ignore[call-arg]

    def test_error_details_defaults_to_empty(self) -> None:
        error = ArtifactStoreError(code="INTEGRITY_FAILURE", message="hash mismatch")
        assert error.details == {}

    def test_error_retryable_defaults_to_false(self) -> None:
        error = ArtifactStoreError(code="INTEGRITY_FAILURE", message="hash mismatch")
        assert error.retryable is False
