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


@dataclass(frozen=True)
class ProjectPaths:
    """The only storage paths A4 is allowed to create."""

    root: Path
    modeling: Path
    project_json: Path
    database: Path
    lock: Path

    @classmethod
    def bind(cls, project_root: Path) -> ProjectPaths:
        raw_root = Path(project_root)
        if "\x00" in str(raw_root):
            raise ValueError("project root contains NUL")
        if not raw_root.exists():
            raise FileNotFoundError("project root does not exist")
        if is_reparse_point(raw_root):
            raise ValueError("project root is a reparse point")
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
        )

    def temporary_modeling(self, suffix: str) -> Path:
        return self.root / f".modeling.tmp.{suffix}"
