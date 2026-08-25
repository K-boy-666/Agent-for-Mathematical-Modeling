"""B3 architecture tests — prove built-in capability extension without modifying core."""

from __future__ import annotations

import hashlib
from pathlib import Path

import sys

import pytest

# Allow importing from tests/fixtures
sys.path.insert(0, str(Path(__file__).parents[1]))

from fixtures.test_echo_capability import compose_test_echo_registry  # noqa: E402
from modeling_harness.capability_scaffold import (  # noqa: E402
    scaffold_builtin_capability,
)


def _file_manifest(root: Path) -> list[tuple[str, str]]:
    """Return sorted (relative_path, sha256) for all files under root."""
    result: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            rel = path.relative_to(root).as_posix()
            sha = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            result.append((rel, sha))
    return result


class TestEchoExtension:
    """Prove that test.echo extends the registry without touching core files."""

    def test_sealed_registry_lists_and_resolves_echo(self) -> None:
        """A sealed registry composed with test.echo lists and resolves it."""
        registry = compose_test_echo_registry()
        assert registry.sealed is True

        # List summaries includes test.echo
        summaries = registry.list_summaries(category=None, capability_id=None)
        echo_ids = [s.capability_id for s in summaries]
        assert "test.echo" in echo_ids

        # Resolve test.echo
        capability = registry.resolve("test.echo", "0.1.0")
        assert capability.descriptor.capability_id == "test.echo"

    def test_echo_executes_and_validates(self) -> None:
        """The echo fixture executes and its validator passes."""
        registry = compose_test_echo_registry()
        capability = registry.resolve("test.echo", "0.1.0")

        from modeling_core.contracts.capability import ExecutionContext
        import time

        record = capability.normalize_and_validate({"message": "hello"})
        outcome = capability.execute(
            record,
            ExecutionContext(
                attempt_id="00000000-0000-4000-8000-000000000001",
                randomness="not_used",
                seed=None,
                deadline=time.time() + 3600,
                clock=lambda: time.monotonic(),
                cancellation=lambda: False,
            ),
        )
        assert outcome.result_kind == "success"

        # Validate
        validator = registry.resolve_validator(
            "test.echo", "test.echo", "0.1.0", "1.0.0"
        )
        from modeling_core.contracts.capability import (
            ResultSnapshotView,
            ValidationContext,
        )
        import time

        report = validator.validate(
            record,
            ResultSnapshotView(
                result_snapshot_id="00000000-0000-4000-8000-000000000001",
                capability_id="test.echo",
                contract_version="0.1.0",
                result_schema_version="0.1.0",
                result_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                result_payload=outcome.result_payload,
            ),
            {},
            ValidationContext(
                deadline=time.time() + 3600,
                clock=lambda: time.monotonic(),
                cancellation=lambda: False,
            ),
        )
        assert report.outcome == "PASSED"

    def test_core_manifest_unchanged_after_echo(self, tmp_path: Path) -> None:
        """src/modeling_core manifest is identical before and after echo."""
        core_root = Path(__file__).parents[2] / "src" / "modeling_core"
        before = _file_manifest(core_root)

        # Compose and execute echo (should not touch core files)
        registry = compose_test_echo_registry()
        capability = registry.resolve("test.echo", "0.1.0")

        from modeling_core.contracts.capability import ExecutionContext
        import time

        record = capability.normalize_and_validate({"message": "hello"})
        capability.execute(
            record,
            ExecutionContext(
                attempt_id="00000000-0000-4000-8000-000000000001",
                randomness="not_used",
                seed=None,
                deadline=time.time() + 3600,
                clock=lambda: time.monotonic(),
                cancellation=lambda: False,
            ),
        )

        after = _file_manifest(core_root)
        assert before == after

    def test_scaffold_produces_exact_file_set(self, tmp_path: Path) -> None:
        """Scaffold output contains exactly the expected 12 capability + 4 test files."""
        dest = tmp_path / "src"
        tests_dest = tmp_path / "tests"
        dest.mkdir()
        tests_dest.mkdir()

        scaffold_builtin_capability(
            "numerical.secant",
            destination_root=dest,
            tests_root=tests_dest,
        )

        cap_files = sorted(
            p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()
        )
        expected_cap = [
            "numerical/secant/__init__.py",
            "numerical/secant/context.md",
            "numerical/secant/contracts.py",
            "numerical/secant/descriptor.py",
            "numerical/secant/schemas/1.0.0/canonical-input.schema.json",
            "numerical/secant/schemas/1.0.0/failure-data.schema.json",
            "numerical/secant/schemas/1.0.0/input.schema.json",
            "numerical/secant/schemas/1.0.0/policy.schema.json",
            "numerical/secant/schemas/1.0.0/report.schema.json",
            "numerical/secant/schemas/1.0.0/success-data.schema.json",
            "numerical/secant/solver.py",
            "numerical/secant/validator.py",
        ]
        assert cap_files == expected_cap

        test_files = sorted(
            p.relative_to(tests_dest).as_posix()
            for p in tests_dest.rglob("*")
            if p.is_file()
        )
        expected_test = [
            "numerical/secant/test_contract.py",
            "numerical/secant/test_metamorphic.py",
            "numerical/secant/test_solver.py",
            "numerical/secant/test_validator.py",
        ]
        assert test_files == expected_test

    def test_invalid_capability_id_rejected(self, tmp_path: Path) -> None:
        """Invalid capability IDs are rejected without writing files."""
        dest = tmp_path / "src"
        tests_dest = tmp_path / "tests"
        dest.mkdir()
        tests_dest.mkdir()

        invalid_ids = [
            "external.test",
            "Numerical.Secant",
            "numerical/secant",
            "numerical.secant.extra.deep",
        ]
        for invalid_id in invalid_ids:
            with pytest.raises(ValueError):
                scaffold_builtin_capability(
                    invalid_id,
                    destination_root=dest,
                    tests_root=tests_dest,
                )
            # No files should be written
            assert list(dest.rglob("*")) == []
            assert list(tests_dest.rglob("*")) == []

    def test_existing_destination_rejected(self, tmp_path: Path) -> None:
        """An existing destination is rejected without overwriting."""
        dest = tmp_path / "src"
        tests_dest = tmp_path / "tests"
        dest.mkdir()
        tests_dest.mkdir()

        # First scaffold succeeds
        scaffold_builtin_capability(
            "numerical.secant",
            destination_root=dest,
            tests_root=tests_dest,
        )

        # Second scaffold to same destination fails
        with pytest.raises(FileExistsError):
            scaffold_builtin_capability(
                "numerical.secant",
                destination_root=dest,
                tests_root=tests_dest,
            )

    def test_registration_instructions_name_composition(self, capsys) -> None:
        """Scaffold stdout references modeling_bootstrap/composition.py."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "src"
            tests_dest = Path(tmp) / "tests"
            dest.mkdir()
            tests_dest.mkdir()

            scaffold_builtin_capability(
                "numerical.secant",
                destination_root=dest,
                tests_root=tests_dest,
            )

        captured = capsys.readouterr()
        assert "modeling_bootstrap/composition.py" in captured.out
        assert "entry point" not in captured.out.lower()
        assert "directory scanning" not in captured.out.lower()
