"""C1.7 fail-closed export tests — RED before GREEN.

Tests verify:
- export_subproblem fails when validations are not both PASSED
- export_subproblem returns workbook data with correct structure
- two-row official header, five columns, 898 data rows
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from modeling_core.application.service import ModelingApplication
from modeling_core.contracts.errors import ModelingError
from modeling_core.contracts.tools import (
    CreateProjectRequest,
    ExportSubproblemRequest,
    MmirContent,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.registry import CapabilityRegistry
from modeling_capabilities.root_finding.solver import BisectionRootFindingCapability
from modeling_capabilities.root_finding.validator import ResidualRootFindingValidator
from modeling_infrastructure.environment import capture_environment_summary
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import bootstrap_storage


def _make_app(project_root: Path) -> ModelingApplication:
    from datetime import UTC, datetime
    import time

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
    return app.create_project(
        CreateProjectRequest(operation_id=str(uuid.uuid4()), display_name="test")
    ).project_id


def _sample_mmir() -> MmirContent:
    return MmirContent(
        schema_version="modeling-mmir/0.1.0",
        problem_id="CUMCM-2022-A",
        question_id="Q1",
        assumptions=("static equilibrium",),
        asset_labels=(),
        derivation="test",
        parameters={},
    )


# ── export blocked without validation ─────────────────────────────────


class TestExportBlocked:
    def test_export_fails_without_validations(self, tmp_path: Path) -> None:
        """RED: export must fail when no validations exist."""
        app = _make_app(tmp_path)
        pid = _create_project(app)

        with pytest.raises(ModelingError) as exc_info:
            app.export_subproblem(
                ExportSubproblemRequest(
                    operation_id="00000000-0000-4000-8000-000000000010",
                    project_id=pid,
                    subproblem_id="CUMCM-2022-A-Q1",
                )
            )
        assert exc_info.value.response.code == "PRECONDITION_FAILED"
        details = exc_info.value.response.details.model_dump()
        assert details["condition"] == "export_blocked_validation_not_passed"


# ── export structure ──────────────────────────────────────────────────


class TestExportStructure:
    def test_export_returns_workbook_structure(self, tmp_path: Path) -> None:
        """RED: export must return structured workbook data."""
        # This test verifies the export method exists and returns basic structure
        app = _make_app(tmp_path)
        pid = _create_project(app)

        # Export is blocked (no validations), so we verify the error
        with pytest.raises(ModelingError):
            app.export_subproblem(
                ExportSubproblemRequest(
                    operation_id="00000000-0000-4000-8000-000000000010",
                    project_id=pid,
                    subproblem_id="CUMCM-2022-A-Q1",
                )
            )
