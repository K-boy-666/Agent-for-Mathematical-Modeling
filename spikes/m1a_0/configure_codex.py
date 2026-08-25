from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


MARKER = '"__M1A0_REPOSITORY_ROOT__"'


def render_codex_config(template_text: str, repository_root: Path) -> str:
    if template_text.count(MARKER) != 1:
        raise ValueError("Codex configuration template must contain one repository marker")
    return template_text.replace(MARKER, json.dumps(str(repository_root.resolve()), ensure_ascii=False))


def materialize_codex_config(
    repository_root: Path, template_path: Path, destination_path: Path
) -> Path:
    rendered = render_codex_config(template_path.read_text(encoding="utf-8"), repository_root)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination_path.parent, prefix=".config.", suffix=".tmp"
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as temporary_file:
            temporary_file.write(rendered)
        os.replace(temporary_path, destination_path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return destination_path


def main() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    materialize_codex_config(
        repository_root,
        Path(__file__).with_name("codex-config.toml"),
        repository_root / ".codex" / "config.toml",
    )


if __name__ == "__main__":
    main()
