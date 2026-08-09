from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Iterator

from modeling_capabilities.root_finding.solver import (
    BisectionRootFindingCapability,
)
from modeling_capabilities.root_finding.validator import (
    ResidualRootFindingValidator,
)
from modeling_core.application import ModelingApplication
from modeling_core.contracts.tools import (
    CapabilitySelection,
    CreateProjectRequest,
    EnvironmentSummary,
    GetProjectStatusExperimentRequest,
    RootFindingInput,
    RunExperimentRequest,
    RunExperimentSucceededResult,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.registry import CapabilityRegistry
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import bootstrap_storage


class FakeClock:
    def __init__(self, start: datetime, monotonic_start: float = 0.0) -> None:
        self._now = start
        self._monotonic = monotonic_start

    def utc_now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic


class FixedIdGenerator:
    def __init__(self, values: Iterable[str]) -> None:
        self._values: Iterator[str] = iter(values)

    def new_uuid4(self) -> str:
        return next(self._values)


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


def _uuid(index: int) -> str:
    return f"10000000-0000-4000-8000-{index:012x}"


def _build_application(project_root: Path) -> ModelingApplication:
    versions = VersionSet.m1a()
    bootstrap_storage(project_root, versions)
    registry = CapabilityRegistry(versions)
    registry.register_capability(BisectionRootFindingCapability())
    registry.register_validator(ResidualRootFindingValidator())
    registry_summary = registry.seal(frozenset())
    return ModelingApplication(
        store=SQLiteProjectStore(project_root, versions),
        registry=registry,
        registry_summary=registry_summary,
        versions=versions,
        clock=FakeClock(datetime(2026, 7, 17, tzinfo=UTC)),
        id_generator=FixedIdGenerator(_uuid(index) for index in range(100, 150)),
        session_id=_uuid(90),
        environment_summary=EnvironmentSummary(
            python_version="3.11.14",
            application_version="0.1.0",
            lock_hash="sha256:" + ("2" * 64),
        ),
        cancellation=_NeverCancelled(),
        default_display_name="M1a repeatability",
    )


def test_distinct_experiments_preserve_deterministic_identity_and_result(
    tmp_path: Path,
) -> None:
    """Catches repeated runs that drift in contracts, hashes, or root value."""
    application = _build_application(tmp_path)
    project = application.create_project(CreateProjectRequest(operation_id=_uuid(1)))

    selection = CapabilitySelection(
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
    )
    payload = RootFindingInput(
        expression="x*x - 2",
        lower=0.0,
        upper=2.0,
    )
    first = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(2),
            project_id=project.project_id,
            mode="new",
            capability=selection,
            payload=payload,
        )
    )
    second = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(3),
            project_id=project.project_id,
            mode="new",
            capability=selection,
            payload=payload,
        )
    )

    assert isinstance(first, RunExperimentSucceededResult)
    assert isinstance(second, RunExperimentSucceededResult)
    assert first.experiment_id != second.experiment_id
    assert first.attempt_status == second.attempt_status == "SUCCEEDED"
    assert first.result_kind == second.result_kind == "success"
    assert (
        first.capability_id,
        first.contract_version,
        first.implementation_id,
        first.implementation_version,
    ) == (
        second.capability_id,
        second.contract_version,
        second.implementation_id,
        second.implementation_version,
    )

    first_trace = application.get_project_status(
        GetProjectStatusExperimentRequest(
            project_id=project.project_id,
            view="experiment",
            experiment_id=first.experiment_id,
        )
    )
    second_trace = application.get_project_status(
        GetProjectStatusExperimentRequest(
            project_id=project.project_id,
            view="experiment",
            experiment_id=second.experiment_id,
        )
    )
    assert (
        first_trace.experiment.canonical_payload_hash,
        first_trace.experiment.model_snapshot_hash,
        first_trace.experiment.data_snapshot_set_hash,
    ) == (
        second_trace.experiment.canonical_payload_hash,
        second_trace.experiment.model_snapshot_hash,
        second_trace.experiment.data_snapshot_set_hash,
    )
    assert math.isclose(
        first.result_summary.root,
        second.result_summary.root,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
