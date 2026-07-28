from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace
from typing import cast

import pytest
from pydantic import ValidationError

from modeling_core.contracts.canonical_json import sha256_json
from modeling_core.contracts.capability import (
    BuiltInCapability,
    CancellationSignal,
    CapabilityDescriptor,
    CapabilityValidator,
    CanonicalInputRecord,
    ExecutionContext,
    ExecutionOutcome,
    ResultSnapshotView,
    SchemaReference,
    SupportedCapabilityRange,
    ValidationContext,
    ValidationReport,
    ValidatorDescriptor,
)
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.tools import PolicyContract, ValidatorSummary
from modeling_core.contracts.versions import VersionSet
from modeling_core.registry import CapabilityRegistry, RegistryError


_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_ROOT_KEY = ("numerical.root_finding", "0.1.0")


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


def capability_descriptor(
    *,
    capability_id: str = _ROOT_KEY[0],
    contract_version: str = _ROOT_KEY[1],
    api_version: str = "modeling-capability/0.1.0",
    implementation_id: str = "builtin.numerical.root_finding.bisection",
    implementation_version: str = "0.1.0",
    artifact_roles: tuple[str, ...] = (),
    validators: tuple[ValidatorSummary, ...] = (),
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        kind="built_in",
        capability_api_version=api_version,
        capability_id=capability_id,
        contract_version=contract_version,
        implementation_id=implementation_id,
        implementation_version=implementation_version,
        title="Bisection root finding",
        summary="Find a bracketed scalar root.",
        category="numerical",
        tags=("deterministic", "root-finding"),
        determinism="deterministic",
        randomness="not_used",
        input_schema=schema_ref(f"{capability_id}.input"),
        canonical_input_schema=schema_ref(f"{capability_id}.canonical-input"),
        success_schema=schema_ref(f"{capability_id}.success"),
        failure_schema=schema_ref(f"{capability_id}.failure"),
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
        artifact_roles=artifact_roles,
        validators=validators,
        context_ref="modeling://capabilities/numerical.root_finding/context",
    )


def validator_descriptor(
    *,
    validator_id: str = "numerical.root_finding.residual",
    policy_version: str = "0.1.0",
    implementation_id: str = "builtin.numerical.root_finding.residual",
    implementation_version: str = "0.1.0",
    minimum: str = "0.1.0",
    maximum: str = "0.1.0",
) -> ValidatorDescriptor:
    return ValidatorDescriptor(
        kind="built_in",
        validator_id=validator_id,
        supported_capabilities=(
            SupportedCapabilityRange(
                capability_id="numerical.root_finding",
                minimum_contract_version=minimum,
                maximum_contract_version=maximum,
            ),
        ),
        implementation_id=implementation_id,
        implementation_version=implementation_version,
        policy_version=policy_version,
        policy_schema=schema_ref(f"{validator_id}.policy"),
        report_schema=schema_ref(f"{validator_id}.report"),
        summary="Independently recompute the residual.",
    )


def advertised_validator(descriptor: ValidatorDescriptor) -> ValidatorSummary:
    return ValidatorSummary(
        validator_id=descriptor.validator_id,
        policies=(
            PolicyContract(
                policy_version=descriptor.policy_version,
                policy_schema=descriptor.policy_schema.schema,
                policy_schema_hash=descriptor.policy_schema.schema_hash,
            ),
        ),
        report_schema_version=descriptor.report_schema.schema_version,
        report_schema=descriptor.report_schema.schema,
        report_schema_hash=descriptor.report_schema.schema_hash,
        summary=descriptor.summary,
    )


@dataclass(frozen=True)
class FakeCapability:
    descriptor: CapabilityDescriptor

    def normalize_and_validate(self, raw_payload: JsonObject) -> CanonicalInputRecord:
        raise NotImplementedError

    def execute(
        self, canonical_input: CanonicalInputRecord, context: ExecutionContext
    ) -> ExecutionOutcome:
        raise NotImplementedError


@dataclass(frozen=True)
class FakeValidator:
    descriptor: ValidatorDescriptor

    def validate(
        self,
        canonical_input: CanonicalInputRecord,
        result_snapshot: ResultSnapshotView,
        policy: JsonObject,
        context: ValidationContext,
    ) -> ValidationReport:
        raise NotImplementedError


