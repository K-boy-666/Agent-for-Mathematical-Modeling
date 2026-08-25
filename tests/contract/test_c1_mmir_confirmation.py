"""C1.3 versioned MMIR confirmation tests — RED before GREEN.

Tests verify that:
- put_subproblem_mmir persists MMIR and returns a revision hash
- confirm_subproblem_mmir confirms an immutable revision
- run_experiment returns MMIR_NOT_CONFIRMED before confirmation
- confirm with wrong revision hash is rejected
- MMIR is immutable after confirmation (re-put generates new revision)
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from modeling_core.application.service import ModelingApplication
from modeling_core.contracts.errors import ModelingError
from modeling_core.contracts.tools import (
    ConfirmSubproblemMmirRequest,
    CreateProjectRequest,
    MmirContent,
    PutSubproblemMmirRequest,
    RunExperimentRequest,
    CapabilitySelection,
    RootFindingInput,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.registry import CapabilityRegistry
from modeling_capabilities.root_finding.solver import BisectionRootFindingCapability
from modeling_capabilities.root_finding.validator import ResidualRootFindingValidator
from modeling_infrastructure.environment import capture_environment_summary
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import bootstrap_storage


# ── helpers ──────────────────────────────────────────────────────────


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
    opid = str(uuid.uuid4())
    request = CreateProjectRequest(
        operation_id=opid,
        display_name="test project",
    )
    result = app.create_project(request)
    return result.project_id


def _sample_mmir() -> MmirContent:
    return MmirContent(
        schema_version="modeling-mmir/0.1.0",
        problem_id="CUMCM-2022-A",
        question_id="Q1",
        assumptions=(
            "static equilibrium deviation coordinates",
            "gravity and static preload cancel in increment equations",
        ),
        asset_labels=("A题.pdf", "附件3.xlsx", "附件4.xlsx"),
        derivation="coupled heave equations",
        parameters={
            "omega": 1.4005,
            "m_a": 1335.535,
            "B": 656.3616,
            "F": 6250,
            "m_f": 4866,
            "m_o": 2433,
            "r": 1,
            "rho": 1025,
            "g": 9.8,
            "k": 80000,
            "D_linear": 10000,
            "D_power_law_coeff": 10000,
            "D_power_law_exp": 0.5,
        },
    )


# ── put MMIR ─────────────────────────────────────────────────────────


class TestPutSubproblemMmir:
    def test_put_mmir_returns_revision_hash(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        pid = _create_project(app)
        mmir = _sample_mmir()
        request = PutSubproblemMmirRequest(
            operation_id="00000000-0000-4000-8000-000000000010",
            project_id=pid,
            subproblem_id="CUMCM-2022-A-Q1",
            mmir=mmir,
        )
        result = app.put_subproblem_mmir(request)
        assert result.mmir_revision.startswith("sha256:")
        assert result.status == "UNCONFIRMED"
        assert result.subproblem_id == "CUMCM-2022-A-Q1"

    def test_put_mmir_same_content_returns_same_revision(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        pid = _create_project(app)
        mmir = _sample_mmir()
        request = PutSubproblemMmirRequest(
            operation_id="00000000-0000-4000-8000-000000000010",
            project_id=pid,
            subproblem_id="CUMCM-2022-A-Q1",
            mmir=mmir,
        )
        result1 = app.put_subproblem_mmir(request)
        result2 = app.put_subproblem_mmir(request)
        assert result1.mmir_revision == result2.mmir_revision

    def test_put_mmir_different_content_returns_different_revision(
        self, tmp_path: Path
    ) -> None:
        app = _make_app(tmp_path)
        pid = _create_project(app)
        mmir1 = _sample_mmir()
        mmir2 = _sample_mmir()
        mmir2 = mmir2.model_copy(update={"derivation": "different derivation"})
        request1 = PutSubproblemMmirRequest(
            operation_id="00000000-0000-4000-8000-000000000010",
            project_id=pid,
            subproblem_id="CUMCM-2022-A-Q1",
            mmir=mmir1,
        )
        request2 = PutSubproblemMmirRequest(
            operation_id="00000000-0000-4000-8000-000000000011",
            project_id=pid,
            subproblem_id="CUMCM-2022-A-Q1",
            mmir=mmir2,
        )
        result1 = app.put_subproblem_mmir(request1)
        result2 = app.put_subproblem_mmir(request2)
        assert result1.mmir_revision != result2.mmir_revision


# ── confirm MMIR ──────────────────────────────────────────────────────


class TestConfirmSubproblemMmir:
    def test_confirm_exact_revision_succeeds(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        pid = _create_project(app)
        mmir = _sample_mmir()
        put_result = app.put_subproblem_mmir(
            PutSubproblemMmirRequest(
                operation_id="00000000-0000-4000-8000-000000000010",
                project_id=pid,
                subproblem_id="CUMCM-2022-A-Q1",
                mmir=mmir,
            )
        )
        confirm_result = app.confirm_subproblem_mmir(
            ConfirmSubproblemMmirRequest(
                operation_id="00000000-0000-4000-8000-000000000011",
                project_id=pid,
                subproblem_id="CUMCM-2022-A-Q1",
                mmir_revision=put_result.mmir_revision,
            )
        )
        assert confirm_result.status == "CONFIRMED"
        assert confirm_result.mmir_revision == put_result.mmir_revision

    def test_confirm_wrong_revision_is_rejected(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        pid = _create_project(app)
        mmir = _sample_mmir()
        app.put_subproblem_mmir(
            PutSubproblemMmirRequest(
                operation_id="00000000-0000-4000-8000-000000000010",
                project_id=pid,
                subproblem_id="CUMCM-2022-A-Q1",
                mmir=mmir,
            )
        )
        wrong_revision = (
            "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        )
        with pytest.raises(ModelingError) as exc_info:
            app.confirm_subproblem_mmir(
                ConfirmSubproblemMmirRequest(
                    operation_id="00000000-0000-4000-8000-000000000011",
                    project_id=pid,
                    subproblem_id="CUMCM-2022-A-Q1",
                    mmir_revision=wrong_revision,
                )
            )
        assert exc_info.value.response.code == "INTEGRITY_FAILURE"

    def test_confirm_unknown_subproblem_is_rejected(self, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        pid = _create_project(app)
        with pytest.raises(ModelingError) as exc_info:
            app.confirm_subproblem_mmir(
                ConfirmSubproblemMmirRequest(
                    operation_id="00000000-0000-4000-8000-000000000010",
                    project_id=pid,
                    subproblem_id="nonexistent",
                    mmir_revision="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                )
            )
        assert exc_info.value.response.code == "NOT_FOUND"


# ── MMIR_NOT_CONFIRMED guard ──────────────────────────────────────────


class TestMmirNotConfirmedGuard:
    def test_run_experiment_without_confirmed_mmir_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """RED: run_experiment must return MMIR_NOT_CONFIRMED when MMIR is put but not confirmed."""
        app = _make_app(tmp_path)
        pid = _create_project(app)
        mmir = _sample_mmir()
        app.put_subproblem_mmir(
            PutSubproblemMmirRequest(
                operation_id="00000000-0000-4000-8000-000000000009",
                project_id=pid,
                subproblem_id="CUMCM-2022-A-Q1",
                mmir=mmir,
            )
        )
        with pytest.raises(ModelingError) as exc_info:
            app.run_experiment(
                RunExperimentRequest(
                    operation_id="00000000-0000-4000-8000-000000000010",
                    project_id=pid,
                    mode="new",
                    capability=CapabilitySelection(
                        capability_id="numerical.root_finding",
                        contract_version="0.1.0",
                    ),
                    payload=RootFindingInput(
                        expression="x*x - 2",
                        lower=1,
                        upper=2,
                    ),
                )
            )
        assert exc_info.value.response.code == "PRECONDITION_FAILED"
        assert isinstance(exc_info.value.response.details, object)
        details = exc_info.value.response.details.model_dump()
        assert details.get("condition") == "mmir_not_confirmed"

    def test_run_experiment_after_mmir_confirmed_proceeds(self, tmp_path: Path) -> None:
        """Confirm MMIR, then run_experiment should work (or fail on numerical grounds)."""
        app = _make_app(tmp_path)
        pid = _create_project(app)
        mmir = _sample_mmir()
        put_result = app.put_subproblem_mmir(
            PutSubproblemMmirRequest(
                operation_id="00000000-0000-4000-8000-000000000010",
                project_id=pid,
                subproblem_id="CUMCM-2022-A-Q1",
                mmir=mmir,
            )
        )
        app.confirm_subproblem_mmir(
            ConfirmSubproblemMmirRequest(
                operation_id="00000000-0000-4000-8000-000000000011",
                project_id=pid,
                subproblem_id="CUMCM-2022-A-Q1",
                mmir_revision=put_result.mmir_revision,
            )
        )
        # After confirmation, run_experiment should not raise MMIR_NOT_CONFIRMED
        # It may still fail with numerical errors (since it's a root_finding experiment)
        result = app.run_experiment(
            RunExperimentRequest(
                operation_id="00000000-0000-4000-8000-000000000012",
                project_id=pid,
                mode="new",
                capability=CapabilitySelection(
                    capability_id="numerical.root_finding",
                    contract_version="0.1.0",
                ),
                payload=RootFindingInput(
                    expression="x*x - 2",
                    lower=1,
                    upper=2,
                ),
            )
        )
        # Should not get MMIR_NOT_CONFIRMED
        assert result is not None
