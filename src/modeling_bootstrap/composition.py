"""The sole concrete assembly location for the M1a modeling server."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from mcp.server.lowlevel import Server

from modeling_capabilities.root_finding.solver import (
    BisectionRootFindingCapability,
)
from modeling_capabilities.root_finding.validator import (
    ResidualRootFindingValidator,
)
from modeling_capabilities.dynamics import (
    CoupledHeaveCapability,
    CoupledHeaveValidator,
)
from modeling_capabilities.dynamics.exporter import build_c1_exports
from modeling_core.application.recovery import RecoveryService
from modeling_core.application.service import ModelingApplication
from modeling_core.contracts.versions import VersionSet
from modeling_core.ports.faults import FaultInjector, NoFaults
from modeling_core.ports.artifact_store import ArtifactStore
from modeling_core.registry import CapabilityRegistry
from modeling_infrastructure.artifacts.store import ContentAddressedArtifactStore
from modeling_infrastructure.environment import (
    capture_environment_snapshot,
    capture_environment_summary,
)
from modeling_infrastructure.project_paths import ProjectPaths
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_mcp.adapter import ModelingMcpAdapter
from modeling_mcp import server as mcp_server


class _SystemClock:
    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class _Uuid4Generator:
    def new_uuid4(self) -> str:
        return str(uuid.uuid4())


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


@dataclass(frozen=True)
class ModelingComposition:
    """The single concrete object graph owned by one MCP process."""

    session_id: str
    store: SQLiteProjectStore
    registry: CapabilityRegistry
    application: ModelingApplication
    adapter: ModelingMcpAdapter
    server: Server[object, object]

    def start(self) -> None:
        """Prepare an existing store for serving without bootstrapping a new one."""
        self.store.start_writer_session()
        if (
            self.store._project_lock.held
            and self.store._versions.database_schema_version == 2
        ):
            report = RecoveryService(self.store).recover_previous_session(
                self.session_id,
                datetime.now(UTC),
            )
            if not report.integrity_failure_ids:
                self.store._degraded = False
                if self.store.inspect_integrity(deep=False).issues:
                    self.store._degraded = True

    def close(self) -> None:
        """Release this composition's writer lease, if it acquired one."""
        self.store.close()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def build_composition(
    project_root: Path,
    *,
    versions: VersionSet | None = None,
    fault_injector: FaultInjector | None = None,
    artifact_store: ArtifactStore | None = None,
) -> ModelingComposition:
    """Assemble and seal one application without starting storage."""
    versions = VersionSet.m1b() if versions is None else versions
    clock = _SystemClock()
    ids = _Uuid4Generator()
    session_id = ids.new_uuid4()
    faults = fault_injector or NoFaults()
    lock_file = Path(__file__).parents[2] / "uv.lock"
    if versions.database_schema_version == 2 and artifact_store is None:
        artifact_store = ContentAddressedArtifactStore(
            ProjectPaths.bind(project_root),
            schema_version=versions.tool_contract_version.rsplit("/", 1)[1],
            session_id=session_id,
            fault_injector=faults,
        )
    if versions.database_schema_version != 2 and artifact_store is not None:
        raise ValueError("schema 1 composition does not accept an artifact store")
    store = SQLiteProjectStore(
        project_root,
        versions,
        clock,
        ids,
        session_id=session_id,
        artifact_store=artifact_store,
    )
    registry = CapabilityRegistry(versions)
    capability = BisectionRootFindingCapability(versions)
    validator = ResidualRootFindingValidator(versions)
    registry.register_capability(capability)
    registry.register_validator(validator)
    if versions.database_schema_version == 2:
        registry.register_capability(CoupledHeaveCapability(versions))
        registry.register_validator(CoupledHeaveValidator("linear", versions))
        registry.register_validator(CoupledHeaveValidator("power_law", versions))
    registry_summary = registry.seal(frozenset())
    application = ModelingApplication(
        store=store,
        registry=registry,
        registry_summary=registry_summary,
        versions=versions,
        clock=clock,
        id_generator=ids,
        session_id=session_id,
        environment_summary=capture_environment_summary(
            lock_file=lock_file,
            application_version=versions.application_release,
        ),
        cancellation=_NeverCancelled(),
        default_display_name="Math modeling project",
        artifact_store=artifact_store,
        environment_document=(
            capture_environment_snapshot(
                lock_file=lock_file,
                capability_descriptor=capability.descriptor,
                validator_descriptor=validator.descriptor,
                application_version=versions.application_release,
            )
            if artifact_store is not None
            else None
        ),
        fault_injector=faults,
        subproblem_exporter=(
            build_c1_exports if versions.database_schema_version == 2 else None
        ),
    )
    adapter = ModelingMcpAdapter(application, versions)
    server = Server[object, object](
        name="math-modeling-mcp",
        version=mcp_server.APPLICATION_VERSION,
    )
    mcp_server.configure_mcp_server(adapter, server)
    return ModelingComposition(
        session_id=session_id,
        store=store,
        registry=registry,
        application=application,
        adapter=adapter,
        server=server,
    )


def run_mcp_server(project_root: Path) -> None:
    """Run one composed MCP process and always release its writer lease."""
    composition = build_composition(project_root)
    with composition:
        asyncio.run(mcp_server.run_mcp_server(composition.server))


__all__ = ["ModelingComposition", "build_composition", "run_mcp_server"]