@dataclass
class MutableCapability:
    current_descriptor: CapabilityDescriptor

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return self.current_descriptor

    def normalize_and_validate(self, raw_payload: JsonObject) -> CanonicalInputRecord:
        raise NotImplementedError

    def execute(
        self, canonical_input: CanonicalInputRecord, context: ExecutionContext
    ) -> ExecutionOutcome:
        raise NotImplementedError


@dataclass
class MutableValidator:
    current_descriptor: ValidatorDescriptor

    @property
    def descriptor(self) -> ValidatorDescriptor:
        return self.current_descriptor

    def validate(
        self,
        canonical_input: CanonicalInputRecord,
        result_snapshot: ResultSnapshotView,
        policy: JsonObject,
        context: ValidationContext,
    ) -> ValidationReport:
        raise NotImplementedError


def registry() -> CapabilityRegistry:
    return CapabilityRegistry(VersionSet.m1a())


def assert_registry_error(
    captured: pytest.ExceptionInfo[RegistryError],
    code: str,
    detail_name: str,
    detail_value: object,
) -> None:
    assert captured.value.code == code
    assert captured.value.retryable is False
    assert captured.value.details[detail_name] == detail_value


def test_protocols_accept_structural_implementations() -> None:
    capability = FakeCapability(capability_descriptor())
    validator = FakeValidator(validator_descriptor())

    assert isinstance(capability, BuiltInCapability)
    assert isinstance(validator, CapabilityValidator)


def test_capability_and_compatible_validator_register_before_seal() -> None:
    catalog = registry()
    validator = FakeValidator(validator_descriptor())
    capability = FakeCapability(
        capability_descriptor(
            validators=(advertised_validator(validator.descriptor),)
        )
    )

    catalog.register_capability(capability)
    catalog.register_validator(validator)
    summary = catalog.seal(frozenset({_ROOT_KEY}))

    assert summary.sealed is True
    assert summary.capability_count == 1
    assert catalog.resolve(*_ROOT_KEY) is capability
    assert (
        catalog.resolve_validator(
            "numerical.root_finding.residual",
            *_ROOT_KEY,
            "0.1.0",
        )
        is validator
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            FakeCapability(capability_descriptor()),
            FakeCapability(capability_descriptor()),
        ),
        (
            FakeValidator(validator_descriptor()),
            FakeValidator(validator_descriptor()),
        ),
        (
            FakeCapability(capability_descriptor()),
            FakeCapability(
                capability_descriptor(
                    capability_id="numerical.other",
                    implementation_id="builtin.numerical.root_finding.bisection",
                )
            ),
        ),
        (
            FakeValidator(validator_descriptor()),
            FakeValidator(
                validator_descriptor(
                    validator_id="numerical.root_finding.second_check",
                    implementation_id="builtin.numerical.root_finding.residual",
                )
            ),
        ),
    ],
    ids=[
        "capability-key",
        "validator-policy-key",
        "capability-implementation-identity",
        "validator-implementation-identity",
    ],
)
def test_duplicate_registration_is_a_strict_conflict(
    first: FakeCapability | FakeValidator,
    second: FakeCapability | FakeValidator,
) -> None:
    catalog = registry()
    if isinstance(first, FakeCapability):
        catalog.register_capability(first)
        register = catalog.register_capability
        duplicate = cast(BuiltInCapability, second)
    else:
        catalog.register_validator(first)
        register = catalog.register_validator
        duplicate = cast(CapabilityValidator, second)

    with pytest.raises(RegistryError) as captured:
        register(duplicate)

    assert_registry_error(
        captured, "CONFLICT", "conflict_type", "duplicate_registration"
    )


def test_incompatible_capability_api_is_unsupported() -> None:
    catalog = registry()

    with pytest.raises(RegistryError) as captured:
        catalog.register_capability(
            FakeCapability(
                capability_descriptor(api_version="modeling-capability/9.0.0")
            )
        )

    assert_registry_error(
        captured,
        "UNSUPPORTED_VERSION",
        "requested_version",
        "modeling-capability/9.0.0",
    )


