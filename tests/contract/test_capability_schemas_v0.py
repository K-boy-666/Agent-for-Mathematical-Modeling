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
from modeling_core.contracts.tools import (
    FailureResultPayload,
    NumericalFailureData,
    ResultSuccessData,
    SuccessResultPayload,
)


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
        "success-data": cast(
            JsonObject,
            json.loads(
                schema_root.joinpath("success-data.schema.json").read_text(
                    encoding="utf-8"
                )
            ),
        ),
        "failure-data": cast(
            JsonObject,
            json.loads(
                schema_root.joinpath("failure-data.schema.json").read_text(
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
        if vector["kind"] not in {"input", "canonical-input"}:
            continue
        validator = Draft202012Validator(schemas[cast(str, vector["kind"])])
        errors = list(validator.iter_errors(vector["instance"]))
        assert bool(errors) is not cast(bool, vector["valid"]), vector["label"]


def test_root_finding_result_data_and_common_result_schemas_are_strict() -> None:
    capability_root = files("modeling_capabilities.root_finding").joinpath(
        "schemas", "0.1.0"
    )
    core_root = files("modeling_core.contracts").joinpath(
        "schemas", "common", "0.1.0"
    )
    success_schema = cast(
        JsonObject,
        json.loads(
            capability_root.joinpath("success-data.schema.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    failure_schema = cast(
        JsonObject,
        json.loads(
            capability_root.joinpath("failure-data.schema.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    result_schema = cast(
        JsonObject,
        json.loads(
            core_root.joinpath("modeling-result.schema.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    success_data: JsonObject = {
        "root": 1.4142135623730951,
        "function_value": 4.440892098500626e-16,
        "iterations": 38,
        "evaluations": 40,
        "termination_reason": "residual_tolerance",
    }
    failure_data: JsonObject = {
        "failure_code": "no_sign_change",
        "iterations": 0,
        "evaluations": 2,
    }
    success_payload: JsonObject = {
        "result_schema_version": "modeling-result/0.1.0",
        "capability_id": "numerical.root_finding",
        "contract_version": "0.1.0",
        "result_kind": "success",
        "data": success_data,
    }
    failure_payload: JsonObject = {
        "result_schema_version": "modeling-result/0.1.0",
        "capability_id": "numerical.root_finding",
        "contract_version": "0.1.0",
        "result_kind": "numerical_failure",
        "data": failure_data,
    }

    for schema_value in (success_schema, failure_schema, result_schema):
        Draft202012Validator.check_schema(schema_value)
        assert schema_value["type"] == "object"
        assert schema_value["additionalProperties"] is False
    Draft202012Validator(success_schema).validate(success_data)
    Draft202012Validator(failure_schema).validate(failure_data)
    result_validator = Draft202012Validator(result_schema)
    result_validator.validate(success_payload)
    result_validator.validate(failure_payload)

    invalid_success = dict(success_data)
    invalid_success["unexpected"] = True
    assert list(
        Draft202012Validator(success_schema).iter_errors(invalid_success)
    )
    invalid_payload = dict(success_payload)
    invalid_payload["unexpected"] = True
    assert list(result_validator.iter_errors(invalid_payload))


@pytest.mark.parametrize(
    "termination_reason",
    ["endpoint_root", "residual_tolerance", "interval_tolerance"],
)
def test_success_schema_accepts_every_declared_termination_reason(
    termination_reason: str,
) -> None:
    schema_root = files("modeling_capabilities.root_finding").joinpath(
        "schemas", "0.1.0"
    )
    success_schema = json.loads(
        schema_root.joinpath("success-data.schema.json").read_text(
            encoding="utf-8"
        )
    )
    result_schema = json.loads(
        files("modeling_core.contracts")
        .joinpath(
            "schemas",
            "common",
            "0.1.0",
            "modeling-result.schema.json",
        )
        .read_text(encoding="utf-8")
    )
    payload = SuccessResultPayload(
        result_schema_version="modeling-result/0.1.0",
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        result_kind="success",
        data=ResultSuccessData(
            root=1.0,
            function_value=0.0,
            iterations=1,
            evaluations=3,
            termination_reason=termination_reason,
        ),
    ).model_dump(mode="json")

    Draft202012Validator(success_schema).validate(payload["data"])
    Draft202012Validator(result_schema).validate(payload)


@pytest.mark.parametrize(
    "failure_code",
    [
        "no_sign_change",
        "non_convergence",
        "domain_error",
        "non_finite_evaluation",
    ],
)
def test_failure_schema_accepts_every_declared_failure_code(
    failure_code: str,
) -> None:
    schema_root = files("modeling_capabilities.root_finding").joinpath(
        "schemas", "0.1.0"
    )
    failure_schema = json.loads(
        schema_root.joinpath("failure-data.schema.json").read_text(
            encoding="utf-8"
        )
    )
    result_schema = json.loads(
        files("modeling_core.contracts")
        .joinpath(
            "schemas",
            "common",
            "0.1.0",
            "modeling-result.schema.json",
        )
        .read_text(encoding="utf-8")
    )
    payload = FailureResultPayload(
        result_schema_version="modeling-result/0.1.0",
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        result_kind="numerical_failure",
        data=NumericalFailureData(
            failure_code=failure_code,
            iterations=0,
            evaluations=2,
        ),
    ).model_dump(mode="json")

    Draft202012Validator(failure_schema).validate(payload["data"])
    Draft202012Validator(result_schema).validate(payload)


@pytest.mark.parametrize(
    ("schema_name", "invalid_data"),
    [
        (
            "success-data.schema.json",
            {
                "root": 1.0,
                "function_value": 0.0,
                "iterations": 1,
                "evaluations": 3,
                "termination_reason": "unknown",
            },
        ),
        (
            "failure-data.schema.json",
            {
                "failure_code": "unknown",
                "iterations": 0,
                "evaluations": 2,
            },
        ),
    ],
)
def test_result_data_schemas_reject_unknown_enums(
    schema_name: str, invalid_data: JsonObject
) -> None:
    schema_root = files("modeling_capabilities.root_finding").joinpath(
        "schemas", "0.1.0"
    )
    packaged_schema = json.loads(
        schema_root.joinpath(schema_name).read_text(encoding="utf-8")
    )
    result_schema = json.loads(
        files("modeling_core.contracts")
        .joinpath(
            "schemas",
            "common",
            "0.1.0",
            "modeling-result.schema.json",
        )
        .read_text(encoding="utf-8")
    )

    assert list(
        Draft202012Validator(packaged_schema).iter_errors(invalid_data)
    )
    result_kind = (
        "success"
        if schema_name.startswith("success")
        else "numerical_failure"
    )
    invalid_payload: JsonObject = {
        "result_schema_version": "modeling-result/0.1.0",
        "capability_id": "numerical.root_finding",
        "contract_version": "0.1.0",
        "result_kind": result_kind,
        "data": invalid_data,
    }
    assert list(
        Draft202012Validator(result_schema).iter_errors(invalid_payload)
    )
