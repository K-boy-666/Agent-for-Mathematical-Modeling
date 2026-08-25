"""C1.2 read-only asset snapshot tests — RED before GREEN.

Tests verify that register_problem_assets:
- rejects paths outside the project root
- computes content-addressed SHA-256 hashes
- matches official benchmark assets against known hashes
- returns official_match=False for non-matching assets
- rejects missing files and directories
- rejects unregistered projects
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from modeling_core.application.service import ModelingApplication
from modeling_core.application import service as application_service
from modeling_core.contracts.errors import ModelingError
from modeling_core.contracts.tools import (
    AssetPathEntry,
    CreateProjectRequest,
    RegisterProblemAssetsRequest,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.registry import CapabilityRegistry
from modeling_capabilities.root_finding.solver import BisectionRootFindingCapability
from modeling_capabilities.root_finding.validator import ResidualRootFindingValidator
from modeling_infrastructure.environment import capture_environment_summary
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import bootstrap_storage


# ── official benchmark hashes from approved C1 design ──────────────────

OFFICIAL_HASHES: dict[str, str] = {
    "A题/A题.pdf": "sha256:e29940eb9eb9382deb8eccb459c73cc47f0080483b8b75f9977830c987162253",
    "A题/附件3.xlsx": "sha256:50a5dd70f04dfb0a57fb2602422dc7999b30aad54ddc02353f5b8f01423fd612",
    "A题/附件4.xlsx": "sha256:c8eff812f5980d955b4f0e587c5f7a357b2571d8d903fcb4913fba77c7354d6d",
    "A题/result1-1.xlsx": "sha256:83ed6e0f2ebcdbdcb53e99a3bfebfbd8dc16141f91396eba8806e781d7809c7a",
    "A题/result1-2.xlsx": "sha256:cc0abbceff32f425e738a3d9c0534fc3fbab4b2a1d2d86b8dc4d51229fb820bf",
}


# ── helpers ──────────────────────────────────────────────────────────


def _make_app(project_root: Path) -> ModelingApplication:
    from datetime import UTC, datetime
    import time
    import uuid

    bootstrap_storage(project_root, VersionSet.m1a())

    class _Clock:
        def utc_now(self) -> datetime:
            return datetime.now(UTC)

        def monotonic(self) -> float:
            return time.monotonic()

    class _Ids:
        def new_uuid4(self) -> str:
            return str(uuid.uuid4())

    class _NeverCancelled:
        def is_cancelled(self) -> bool:
            return False

    versions = VersionSet.m1a()
    session_id = str(uuid.uuid4())
    store = SQLiteProjectStore(
        project_root, versions, _Clock(), _Ids(), session_id=session_id
    )
    registry = CapabilityRegistry(versions)
    registry.register_capability(BisectionRootFindingCapability())
    registry.register_validator(ResidualRootFindingValidator())
    registry_summary = registry.seal(frozenset())
    return ModelingApplication(
        store=store,
        registry=registry,
        registry_summary=registry_summary,
        versions=versions,
        clock=_Clock(),
        id_generator=_Ids(),
        session_id=session_id,
        environment_summary=capture_environment_summary(
            lock_file=Path(__file__).parents[2] / "uv.lock"
        ),
        cancellation=_NeverCancelled(),
        default_display_name="test",
    )


def _create_project(app: ModelingApplication) -> str:
    import uuid as _uuid

    opid = str(_uuid.uuid4())
    request = CreateProjectRequest(
        operation_id=opid,
        display_name="test project",
    )
    result = app.create_project(request)
    return result.project_id


# ── path security ────────────────────────────────────────────────────


class TestAssetPathSecurity:
    def test_relative_path_outside_project_root_rejected(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        _create_project(app)
        request = RegisterProblemAssetsRequest(
            operation_id="00000000-0000-4000-8000-000000000010",
            project_id="00000000-0000-4000-8000-000000000001",
            asset_paths=(AssetPathEntry(label="escape", path="../etc/passwd"),),
        )
        with pytest.raises(ModelingError) as exc_info:
            app.register_problem_assets(request)
        assert exc_info.value.response.code == "SECURITY_VIOLATION"

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        _create_project(app)
        abs_path = tmp_path / "test.txt"
        abs_path.write_text("hello")
        request = RegisterProblemAssetsRequest(
            operation_id="00000000-0000-4000-8000-000000000010",
            project_id="00000000-0000-4000-8000-000000000001",
            asset_paths=(AssetPathEntry(label="abs", path=str(abs_path.resolve())),),
        )
        with pytest.raises(ModelingError) as exc_info:
            app.register_problem_assets(request)
        assert exc_info.value.response.code == "SECURITY_VIOLATION"


# ── content-addressed snapshots ───────────────────────────────────────


class TestContentAddressedSnapshots:
    def test_asset_sha256_is_computed(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        pid = _create_project(app)
        content = b"hello world"
        asset_path = tmp_path / "data.txt"
        asset_path.write_bytes(content)
        expected_hash = "sha256:" + hashlib.sha256(content).hexdigest()

        request = RegisterProblemAssetsRequest(
            operation_id="00000000-0000-4000-8000-000000000010",
            project_id=pid,
            asset_paths=(AssetPathEntry(label="data", path="data.txt"),),
        )
        result = app.register_problem_assets(request)
        assert len(result.snapshots) == 1
        assert result.snapshots[0].sha256 == expected_hash
        assert result.snapshots[0].label == "data"

    def test_official_asset_is_matched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _make_app(tmp_path)
        pid = _create_project(app)
        assert application_service._OFFICIAL_ASSET_SHA256 == frozenset(
            OFFICIAL_HASHES.values()
        )
        content = b"deterministic official-match fixture"
        expected_hash = "sha256:" + hashlib.sha256(content).hexdigest()
        monkeypatch.setattr(
            application_service, "_OFFICIAL_ASSET_SHA256", frozenset({expected_hash})
        )
        (tmp_path / "A题.pdf").write_bytes(content)

        request = RegisterProblemAssetsRequest(
            operation_id="00000000-0000-4000-8000-000000000010",
            project_id=pid,
            asset_paths=(AssetPathEntry(label="A题.pdf", path="A题.pdf"),),
        )
        result = app.register_problem_assets(request)
        assert len(result.snapshots) == 1
        assert result.snapshots[0].official_match is True
        assert result.snapshots[0].sha256 == expected_hash

    def test_non_official_asset_returns_false_match(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        pid = _create_project(app)
        asset_path = tmp_path / "custom.txt"
        asset_path.write_text("not an official benchmark asset")

        request = RegisterProblemAssetsRequest(
            operation_id="00000000-0000-4000-8000-000000000010",
            project_id=pid,
            asset_paths=(AssetPathEntry(label="custom", path="custom.txt"),),
        )
        result = app.register_problem_assets(request)
        assert len(result.snapshots) == 1
        assert result.snapshots[0].official_match is False

    def test_missing_file_is_rejected(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        pid = _create_project(app)
        request = RegisterProblemAssetsRequest(
            operation_id="00000000-0000-4000-8000-000000000010",
            project_id=pid,
            asset_paths=(AssetPathEntry(label="missing", path="nope.txt"),),
        )
        with pytest.raises(ModelingError) as exc_info:
            app.register_problem_assets(request)
        assert exc_info.value.response.code == "NOT_FOUND"

    def test_directory_is_rejected(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        pid = _create_project(app)
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        request = RegisterProblemAssetsRequest(
            operation_id="00000000-0000-4000-8000-000000000010",
            project_id=pid,
            asset_paths=(AssetPathEntry(label="dir", path="subdir"),),
        )
        with pytest.raises(ModelingError) as exc_info:
            app.register_problem_assets(request)
        assert exc_info.value.response.code == "INVALID_REQUEST"


# ── project not ready ─────────────────────────────────────────────────


class TestAssetProjectPreconditions:
    def test_project_not_ready_is_rejected(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        # No project created — project is not ready
        request = RegisterProblemAssetsRequest(
            operation_id="00000000-0000-4000-8000-000000000010",
            project_id="00000000-0000-4000-8000-000000000001",
            asset_paths=(AssetPathEntry(label="x", path="x.txt"),),
        )
        with pytest.raises(ModelingError) as exc_info:
            app.register_problem_assets(request)
        assert exc_info.value.response.code == "PRECONDITION_FAILED"