def test_incompatible_validator_contract_range_is_unsupported() -> None:
    catalog = registry()
    validator = FakeValidator(
        validator_descriptor(minimum="0.2.0", maximum="0.3.0")
    )
    catalog.register_capability(
        FakeCapability(
            capability_descriptor(
                validators=(advertised_validator(validator.descriptor),)
            )
        )
    )
    catalog.register_validator(validator)

    with pytest.raises(RegistryError) as captured:
        catalog.seal(frozenset({_ROOT_KEY}))

    assert_registry_error(
        captured, "UNSUPPORTED_VERSION", "requested_version", "0.1.0"
    )


def test_every_declared_validator_contract_range_must_be_compatible() -> None:
    descriptor = validator_descriptor()
    descriptor = descriptor.model_copy(
        update={
            "supported_capabilities": (
                *descriptor.supported_capabilities,
                SupportedCapabilityRange(
                    capability_id="numerical.unregistered",
                    minimum_contract_version="0.1.0",
                    maximum_contract_version="0.1.0",
                ),
            )
        }
    )
    catalog = registry()
    catalog.register_capability(
        FakeCapability(
            capability_descriptor(validators=(advertised_validator(descriptor),))
        )
    )
    catalog.register_validator(FakeValidator(descriptor))

    with pytest.raises(RegistryError) as captured:
        catalog.seal(frozenset({_ROOT_KEY}))

    assert_registry_error(
        captured, "UNSUPPORTED_VERSION", "requested_version", "<missing>"
    )


def test_required_root_finding_capability_is_always_required() -> None:
    with pytest.raises(RegistryError) as captured:
        registry().seal(frozenset())

    assert_registry_error(
        captured,
        "PRECONDITION_FAILED",
        "condition",
        "missing_required_capability",
    )


@pytest.mark.parametrize("breakage", ["invalid-draft", "non-object", "wrong-hash"])
def test_seal_validates_referenced_draft_2020_12_schemas_and_hashes(
    breakage: str,
) -> None:
    descriptor = capability_descriptor()
    original = descriptor.input_schema
    broken_schema = dict(original.schema)
    broken_hash = original.schema_hash
    if breakage == "invalid-draft":
        broken_schema["type"] = "not-a-json-schema-type"
        broken_hash = sha256_json(broken_schema)
    elif breakage == "non-object":
        broken_schema["type"] = "array"
        broken_hash = sha256_json(broken_schema)
    else:
        broken_hash = "sha256:" + "0" * 64
    broken_ref = SchemaReference(
        schema_version=original.schema_version,
        schema=broken_schema,
        schema_hash=broken_hash,
    )
    descriptor = descriptor.model_copy(update={"input_schema": broken_ref})
    catalog = registry()
    catalog.register_capability(FakeCapability(descriptor))

    with pytest.raises(RegistryError) as captured:
        catalog.seal(frozenset({_ROOT_KEY}))

    assert captured.value.code == "INTEGRITY_FAILURE"


def test_seal_validates_schema_hashes_inside_capability_validator_summaries() -> None:
    policy = schema("residual.policy")
    report = schema("residual.report")
    summary = ValidatorSummary(
        validator_id="numerical.root_finding.residual",
        policies=(
            PolicyContract(
                policy_version="0.1.0",
                policy_schema=policy,
                policy_schema_hash="sha256:" + "0" * 64,
            ),
        ),
        report_schema_version="modeling-validation-report/0.1.0",
        report_schema=report,
        report_schema_hash=sha256_json(report),
        summary="Independent residual validation.",
    )
    catalog = registry()
    catalog.register_capability(
        FakeCapability(capability_descriptor(validators=(summary,)))
    )

    with pytest.raises(RegistryError) as captured:
        catalog.seal(frozenset({_ROOT_KEY}))

    assert captured.value.code == "INTEGRITY_FAILURE"


