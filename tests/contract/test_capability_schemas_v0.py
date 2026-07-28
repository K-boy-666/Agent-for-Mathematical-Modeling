from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
import pytest

from modeling_core.contracts.canonical_json import sha256_json
from modeling_core.contracts.capability import (
    CapabilityDescriptor,
    SchemaReference,
    SupportedCapabilityRange,
    ValidatorDescriptor,
)
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.schema_catalog import SchemaCatalog


_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_CAPABILITY_ID = (
    "https://schemas.math-modeling-mcp.local/common/0.1.0/"
    "modeling-capability.schema.json"
)
_VALIDATOR_ID = (
    "https://schemas.math-modeling-mcp.local/common/0.1.0/"
    "modeling-validator.schema.json"
)


def schema(name: str) -> JsonObject:
    return {
        "$schema": _DRAFT,
        "$id": f"https://modeling.local/schemas/{name}/0.1.0",
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    }


def schema_ref(name: str) -> SchemaReference:
    value = schema(name)
    return SchemaReference(
        schema_version=f"{name}/0.1.0",
        schema=value,
        schema_hash=sha256_json(value),
    )


def capability_instance() -> JsonObject:
    descriptor = CapabilityDescriptor(
        kind="built_in",
        capability_api_version="modeling-capability/0.1.0",
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        implementation_id="builtin.numerical.root_finding.bisection",
        implementation_version="0.1.0",
        title="Bisection root finding",
        summary="Find a bracketed scalar root.",
        category="numerical",
        tags=("deterministic", "root-finding"),
        determinism="deterministic",
        randomness="not_used",
        input_schema=schema_ref("root-finding.input"),
        canonical_input_schema=schema_ref("root-finding.canonical-input"),
        success_schema=schema_ref("root-finding.success"),
        failure_schema=schema_ref("root-finding.failure"),
        default_limits={
            "timeout_ms": 10_000,
            "max_iterations": 100,
            "max_evaluations": 20_000,
        },
        maximum_limits={
            "timeout_ms": 60_000,
            "max_iterations": 10_000,
            "max_evaluations": 20_000,
        },
        artifact_roles=(),
        validators=(),
        context_ref="modeling://capabilities/numerical.root_finding/context",
    )
    return descriptor.model_dump(mode="json")


def validator_instance() -> JsonObject:
    descriptor = ValidatorDescriptor(
        kind="built_in",
        validator_id="numerical.root_finding.residual",
        supported_capabilities=(
            SupportedCapabilityRange(
                capability_id="numerical.root_finding",
                minimum_contract_version="0.1.0",
                maximum_contract_version="0.1.0",
            ),
        ),
        implementation_id="builtin.numerical.root_finding.residual",
        implementation_version="0.1.0",
        policy_version="0.1.0",
        policy_schema=schema_ref("root-finding.policy"),
        report_schema=schema_ref("root-finding.report"),
        summary="Independently recompute the residual.",
    )
    return descriptor.model_dump(mode="json")


@pytest.mark.parametrize(
    ("schema_id", "instance"),
    [
        (_CAPABILITY_ID, capability_instance()),
        (_VALIDATOR_ID, validator_instance()),
    ],
)
def test_packaged_descriptor_schema_is_draft_2020_12_and_strict(
    schema_id: str, instance: JsonObject
) -> None:
    catalog = SchemaCatalog.load_packaged("0.1.0")
    packaged = catalog.common_schemas[schema_id]

    assert packaged["$schema"] == _DRAFT
    assert packaged["type"] == "object"
    assert packaged["additionalProperties"] is False
    Draft202012Validator.check_schema(packaged)
    validator = Draft202012Validator(packaged)
    validator.validate(instance)

    invalid = dict(instance)
    invalid["unexpected"] = True
    assert list(validator.iter_errors(invalid))


def test_descriptor_schemas_reject_non_object_references_and_non_m1a_artifacts() -> None:
    catalog = SchemaCatalog.load_packaged("0.1.0")
    capability_schema = catalog.common_schemas[_CAPABILITY_ID]
    instance = capability_instance()

    input_schema = dict(instance["input_schema"])  # type: ignore[arg-type]
    input_schema["schema"] = {
        "$schema": _DRAFT,
        "$id": "https://modeling.local/schemas/not-an-object/0.1.0",
        "type": "array",
    }
    instance["input_schema"] = input_schema
    instance["artifact_roles"] = ["result"]

    errors = list(Draft202012Validator(capability_schema).iter_errors(instance))
    assert {tuple(error.path) for error in errors} >= {
        ("artifact_roles",),
        ("input_schema", "schema", "type"),
    }


def test_root_finding_contract_corpus_matches_the_packaged_strict_schemas() -> None:
    package_root = files("modeling_capabilities.root_finding")
    schema_root = package_root.joinpath("schemas", "0.1.0")
    schemas = {
        "input": cast(
            JsonObject,
            json.loads(
                schema_root.joinpath("input.schema.json").read_text(
                    encoding="utf-8"
                )
            ),
        ),
        "canonical-input": cast(
            JsonObject,
            json.loads(
                schema_root.joinpath("canonical-input.schema.json").read_text(
                    encoding="utf-8"
                )
            ),
        ),
    }
    corpus_path = (
        Path(__file__).parent / "corpus" / "root-finding" / "0.1.0.json"
    )
    corpus = cast(
        list[dict[str, object]],
        json.loads(corpus_path.read_text(encoding="utf-8")),
    )

    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False

    for vector in corpus:
        validator = Draft202012Validator(schemas[cast(str, vector["kind"])])
        errors = list(validator.iter_errors(vector["instance"]))
        assert bool(errors) is not cast(bool, vector["valid"]), vector["label"]
