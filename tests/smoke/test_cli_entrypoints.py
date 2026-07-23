import locale
from pathlib import Path
import site
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def run_module(module: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_modeling_help_exposes_three_m1a_commands() -> None:
    completed = run_module("modeling_cli", "--help")
    assert completed.returncode == 0
    assert "bootstrap" in completed.stdout
    assert "doctor" in completed.stdout
    assert "verify" in completed.stdout


def test_verify_help_requires_a_milestone_for_evidence() -> None:
    completed = run_module("modeling_cli", "verify", "--help")
    assert completed.returncode == 0
    assert "--milestone {m1a,m1b}" in completed.stdout


def test_editable_install_is_safe_in_checkout_locale() -> None:
    project_path_files = [
        path
        for site_packages in site.getsitepackages()
        for path in Path(site_packages).glob("*math_modeling_mcp*.pth")
    ]
    assert project_path_files
    for path_file in project_path_files:
        path_file.read_text(encoding=locale.getencoding())


def test_editable_loader_support_is_dev_only() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["dev-mode-exact"]
    assert "editables~=0.3" in project["dependency-groups"]["dev"]
    assert all(
        not dependency.startswith("editables")
        for dependency in project["project"]["dependencies"]
    )


if __name__ == "__main__":
    test_modeling_help_exposes_three_m1a_commands()
    test_verify_help_requires_a_milestone_for_evidence()
    test_editable_install_is_safe_in_checkout_locale()
    test_editable_loader_support_is_dev_only()
