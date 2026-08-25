"""Startup convergence for writes left active by an earlier process."""

from __future__ import annotations

from datetime import datetime

from modeling_core.ports.project_store import ProjectStore, RecoveryReport


class RecoveryService:
    """Keep startup policy in the application layer and mutation in the store."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def recover_previous_session(
        self, current_session_id: str, recovered_at: datetime
    ) -> RecoveryReport:
        return self._store.recover_previous_session(current_session_id, recovered_at)


__all__ = ["RecoveryService"]
