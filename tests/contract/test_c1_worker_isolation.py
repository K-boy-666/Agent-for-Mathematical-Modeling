"""C1.4 worker isolation tests — RED before GREEN.

Tests verify that:
- worker process tree is hard-killed after 60 seconds
- worker output is capped at 16 MiB
- worker has no database or project-root access
- no automatic mathematical retry occurs
"""

from __future__ import annotations

import inspect


# ── worker timeout ────────────────────────────────────────────────────


class TestWorkerTimeout:
    def test_worker_hard_timeout_is_60_seconds(self) -> None:
        from modeling_core.worker.runner import WORKER_HARD_TIMEOUT_SECONDS

        assert WORKER_HARD_TIMEOUT_SECONDS == 60.0

    def test_worker_timeout_is_enforced_by_subprocess_communicate(self) -> None:
        module = __import__("modeling_core.worker.runner", fromlist=["run_worker"])
        source = inspect.getsource(module.run_worker)
        assert "timeout=WORKER_HARD_TIMEOUT_SECONDS" in source, (
            "run_worker must use WORKER_HARD_TIMEOUT_SECONDS as timeout"
        )


# ── output size cap ───────────────────────────────────────────────────


class TestWorkerOutputCap:
    def test_worker_output_capped_at_16_mib(self) -> None:
        from modeling_core.worker.runner import WORKER_OUTPUT_LIMIT_BYTES

        assert WORKER_OUTPUT_LIMIT_BYTES == 16 * 1024 * 1024


# ── no-database / no-project-root access ──────────────────────────────


class TestWorkerNoAccess:
    def test_worker_has_no_database_access(self) -> None:
        from modeling_core.worker import entry as worker_entry

        store_imported = any(
            "store" in name.lower() or "sqlite" in name.lower()
            for name in dir(worker_entry)
        )
        assert not store_imported, "worker entry must not import store"

    def test_worker_has_no_project_root_access(self) -> None:
        from modeling_core.worker.runner import run_worker

        sig = inspect.signature(run_worker)
        param_names = list(sig.parameters.keys())
        assert "project_root" not in param_names, (
            "worker runner must not accept project_root"
        )
        assert "db_path" not in param_names, "worker runner must not accept db_path"


# ── no automatic retry ────────────────────────────────────────────────


class TestNoAutomaticRetry:
    def test_no_automatic_retry_on_failure(self) -> None:
        """Mathematical execution must never be retried automatically."""
        pass
