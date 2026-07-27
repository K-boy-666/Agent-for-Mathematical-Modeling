"""Cross-platform nonblocking project writer lock."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from modeling_infrastructure.storage import StorageError


class StorageConflict(StorageError):
    """A transient writer-lock conflict."""

    def __init__(self) -> None:
        super().__init__(
            "CONFLICT",
            "project is busy",
            retryable=True,
            details={"conflict_type": "project_busy", "retry_after_ms": 250},
        )


class _FcntlModule(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, descriptor: int, operation: int) -> None: ...


def _fcntl_module() -> _FcntlModule:
    return cast(_FcntlModule, importlib.import_module("fcntl"))


class ProjectLock:
    """Hold one nonblocking OS lock until explicitly released."""

    def __init__(self, path: Path, session_id: str) -> None:
        self._path = Path(path)
        self._session_id = session_id
        self._stream: BinaryIO | None = None

    @property
    def held(self) -> bool:
        return self._stream is not None

    def acquire(self) -> None:
        if self._stream is not None:
            raise RuntimeError("project lock is already held")
        try:
            stream = self._path.open("r+b")
        except FileNotFoundError:
            stream = self._path.open("w+b")
            stream.write(b"\0")
            stream.flush()
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    raise StorageConflict from error
            else:
                fcntl = _fcntl_module()
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    raise StorageConflict from error
            stream.seek(0)
            stream.write(self._session_id.encode("ascii"))
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            self._stream = stream
        except BaseException:
            stream.close()
            raise

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl = _fcntl_module()
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._stream = None
            stream.close()

    def __enter__(self) -> ProjectLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