def test_seal_sorts_lists_and_exact_resolve_does_not_choose_latest() -> None:
    catalog = registry()
    root = FakeCapability(capability_descriptor())
    later = FakeCapability(
        capability_descriptor(
            capability_id="numerical.zeta",
            contract_version="0.2.0",
            implementation_id="builtin.numerical.zeta",
            implementation_version="0.2.0",
        )
    )
    earlier = FakeCapability(
        capability_descriptor(
            capability_id="algebra.alpha",
            implementation_id="builtin.algebra.alpha",
        )
    )
    for capability in (later, root, earlier):
        catalog.register_capability(capability)
    catalog.seal(frozenset({_ROOT_KEY}))

    assert [
        (item.capability_id, item.contract_version)
        for item in catalog.list_summaries(None, None)
    ] == [
        ("algebra.alpha", "0.1.0"),
        ("numerical.root_finding", "0.1.0"),
        ("numerical.zeta", "0.2.0"),
    ]
    with pytest.raises(RegistryError) as captured:
        catalog.resolve("numerical.root_finding", "0.2.0")
    assert captured.value.code == "NOT_FOUND"


def test_fingerprint_is_the_ordered_versioned_hash_projection() -> None:
    validator = validator_descriptor()
    validator_summary = advertised_validator(validator)
    descriptor = capability_descriptor(validators=(validator_summary,))
    catalog = registry()
    catalog.register_validator(FakeValidator(validator))
    catalog.register_capability(FakeCapability(descriptor))

    summary = catalog.seal(frozenset({_ROOT_KEY}))

    expected = sha256_json(
        {
            "capabilities": [
                {
                    "capability_api_version": descriptor.capability_api_version,
                    "capability_id": descriptor.capability_id,
                    "contract_version": descriptor.contract_version,
                    "implementation_id": descriptor.implementation_id,
                    "implementation_version": descriptor.implementation_version,
                    "schemas": {
                        "canonical_input": {
                            "schema_hash": descriptor.canonical_input_schema.schema_hash,
                            "schema_version": descriptor.canonical_input_schema.schema_version,
                        },
                        "failure": {
                            "schema_hash": descriptor.failure_schema.schema_hash,
                            "schema_version": descriptor.failure_schema.schema_version,
                        },
                        "input": {
                            "schema_hash": descriptor.input_schema.schema_hash,
                            "schema_version": descriptor.input_schema.schema_version,
                        },
                        "success": {
                            "schema_hash": descriptor.success_schema.schema_hash,
                            "schema_version": descriptor.success_schema.schema_version,
                        },
                    },
                    "validators": [
                        {
                            "policies": [
                                {
                                    "policy_schema_hash": (
                                        validator_summary.policies[
                                            0
                                        ].policy_schema_hash
                                    ),
                                    "policy_version": "0.1.0",
                                }
                            ],
                            "report_schema_hash": (
                                validator_summary.report_schema_hash
                            ),
                            "report_schema_version": (
                                validator_summary.report_schema_version
                            ),
                            "validator_id": validator_summary.validator_id,
                        }
                    ],
                }
            ],
            "validators": [
                {
                    "implementation_id": validator.implementation_id,
                    "implementation_version": validator.implementation_version,
                    "policy": {
                        "schema_hash": validator.policy_schema.schema_hash,
                        "schema_version": validator.policy_schema.schema_version,
                        "version": validator.policy_version,
                    },
                    "report": {
                        "schema_hash": validator.report_schema.schema_hash,
                        "schema_version": validator.report_schema.schema_version,
                    },
                    "supported_capabilities": [
                        {
                            "capability_id": "numerical.root_finding",
                            "maximum_contract_version": "0.1.0",
                            "minimum_contract_version": "0.1.0",
                        }
                    ],
                    "validator_id": validator.validator_id,
                }
            ],
        }
    )
    assert summary.fingerprint == expected


def test_fingerprint_includes_capability_validator_summary_versions_and_hashes() -> None:
    matching_descriptor = validator_descriptor()
    validator_summary = advertised_validator(matching_descriptor)
    without_summary = registry()
    without_summary.register_capability(FakeCapability(capability_descriptor()))
    first = without_summary.seal(frozenset({_ROOT_KEY}))
    with_summary = registry()
    matching_validator = FakeValidator(matching_descriptor)
    with_summary.register_capability(
        FakeCapability(capability_descriptor(validators=(validator_summary,)))
    )
    with_summary.register_validator(matching_validator)
    second = with_summary.seal(frozenset({_ROOT_KEY}))

    assert first.fingerprint != second.fingerprint


