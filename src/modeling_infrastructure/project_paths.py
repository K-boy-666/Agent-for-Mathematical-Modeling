"""Bound project paths with fail-closed reparse-point checks."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path


_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def is_reparse_point(path: Path) -> bool:
    """Return whether *path* is a symlink, junction, or Windows reparse point."""
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(details, "st_file_attributes", 0)
    return stat.S_ISLNK(details.st_mode) or bool(
        attributes & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _reject_reparse_components(path: Path) -> None:
    if path.drive and not path.root:
        raise ValueError("project root uses a drive-relative path")
    bound = path if path.is_absolute() else Path.cwd() / path
    if not bound.is_absolute() or not bound.anchor:
        raise ValueError("project root cannot be bound to a filesystem root")

    current = Path(bound.anchor)
    if is_reparse_point(current):
        raise ValueError("project root has a reparse-point ancestor")
    for component in bound.parts[1:]:
        current /= component
        if is_reparse_point(current):
            raise ValueError("project root has a reparse-point ancestor")


@dataclass(frozen=True)
class ProjectPaths:
    """The only storage paths A4 is allowed to create."""

    root: Path
    modeling: Path
    project_json: Path
    database: Path
    lock: Path
    staging: Path
    artifacts: Path

    @classmethod
    def bind(cls, project_root: Path) -> ProjectPaths:
        raw_root = Path(project_root)
        if "\x00" in str(raw_root):
            raise ValueError("project root contains NUL")
        _reject_reparse_components(raw_root)
        if not raw_root.exists():
            raise FileNotFoundError("project root does not exist")
        root = raw_root.resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError("project root is not a directory")
        modeling = root / ".modeling"
        if is_reparse_point(modeling):
            raise ValueError(".modeling is a reparse point")
        return cls(
            root=root,
            modeling=modeling,
            project_json=modeling / "project.json",
            database=modeling / "state.sqlite3",
            lock=modeling / "project.lock",
            staging=modeling / "staging",
            artifacts=modeling / "artifacts",
        )

    def temporary_modeling(self, suffix: str) -> Path:
        return self.root / f".modeling.tmp.{suffix}"
