"""Guarded scaffold for built-in capability extension — no automatic registration."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from string import Template

_VALID_CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)?$")

_SCHEMAS_DIR = "schemas" / Path("1.0.0")

_CAPABILITY_TEMPLATES: dict[str, Template] = {
    "__init__.py": Template('"""Built-in capability: ${capability_id}."""\n'),
    "context.md": Template(
        "# ${capability_id}\n\n"
        "## Purpose\n\n"
        "TODO: describe the mathematical domain and expected inputs.\n\n"
        "## Registration\n\n"
        "Add this capability to `modeling_bootstrap/composition.py`.\n"
    ),
    "contracts.py": Template(
        '"""Data contracts for ${capability_id}."""\n\n'
        "from __future__ import annotations\n\n"
        "from pydantic import BaseModel, ConfigDict\n\n\n"
        "class ${class_prefix}Input(BaseModel):\n"
        '    model_config = ConfigDict(strict=True, extra="forbid")\n'
        "    expression: str\n\n\n"
        "class ${class_prefix}SuccessData(BaseModel):\n"
        '    model_config = ConfigDict(strict=True, extra="forbid")\n'
        "    root: float\n"
        "    function_value: float\n"
        "    iterations: int\n"
        "    evaluations: int\n\n\n"
        "class ${class_prefix}FailureData(BaseModel):\n"
        '    model_config = ConfigDict(strict=True, extra="forbid")\n'
        "    failure_code: str\n"
        "    iterations: int\n"
        "    evaluations: int\n"
    ),
    "descriptor.py": Template(
        '"""Descriptor for ${capability_id}."""\n\n'
        "from __future__ import annotations\n\n"
        "from modeling_core.contracts.capability import CapabilityDescriptor\n"
        "from modeling_core.contracts.schema_catalog import SchemaCatalog\n"
        "from modeling_core.contracts.tools import (\n"
        "    CapabilitySummary,\n"
        "    ValidatorSummary,\n"
        ")\n\n\n"
        '_CATALOG = SchemaCatalog.load_packaged("1.0.0")\n'
        "_COMMON = _CATALOG.common_schemas\n\n\n"
        "def build_descriptor() -> CapabilityDescriptor:\n"
        "    return CapabilityDescriptor(\n"
        '        kind="built_in",\n'
        '        capability_api_version="modeling-capability/1.0.0",\n'
        '        capability_id="${capability_id}",\n'
        '        contract_version="1.0.0",\n'
        '        implementation_id="${capability_id}",\n'
        '        implementation_version="0.1.0",\n'
        '        title="${title}",\n'
        '        summary="${summary}",\n'
        '        category="numerical",\n'
        '        tags=("root-finding",),\n'
        '        determinism="deterministic",\n'
        '        randomness="not_used",\n'
        "        input_schema=_COMMON[\n"
        '            "https://schemas.math-modeling-mcp.local/common/1.0.0/'
        'modeling-error.schema.json"\n'
        "        ],\n"
        "        canonical_input_schema=_COMMON[\n"
        '            "https://schemas.math-modeling-mcp.local/common/1.0.0/'
        'modeling-error.schema.json"\n'
        "        ],\n"
        "        success_schema=_COMMON[\n"
        '            "https://schemas.math-modeling-mcp.local/common/1.0.0/'
        'modeling-error.schema.json"\n'
        "        ],\n"
        "        failure_schema=_COMMON[\n"
        '            "https://schemas.math-modeling-mcp.local/common/1.0.0/'
        'modeling-error.schema.json"\n'
        "        ],\n"
        "        default_limits=CapabilitySummary._default_limits(),\n"
        "        maximum_limits=CapabilitySummary._default_limits(),\n"
        "        artifact_roles=(),\n"
        "        validators=[\n"
        "            ValidatorSummary(\n"
        '                validator_id="${capability_id}.residual",\n'
        '                summary="Residual-based validator for ${capability_id}.",\n'
        '                report_schema_version="0.1.0",\n'
        "                report_schema=_COMMON[\n"
        '                    "https://schemas.math-modeling-mcp.local/common/'
        '1.0.0/modeling-error.schema.json"\n'
        "                ],\n"
        '                report_schema_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",\n'
        "                policies=[],\n"
        "            ),\n"
        "        ],\n"
        '        context_ref="${capability_id}",\n'
        "    )\n"
    ),
    "solver.py": Template(
        '"""Solver for ${capability_id}."""\n\n'
        "from __future__ import annotations\n\n"
        "from modeling_core.contracts.capability import (\n"
        "    BuiltInCapability,\n"
        "    CanonicalInputRecord,\n"
        "    ExecutionContext,\n"
        "    ExecutionOutcome,\n"
        ")\n"
        "from modeling_core.contracts.common import JsonObject\n\n\n"
        "class ${class_prefix}Solver:\n"
        "    def __init__(self) -> None:\n"
        "        from ${module_path}.descriptor import build_descriptor\n"
        "        self._descriptor = build_descriptor()\n\n"
        "    @property\n"
        "    def descriptor(self):\n"
        "        return self._descriptor\n\n"
        "    def normalize_and_validate(\n"
        "        self, raw_payload: JsonObject\n"
        "    ) -> CanonicalInputRecord:\n"
        "        raise NotImplementedError(\n"
        '            "capability behavior must be specified before registration"\n'
        "        )\n\n"
        "    def execute(\n"
        "        self,\n"
        "        canonical_input: CanonicalInputRecord,\n"
        "        context: ExecutionContext,\n"
        "    ) -> ExecutionOutcome:\n"
        "        raise NotImplementedError(\n"
        '            "capability behavior must be specified before registration"\n'
        "        )\n"
    ),
    "validator.py": Template(
        '"""Validator for ${capability_id}."""\n\n'
        "from __future__ import annotations\n\n"
        "from modeling_core.contracts.capability import (\n"
        "    CapabilityValidator,\n"
        "    CanonicalInputRecord,\n"
        "    ResultSnapshotView,\n"
        "    ValidationContext,\n"
        "    ValidationReport,\n"
        ")\n"
        "from modeling_core.contracts.common import JsonObject\n\n\n"
        "class ${class_prefix}Validator:\n"
        "    def __init__(self) -> None:\n"
        "        from modeling_core.contracts.schema_catalog import SchemaCatalog\n"
        '        catalog = SchemaCatalog.load_packaged("1.0.0")\n'
        "        self._descriptor = ...  # TODO: build ValidatorDescriptor\n\n"
        "    @property\n"
        "    def descriptor(self):\n"
        "        return self._descriptor\n\n"
        "    def validate(\n"
        "        self,\n"
        "        canonical_input: CanonicalInputRecord,\n"
        "        result_snapshot: ResultSnapshotView,\n"
        "        policy: JsonObject,\n"
        "        context: ValidationContext,\n"
        "    ) -> ValidationReport:\n"
        "        raise NotImplementedError(\n"
        '            "capability behavior must be specified before registration"\n'
        "        )\n"
    ),
}

_TEST_TEMPLATES: dict[str, Template] = {
    "test_contract.py": Template(
        '"""Contract tests for ${capability_id}."""\n\n'
        "from __future__ import annotations\n\n"
        "import pytest\n\n\n"
        "def test_descriptor_structure() -> None:\n"
        "    from ${module_path}.descriptor import build_descriptor\n"
        "    descriptor = build_descriptor()\n"
        '    assert descriptor.kind == "built_in"\n'
        '    assert descriptor.capability_id == "${capability_id}"\n'
        '    assert descriptor.contract_version == "1.0.0"\n\n\n'
        "def test_schema_assets_exist() -> None:\n"
        "    from importlib import resources\n"
        "    schemas = [\n"
        '        "input.schema.json",\n'
        '        "canonical-input.schema.json",\n'
        '        "success-data.schema.json",\n'
        '        "failure-data.schema.json",\n'
        '        "policy.schema.json",\n'
        '        "report.schema.json",\n'
        "    ]\n"
        "    for name in schemas:\n"
        '        assert resources.files("${module_path}").joinpath(\n'
        '            "schemas", "1.0.0", name\n'
        "        ).is_file()\n"
    ),
    "test_solver.py": Template(
        '"""Solver tests for ${capability_id}."""\n\n'
        "from __future__ import annotations\n\n"
        "import pytest\n\n\n"
        "def test_solver_not_implemented() -> None:\n"
        "    from ${module_path}.solver import ${class_prefix}Solver\n"
        "    solver = ${class_prefix}Solver()\n"
        '    with pytest.raises(NotImplementedError, match="capability behavior"):\n'
        "        solver.normalize_and_validate({})\n"
    ),
    "test_validator.py": Template(
        '"""Validator tests for ${capability_id}."""\n\n'
        "from __future__ import annotations\n\n"
        "import pytest\n\n\n"
        "def test_validator_not_implemented() -> None:\n"
        "    from ${module_path}.validator import ${class_prefix}Validator\n"
        "    validator = ${class_prefix}Validator()\n"
        "    with pytest.raises(\n"
        '        NotImplementedError, match="capability behavior"\n'
        "    ):\n"
        "        validator.validate(None, None, {}, None)  # type: ignore[arg-type]\n"
    ),
    "test_metamorphic.py": Template(
        '"""Metamorphic tests for ${capability_id}."""\n\n'
        "from __future__ import annotations\n\n"
        "import pytest\n\n\n"
        "def test_metamorphic_not_implemented() -> None:\n"
        "    pytest.skip(\n"
        '        "capability behavior must be specified before registration"\n'
        "    )\n"
    ),
}

_EMPTY_SCHEMA = (
    "{\n"
    '  "$schema": "https://json-schema.org/draft/2020-12/schema",\n'
    '  "$id": "https://schemas.math-modeling-mcp.local/capabilities/'
    '${capability_id}/1.0.0/${schema_name}.schema.json"\n'
    "}\n"
)


def _validate_capability_id(capability_id: str) -> None:
    if not _VALID_CAPABILITY_ID.fullmatch(capability_id):
        raise ValueError(
            f"invalid capability_id: {capability_id!r} "
            f"(must match {_VALID_CAPABILITY_ID.pattern})"
        )
    if capability_id.startswith("external."):
        raise ValueError(
            f"external plugin capabilities are not supported: {capability_id!r}"
        )


def _class_prefix(capability_id: str) -> str:
    return "".join(part.capitalize() for part in capability_id.split("."))


def _module_path(capability_id: str) -> str:
    return capability_id.replace(".", "_")


def _title(capability_id: str) -> str:
    return " ".join(part.capitalize() for part in capability_id.split("."))


@dataclass(frozen=True, slots=True)
class ScaffoldResult:
    capability_root: Path
    tests_root: Path


def scaffold_builtin_capability(
    capability_id: str,
    destination_root: Path,
    tests_root: Path,
) -> ScaffoldResult:
    """Generate a built-in capability scaffold without modifying any existing file.

    Writes capability files under `destination_root` and test files under
    `tests_root`.  Neither destination may already exist.  Registration
    instructions are printed to stdout.
    """
    _validate_capability_id(capability_id)

    parts = capability_id.split(".")
    package_dir = destination_root / Path(*parts)
    tests_package_dir = tests_root / Path(*parts)

    if package_dir.exists():
        raise FileExistsError(f"capability destination already exists: {package_dir}")
    if tests_package_dir.exists():
        raise FileExistsError(f"test destination already exists: {tests_package_dir}")

    prefix = _class_prefix(capability_id)
    mod_path = _module_path(capability_id)
    title = _title(capability_id)
    summary = f"${title} solver."

    substitutions = {
        "capability_id": capability_id,
        "class_prefix": prefix,
        "module_path": mod_path,
        "title": title,
        "summary": summary,
    }

    # Stage capability files
    first_created: Path | None = None
    try:
        schemas_dir = package_dir / _SCHEMAS_DIR
        schemas_dir.mkdir(parents=True)
        first_created = package_dir

        for name, template in _CAPABILITY_TEMPLATES.items():
            _write_atomic(package_dir / name, template.safe_substitute(substitutions))

        schema_names = [
            "input",
            "canonical-input",
            "success-data",
            "failure-data",
            "policy",
            "report",
        ]
        for schema_name in schema_names:
            _write_atomic(
                schemas_dir / f"{schema_name}.schema.json",
                Template(_EMPTY_SCHEMA).safe_substitute(
                    capability_id=capability_id,
                    schema_name=schema_name,
                ),
            )

        # Stage test files (second phase)
        tests_package_dir.mkdir(parents=True)
        for name, template in _TEST_TEMPLATES.items():
            _write_atomic(
                tests_package_dir / name,
                template.safe_substitute(substitutions),
            )
    except BaseException:
        # Clean up only the first directory we created
        if first_created is not None and first_created.exists():
            shutil.rmtree(first_created)
        raise

    # Print registration instructions
    print(
        f"# To register {capability_id}, add the following to "
        f"modeling_bootstrap/composition.py:\n"
        f"#   from {mod_path}.solver import {prefix}Solver\n"
        f"#   from {mod_path}.validator import {prefix}Validator\n"
        f"#   registry.register_capability({prefix}Solver())\n"
        f"#   registry.register_validator({prefix}Validator())\n"
        f"\n"
        f"# Focused acceptance command:\n"
        f"#   modeling verify --capability {capability_id}\n"
    )

    return ScaffoldResult(
        capability_root=package_dir,
        tests_root=tests_package_dir,
    )


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
