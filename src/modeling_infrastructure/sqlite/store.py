"""Schema-1 SQLite implementation of the A3 project-store port."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from modeling_core.contracts.common import ProjectSummary
from modeling_core.contracts.versions import VersionSet
from modeling_core.domain.models import Project
from modeling_core.domain.states import ProjectState
from modeling_core.ports.clock import Clock
from modeling_core.ports.ids import IdGenerator
from modeling_core.ports.project_store import (
    BeginRunCommand,
    BeginRunResult,
    BeginValidationCommand,
    BeginValidationResult,
    CompleteAttemptCommand,
    CompleteValidationCommand,
    CreateProjectCommand,
    ExperimentTrace,
    ExperimentTraceQuery,
    ProjectStateInspection,
    ProjectWriteResult,
    StoreIntegrityReport,
    StoredRunResult,
    StoredValidationResult,
)
from modeling_infrastructure.project_paths import ProjectPaths
from modeling_infrastructure.storage import load_storage_metadata

if TYPE_CHECKING:
    from modeling_core.ports.project_store import ProjectStore


class SQLiteProjectStore:
    """ProjectStore shell backed by the schema established in A4."""

    def __init__(
        self,
        project_root: Path,
        versions: VersionSet,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._paths = ProjectPaths.bind(project_root)
        self._versions = versions
        self._clock = clock
        self._id_generator = id_generator

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._paths.database, timeout=0.25)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=250")
        return connection

    def inspect_project_state(self) -> ProjectStateInspection:
        if not self._paths.modeling.exists():
            return ProjectStateInspection(state=ProjectState.UNINITIALIZED)
        metadata = load_storage_metadata(self._paths.root, self._versions)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT project_id, storage_instance_id, project_format_version,
                       display_name, created_at
                FROM projects
                """
            ).fetchall()
        if not rows:
            return ProjectStateInspection(state=metadata.project_state)
        if len(rows) != 1:
            return ProjectStateInspection(state=ProjectState.DEGRADED)
        row = rows[0]
        project = Project(
            project_id=row[0],
            storage_instance_id=row[1],
            project_format_version=row[2],
            display_name=row[3],
            created_at=datetime.fromisoformat(row[4].replace("Z", "+00:00")),
        )
        return ProjectStateInspection(state=ProjectState.READY, project=project)

    def create_or_replay_project(
        self, command: CreateProjectCommand
    ) -> ProjectWriteResult:
        raise NotImplementedError("project workflow is owned by A9")

    def get_project_summary(self, project_id: str) -> ProjectSummary:
        raise NotImplementedError("project workflow is owned by A9")

    def get_experiment_trace(self, query: ExperimentTraceQuery) -> ExperimentTrace:
        raise NotImplementedError("experiment workflow is owned by A9")

    def begin_run(self, command: BeginRunCommand) -> BeginRunResult:
        raise NotImplementedError("experiment workflow is owned by A9")

    def mark_attempt_running(
        self, attempt_id: str, started_at: datetime, session_id: str
    ) -> None:
        raise NotImplementedError("experiment workflow is owned by A9")

    def complete_attempt(self, command: CompleteAttemptCommand) -> StoredRunResult:
        raise NotImplementedError("experiment workflow is owned by A9")

    def begin_validation(
        self, command: BeginValidationCommand
    ) -> BeginValidationResult:
        raise NotImplementedError("validation workflow is owned by A9")

    def mark_validation_running(
        self, validation_id: str, started_at: datetime
    ) -> None:
        raise NotImplementedError("validation workflow is owned by A9")

    def complete_validation(
        self, command: CompleteValidationCommand
    ) -> StoredValidationResult:
        raise NotImplementedError("validation workflow is owned by A9")

    def inspect_integrity(self, deep: bool) -> StoreIntegrityReport:
        inspection = self.inspect_project_state()
        return StoreIntegrityReport(state=inspection.state, issues=())


if TYPE_CHECKING:
    _project_store_contract: ProjectStore = SQLiteProjectStore(
        Path(), VersionSet.m1a()
    )