def test_registration_is_rejected_after_seal() -> None:
    catalog = registry()
    catalog.register_capability(FakeCapability(capability_descriptor()))
    catalog.seal(frozenset({_ROOT_KEY}))

    with pytest.raises(RegistryError) as captured:
        catalog.register_validator(FakeValidator(validator_descriptor()))

    assert_registry_error(
        captured, "CONFLICT", "conflict_type", "duplicate_registration"
    )


def test_m1a_descriptor_and_contexts_are_strictly_immutable() -> None:
    descriptor = capability_descriptor()

    assert descriptor.artifact_roles == ()
    with pytest.raises(ValidationError):
        descriptor.title = "changed"
    with pytest.raises(ValidationError):
        capability_descriptor(artifact_roles=("result",))

    @dataclass(frozen=True)
    class NeverCancelled:
        def is_cancelled(self) -> bool:
            return False

    @dataclass(frozen=True)
    class TestClock:
        def utc_now(self) -> object:
            raise NotImplementedError

        def monotonic(self) -> float:
            return 1.0

    context = ExecutionContext(
        attempt_id="123e4567-e89b-42d3-a456-426614174000",
        randomness="not_used",
        seed=None,
        deadline=2.0,
        clock=TestClock(),
        cancellation=cast(CancellationSignal, NeverCancelled()),
    )
    with pytest.raises(FrozenInstanceError):
        replace(context, deadline=3.0).deadline = 4.0


def test_descriptor_nested_schemas_and_validator_summaries_are_deeply_immutable() -> None:
    policy = schema("residual.policy")
    report = schema("residual.report")
    summary = ValidatorSummary(
        validator_id="numerical.root_finding.residual",
        policies=(
            PolicyContract(
                policy_version="0.1.0",
                policy_schema=policy,
                policy_schema_hash=sha256_json(policy),
            ),
        ),
        report_schema_version="modeling-validation-report/0.1.0",
        report_schema=report,
        report_schema_hash=sha256_json(report),
        summary="Independent residual validation.",
    )
    descriptor = capability_descriptor(validators=(summary,))
    input_view = descriptor.input_schema.schema
    policy_view = descriptor.validators[0].policies[0].policy_schema
    report_view = descriptor.validators[0].report_schema

    input_view["title"] = "mutated"
    policy_view["title"] = "mutated"
    report_view["title"] = "mutated"

    assert "title" not in descriptor.input_schema.schema
    assert "title" not in descriptor.validators[0].policies[0].policy_schema
    assert "title" not in descriptor.validators[0].report_schema


def test_registry_snapshots_descriptors_at_registration() -> None:
    original_validator = validator_descriptor()
    original_capability = capability_descriptor(
        validators=(advertised_validator(original_validator),)
    )
    capability = MutableCapability(original_capability)
    validator = MutableValidator(original_validator)
    catalog = registry()
    catalog.register_capability(capability)
    catalog.register_validator(validator)

    capability.current_descriptor = capability_descriptor(
        capability_id="numerical.changed",
        implementation_id="builtin.numerical.changed",
    )
    validator.current_descriptor = validator_descriptor(
        validator_id="numerical.changed.validator",
        implementation_id="builtin.numerical.changed.validator",
        minimum="0.2.0",
        maximum="0.3.0",
    )
    sealed = catalog.seal(frozenset({_ROOT_KEY}))
    listed = catalog.list_summaries(None, None)

    capability.current_descriptor = capability_descriptor(
        capability_id="numerical.changed_again",
        implementation_id="builtin.numerical.changed_again",
    )
    validator.current_descriptor = validator_descriptor(
        validator_id="numerical.changed_again.validator",
        implementation_id="builtin.numerical.changed_again.validator",
    )

    assert catalog.seal(frozenset({_ROOT_KEY})).fingerprint == sealed.fingerprint
    assert [(item.capability_id, item.title) for item in listed] == [
        ("numerical.root_finding", "Bisection root finding")
    ]
    assert [
        (item.capability_id, item.title)
        for item in catalog.list_summaries(None, None)
    ] == [("numerical.root_finding", "Bisection root finding")]
    assert catalog.resolve(*_ROOT_KEY) is capability
    assert (
        catalog.resolve_validator(
            original_validator.validator_id,
            *_ROOT_KEY,
            original_validator.policy_version,
        )
        is validator
    )


