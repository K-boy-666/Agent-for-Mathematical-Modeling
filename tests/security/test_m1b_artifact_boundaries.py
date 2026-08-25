"""Fail-closed M1b artifact path, integrity, ownership, and budget tests."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import cast

import pytest

from modeling_core.contracts.canonical_json import canonical_json_bytes
from modeling_core.contracts.versions import VersionSet
from modeling_core.ports.artifact_store import (
    ArtifactInspectionReport,
    ArtifactManifest,
    ArtifactRole,
    ArtifactStoreError,
    AttemptArtifactSink,
)
from modeling_core.ports.faults import FaultInjector, FaultPoint
from modeling_infrastructure.artifacts import store as artifact_store_module
from modeling_infrastructure.artifacts.store import ContentAddressedArtifactStore
from modeling_infrastructure.project_paths import ProjectPaths
from modeling_infrastructure.storage import bootstrap_storage

LIMIT = 64 * 1024 * 1024
VALID_SCHEMA_ID = "health_check.request"


def _uuid(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012x}"


def _store(
    tmp_path: Path,
    *,
    session_id: str | None = None,
    fault_injector: FaultInjector | None = None,
) -> ContentAddressedArtifactStore:
    bootstrap_storage(tmp_path, VersionSet.m1b())
    return ContentAddressedArtifactStore(
        ProjectPaths.bind(tmp_path),
        session_id=session_id,
        fault_injector=fault_injector,
    )


def _artifact_path(project_root: Path, full_hex: str) -> Path:
    return (
        project_root
        / ".modeling"
        / "artifacts"
        / "sha256"
        / full_hex[:2]
        / f"{full_hex}.json"
    )


class _FixedManifestStore:
    def __init__(self) -> None:
        self.calls = 0

    def publish_json(
        self,
        role: ArtifactRole,
        payload: dict[str, object],
        schema_id: str,
    ) -> ArtifactManifest:
        self.calls += 1
        artifact_id = "sha256:" + f"{self.calls:064x}"
        return ArtifactManifest(
            artifact_id=artifact_id,
            role=role,
            media_type="application/json",
            byte_size=len(canonical_json_bytes(payload)),
            sha256=artifact_id,
            schema_id=schema_id,
            created_at="2026-08-20T00:00:00.000Z",
        )

    def read_verified(
        self, artifact_id: str, expected_size: int, expected_sha256: str
    ) -> bytes:
        raise AssertionError("write-only fixture was read")

    def inspect(
        self, referenced_artifact_ids: frozenset[str]
    ) -> ArtifactInspectionReport:
        raise AssertionError("write-only fixture was inspected")


def test_forged_project_paths_cannot_escape_the_bound_project_root(
    tmp_path: Path,
) -> None:
    """Catches a forged path bundle redirecting artifact writes outside the root."""
    bootstrap_storage(tmp_path, VersionSet.m1b())
    paths = ProjectPaths.bind(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    forged = ProjectPaths(
        root=paths.root,
        modeling=paths.modeling,
        project_json=paths.project_json,
        database=paths.database,
        lock=paths.lock,
        staging=paths.staging,
        artifacts=outside,
    )

    with pytest.raises(ArtifactStoreError) as caught:
        ContentAddressedArtifactStore(forged)
    assert caught.value.code == "PATH_BOUNDARY_VIOLATION"
    assert caught.value.details == {"path": "artifacts"}
    assert not outside.exists()


def test_reparse_artifact_directory_never_writes_its_target(tmp_path: Path) -> None:
    """Catches symlink/junction traversal below an otherwise valid project root."""
    store = _store(tmp_path)
    target = tmp_path.parent / f"{tmp_path.name}-target"
    target.mkdir()
    artifacts = tmp_path / ".modeling" / "artifacts"
    artifacts.rmdir()
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(artifacts), str(target)],
            check=False,
            capture_output=True,
        )
        assert created.returncode == 0, created.stderr
    else:
        artifacts.symlink_to(target, target_is_directory=True)

    with pytest.raises(ArtifactStoreError) as caught:
        store.publish_json("result", {}, VALID_SCHEMA_ID)
    assert caught.value.code == "REPARSE_POINT"
    assert caught.value.details == {"path": "artifacts"}
    assert tuple(target.iterdir()) == ()


def test_verified_read_rejects_hash_self_consistent_noncanonical_json(
    tmp_path: Path,
) -> None:
    """Catches hash-valid evidence bypassing canonical JSON integrity."""
    store = _store(tmp_path)
    data = b'{ "status": "OK" }'
    full_hex = hashlib.sha256(data).hexdigest()
    path = _artifact_path(tmp_path, full_hex)
    path.parent.mkdir(parents=True)
    path.write_bytes(data)

    with pytest.raises(ArtifactStoreError) as caught:
        store.read_verified(f"sha256:{full_hex}", len(data), f"sha256:{full_hex}")
    assert caught.value.code == "INTEGRITY_FAILURE"
    assert caught.value.details == {"reason": "noncanonical_json"}
    assert path.read_bytes() == data


def test_wrong_schema_fails_without_leaving_staging_bytes(tmp_path: Path) -> None:
    """Catches schema-invalid content surviving a failed publication."""
    store = _store(tmp_path, session_id=_uuid(1))

    with pytest.raises(ArtifactStoreError) as caught:
        store.publish_json("result", {"unexpected": True}, VALID_SCHEMA_ID)
    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"
    assert caught.value.details == {}
    assert tuple((tmp_path / ".modeling" / "staging").iterdir()) == ()
    assert tuple((tmp_path / ".modeling" / "artifacts").rglob("*.json")) == ()


def test_seventeenth_attempt_artifact_is_rejected_before_store_call() -> None:
    """Catches the per-attempt count limit being checked after publication."""
    backing = _FixedManifestStore()
    sink = AttemptArtifactSink(backing, _uuid(2))
    for index in range(16):
        sink.publish_json("result", {"value": index}, VALID_SCHEMA_ID)

    with pytest.raises(ArtifactStoreError) as caught:
        sink.publish_json("result", {"value": 16}, VALID_SCHEMA_ID)
    assert caught.value.code == "RESOURCE_LIMIT_EXCEEDED"
    assert caught.value.details == {
        "resource": "attempt_artifacts",
        "limit": 16,
        "observed": 17,
    }
    assert backing.calls == 16


def test_attempt_cumulative_bytes_above_64_mib_are_rejected_before_store_call() -> None:
    """Catches cumulative bytes being enforced only by each individual artifact."""
    backing = _FixedManifestStore()
    sink = AttemptArtifactSink(backing, _uuid(3))
    first = "a" * (LIMIT // 2)
    second = "b" * (LIMIT // 2)
    sink.publish_json("result", {"data": first}, VALID_SCHEMA_ID)
    calls_before_rejection = backing.calls

    with pytest.raises(ArtifactStoreError) as caught:
        sink.publish_json("result", {"data": second}, VALID_SCHEMA_ID)
    assert caught.value.code == "RESOURCE_LIMIT_EXCEEDED"
    assert caught.value.details == {
        "resource": "attempt_artifact_bytes",
        "limit": LIMIT,
        "observed": LIMIT + 22,
    }
    assert backing.calls == calls_before_rejection


def test_real_store_rejects_64_mib_plus_one_before_staging(tmp_path: Path) -> None:
    """Catches oversize bytes being written before the single-artifact limit."""
    store = _store(tmp_path, session_id=_uuid(4))
    payload = {"data": "x" * (LIMIT - 10)}

    with pytest.raises(ArtifactStoreError) as caught:
        store.publish_json("result", payload, VALID_SCHEMA_ID)
    assert caught.value.code == "PAYLOAD_TOO_LARGE"
    assert caught.value.details == {
        "resource": "artifact_bytes",
        "limit": LIMIT,
        "observed": LIMIT + 1,
    }
    assert tuple((tmp_path / ".modeling" / "staging").iterdir()) == ()


def test_tampered_existing_artifact_is_never_overwritten(tmp_path: Path) -> None:
    """Catches immutable evidence being repaired or replaced after tampering."""
    store = _store(tmp_path)
    manifest = store.publish_json("result", {}, VALID_SCHEMA_ID)
    path = _artifact_path(tmp_path, manifest.artifact_id.removeprefix("sha256:"))
    tampered = b"xx"
    path.write_bytes(tampered)

    with pytest.raises(ArtifactStoreError) as caught:
        store.publish_json("result", {}, VALID_SCHEMA_ID)
    assert caught.value.code == "INTEGRITY_FAILURE"
    assert caught.value.details == {"reason": "existing_artifact_mismatch"}
    assert path.read_bytes() == tampered
    assert tuple((tmp_path / ".modeling" / "staging").iterdir()) == ()


def test_atomic_publish_never_overwrites_a_racing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches POSIX rename semantics overwriting a collision after exists-check."""
    store = _store(tmp_path, session_id=_uuid(9))
    expected_hex = hashlib.sha256(b"{}").hexdigest()
    destination = _artifact_path(tmp_path, expected_hex)
    competitor = b'{"competitor":true}'
    original_link = os.link

    def insert_competitor(path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(competitor)

    def posix_style_rename(source: str | Path, target: str | Path) -> None:
        insert_competitor(target)
        os.replace(source, target)

    def colliding_link(source: str | Path, target: str | Path) -> None:
        insert_competitor(target)
        original_link(source, target)

    monkeypatch.setattr(artifact_store_module.os, "rename", posix_style_rename)
    monkeypatch.setattr(artifact_store_module.os, "link", colliding_link)

    with pytest.raises(ArtifactStoreError) as caught:
        store.publish_json("result", {}, VALID_SCHEMA_ID)
    assert caught.value.code == "INTEGRITY_FAILURE"
    assert destination.read_bytes() == competitor
    assert tuple((tmp_path / ".modeling" / "staging").iterdir()) == ()


@pytest.mark.parametrize("suffix", ["../outside", r"..\outside", r"aa\outside"])
def test_artifact_id_rejects_backslash_and_parent_relative_surfaces(
    tmp_path: Path,
    suffix: str,
) -> None:
    """Catches artifact-relative path syntax escaping the hash tree."""
    store = _store(tmp_path)
    artifact_id = "sha256:" + suffix

    with pytest.raises(ArtifactStoreError) as caught:
        store.read_verified(artifact_id, 0, "sha256:" + "0" * 64)
    assert caught.value.code == "INVALID_ARTIFACT_ID"
    assert caught.value.details == {"artifact_id": artifact_id}


def test_failed_publish_cleans_only_its_session_file_and_reports_foreign_staging(
    tmp_path: Path,
) -> None:
    """Catches cleanup deleting unknown or previous-session crash evidence."""
    store = _store(tmp_path, session_id=_uuid(5))
    staging = tmp_path / ".modeling" / "staging"
    foreign = staging / f"{_uuid(6)}.00000000-0000-4000-8000-000000000007.json"
    foreign_bytes = b"previous-session-evidence"
    foreign.write_bytes(foreign_bytes)

    with pytest.raises(ArtifactStoreError):
        store.publish_json("result", {"unexpected": True}, VALID_SCHEMA_ID)

    assert foreign.read_bytes() == foreign_bytes
    report = store.inspect(frozenset())
    assert report.staging_files == (foreign.name,)


@pytest.mark.parametrize(
    "session_id",
    ["", "../escape", r"..\escape", "00000000-0000-4000-8000-00000000000A"],
)
def test_staging_session_id_must_be_a_canonical_uuid_v4(
    tmp_path: Path,
    session_id: str,
) -> None:
    """Catches an invalid session identifier becoming a staging path component."""
    bootstrap_storage(tmp_path, VersionSet.m1b())

    with pytest.raises(ArtifactStoreError) as caught:
        ContentAddressedArtifactStore(
            ProjectPaths.bind(tmp_path),
            session_id=session_id,
        )
    assert caught.value.code == "INVALID_SESSION_ID"
    assert caught.value.details == {}


def test_staging_filename_carries_current_session_and_unguessable_uuid(
    tmp_path: Path,
) -> None:
    """Catches staging ownership being absent or derived from user content."""

    class StopAfterWrite:
        def __init__(self) -> None:
            self.staging_file: str | None = None

        def check(self, point: FaultPoint, context: object) -> None:
            if point is FaultPoint.DURING_ARTIFACT_STAGING:
                assert isinstance(context, dict)
                self.staging_file = cast(str, context["staging_file"])
                raise RuntimeError("stop after staging")

    faults = StopAfterWrite()
    store = _store(
        tmp_path,
        session_id=_uuid(8),
        fault_injector=faults,
    )
    with pytest.raises(RuntimeError, match="stop after staging"):
        store.publish_json("result", {}, VALID_SCHEMA_ID)
    assert faults.staging_file is not None
    owner, random_part, extension = faults.staging_file.rsplit(".", 2)
    assert owner == _uuid(8)
    assert len(random_part) == 36
    assert extension == "json"
    assert tuple((tmp_path / ".modeling" / "staging").iterdir()) == ()