def test_advertised_validator_requires_a_registered_match() -> None:
    descriptor = validator_descriptor()
    catalog = registry()
    catalog.register_capability(
        FakeCapability(
            capability_descriptor(validators=(advertised_validator(descriptor),))
        )
    )

    with pytest.raises(RegistryError) as captured:
        catalog.seal(frozenset({_ROOT_KEY}))

    assert captured.value.code == "INTEGRITY_FAILURE"


def test_registered_validator_must_be_advertised_by_supported_capability() -> None:
    catalog = registry()
    catalog.register_capability(FakeCapability(capability_descriptor()))
    catalog.register_validator(FakeValidator(validator_descriptor()))

    with pytest.raises(RegistryError) as captured:
        catalog.seal(frozenset({_ROOT_KEY}))

    assert captured.value.code == "INTEGRITY_FAILURE"


@pytest.mark.parametrize(
    "mismatch",
    ["policy-version", "policy-hash", "report-version", "report-hash"],
)
def test_advertised_validator_contract_must_exactly_match_registration(
    mismatch: str,
) -> None:
    descriptor = validator_descriptor()
    summary = advertised_validator(descriptor)
    if mismatch == "policy-version":
        summary = summary.model_copy(
            update={
                "policies": (
                    summary.policies[0].model_copy(
                        update={"policy_version": "0.2.0"}
                    ),
                )
            }
        )
    elif mismatch == "policy-hash":
        different_policy = schema("different.policy")
        summary = summary.model_copy(
            update={
                "policies": (
                    PolicyContract(
                        policy_version="0.1.0",
                        policy_schema=different_policy,
                        policy_schema_hash=sha256_json(different_policy),
                    ),
                )
            }
        )
    elif mismatch == "report-version":
        summary = summary.model_copy(
            update={"report_schema_version": "different-report/0.1.0"}
        )
    else:
        different_report = schema("different.report")
        summary = summary.model_copy(
            update={
                "report_schema": different_report,
                "report_schema_hash": sha256_json(different_report),
            }
        )
    catalog = registry()
    catalog.register_capability(
        FakeCapability(capability_descriptor(validators=(summary,)))
    )
    catalog.register_validator(FakeValidator(descriptor))

    with pytest.raises(RegistryError) as captured:
        catalog.seal(frozenset({_ROOT_KEY}))

    assert captured.value.code == "INTEGRITY_FAILURE"


@pytest.mark.parametrize("duplicate", ["summary", "policy"])
def test_duplicate_advertised_validator_mapping_is_a_conflict(
    duplicate: str,
) -> None:
    descriptor = validator_descriptor()
    summary = advertised_validator(descriptor)
    if duplicate == "summary":
        summaries = (summary, summary)
    else:
        summary = summary.model_copy(
            update={"policies": (summary.policies[0], summary.policies[0])}
        )
        summaries = (summary,)
    catalog = registry()
    catalog.register_capability(
        FakeCapability(capability_descriptor(validators=summaries))
    )
    catalog.register_validator(FakeValidator(descriptor))

    with pytest.raises(RegistryError) as captured:
        catalog.seal(frozenset({_ROOT_KEY}))

    assert_registry_error(
        captured, "CONFLICT", "conflict_type", "duplicate_registration"
    )


def test_overlapping_registered_ranges_are_an_ambiguous_conflict() -> None:
    descriptor = validator_descriptor().model_copy(
        update={
            "supported_capabilities": (
                SupportedCapabilityRange(
                    capability_id="numerical.root_finding",
                    minimum_contract_version="0.1.0",
                    maximum_contract_version="0.1.0",
                ),
                SupportedCapabilityRange(
                    capability_id="numerical.root_finding",
                    minimum_contract_version="0.1.0",
                    maximum_contract_version="0.2.0",
                ),
            )
        }
    )
    catalog = registry()
    catalog.register_capability(
        FakeCapability(
            capability_descriptor(validators=(advertised_validator(descriptor),))
        )
    )
    catalog.register_validator(FakeValidator(descriptor))

    with pytest.raises(RegistryError) as captured:
        catalog.seal(frozenset({_ROOT_KEY}))

    assert_registry_error(
        captured, "CONFLICT", "conflict_type", "duplicate_registration"
    )
