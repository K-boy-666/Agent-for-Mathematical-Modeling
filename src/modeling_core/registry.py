"""Sealed deterministic registry for explicitly composed Built-in Capabilities."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import NoReturn

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import (  # type: ignore[import-untyped]
    SchemaError,
    ValidationError,
)

from modeling_core.contracts.canonical_json import sha256_json
from modeling_core.contracts.capability import (
    BuiltInCapability,
    CapabilityDescriptor,
    CapabilityKey,
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
    ValidatorKey,
)
from modeling_core.contracts.common import JsonObject, RegistrySummary
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.tools import CapabilitySummary, ValidatorSummary
from modeling_core.contracts.versions import VersionSet

_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_REQUIRED_M1A = frozenset({("numerical.root_finding", "0.1.0")})
_CAPABILITY_DESCRIPTOR_SCHEMA = (
    "https://schemas.math-modeling-mcp.local/common/0.1.0/"
    "modeling-capability.schema.json"
)
_VALIDATOR_DESCRIPTOR_SCHEMA = (
    "https://schemas.math-modeling-mcp.local/common/0.1.0/"
    "modeling-validator.schema.json"
)


class RegistryError(RuntimeError):
    """Stable fail-closed registration error for the composition boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object],
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = False
        self.details = dict(details)


def _duplicate(subject: str) -> NoReturn:
    raise RegistryError(
        "CONFLICT",
        f"duplicate or sealed Built-in registration: {subject}",
        details={
            "conflict_type": "duplicate_registration",
            "existing_resource_id": subject,
        },
    )


def _unsupported(
    subject: str, requested: str, supported: Iterable[str]
) -> NoReturn:
    raise RegistryError(
        "UNSUPPORTED_VERSION",
        f"unsupported {subject} version: {requested}",
        details={
            "subject": subject,
            "requested_version": requested,
            "supported_versions": tuple(sorted(supported)),
        },
    )


def _integrity(subject: str, message: str) -> NoReturn:
    raise RegistryError(
        "INTEGRITY_FAILURE",
        message,
        details={"subject": subject},
    )


def _validate_schema_reference(subject: str, reference: SchemaReference) -> None:
    schema = reference.schema
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise RegistryError(
            "INTEGRITY_FAILURE",
            f"{subject} is not a valid Draft 2020-12 Schema",
            details={"subject": subject},
        ) from error
    if schema.get("$schema") != _DRAFT_2020_12:
        _integrity(subject, f"{subject} does not declare Draft 2020-12")
    if schema.get("type") != "object":
        _integrity(subject, f"{subject} root type must be object")
    if schema.get("additionalProperties") is not False:
        _integrity(subject, f"{subject} root must reject additional properties")
    observed = sha256_json(schema)
    if observed != reference.schema_hash:
        raise RegistryError(
            "INTEGRITY_FAILURE",
            f"{subject} declared hash does not match its Schema",
            details={
                "subject": subject,
                "expected_hash": reference.schema_hash,
                "observed_hash": observed,
            },
        )


def _validate_descriptor(
    descriptor: CapabilityDescriptor | ValidatorDescriptor,
    packaged_schema: JsonObject,
) -> None:
    try:
        Draft202012Validator(packaged_schema).validate(
            descriptor.model_dump(mode="json")
        )
    except ValidationError as error:
        _integrity("registry_descriptor", f"invalid registry descriptor: {error.message}")
    references: list[tuple[str, SchemaReference]]
    if isinstance(descriptor, CapabilityDescriptor):
        references = [
            ("input_schema", descriptor.input_schema),
            ("canonical_input_schema", descriptor.canonical_input_schema),
            ("success_schema", descriptor.success_schema),
            ("failure_schema", descriptor.failure_schema),
        ]
        for validator_summary in descriptor.validators:
            for policy in validator_summary.policies:
                references.append(
                    (
                        f"validators.{validator_summary.validator_id}"
                        f".policy.{policy.policy_version}",
                        SchemaReference(
                            schema_version=policy.policy_version,
                            schema=policy.policy_schema,
                            schema_hash=policy.policy_schema_hash,
                        ),
                    )
                )
            references.append(
                (
                    f"validators.{validator_summary.validator_id}.report",
                    SchemaReference(
                        schema_version=validator_summary.report_schema_version,
                        schema=validator_summary.report_schema,
                        schema_hash=validator_summary.report_schema_hash,
                    ),
                )
            )
    else:
        references = [
            ("policy_schema", descriptor.policy_schema),
            ("report_schema", descriptor.report_schema),
        ]
    for field_name, reference in references:
        _validate_schema_reference(
            f"{descriptor.implementation_id}.{field_name}", reference
        )


def _range_projection(item: SupportedCapabilityRange) -> JsonObject:
    return {
        "capability_id": item.capability_id,
        "maximum_contract_version": item.maximum_contract_version,
        "minimum_contract_version": item.minimum_contract_version,
    }


def _schema_projection(reference: SchemaReference) -> JsonObject:
    return {
        "schema_hash": reference.schema_hash,
        "schema_version": reference.schema_version,
    }


def _validator_summary_projection(summary: ValidatorSummary) -> JsonObject:
    return {
        "policies": [
            {
                "policy_schema_hash": policy.policy_schema_hash,
                "policy_version": policy.policy_version,
            }
            for policy in sorted(
                summary.policies, key=lambda item: item.policy_version
            )
        ],
        "report_schema_hash": summary.report_schema_hash,
        "report_schema_version": summary.report_schema_version,
        "validator_id": summary.validator_id,
    }


@dataclass(frozen=True)
class _CapabilityRegistration:
    implementation: BuiltInCapability
    descriptor: CapabilityDescriptor

    def normalize_and_validate(
        self, raw_payload: JsonObject
    ) -> CanonicalInputRecord:
        return self.implementation.normalize_and_validate(raw_payload)

    def execute(
        self,
        canonical_input: CanonicalInputRecord,
        context: ExecutionContext,
    ) -> ExecutionOutcome:
        return self.implementation.execute(canonical_input, context)


@dataclass(frozen=True)
class _ValidatorRegistration:
    implementation: CapabilityValidator
    descriptor: ValidatorDescriptor

    def validate(
        self,
        canonical_input: CanonicalInputRecord,
        result_snapshot: ResultSnapshotView,
        policy: JsonObject,
        context: ValidationContext,
    ) -> ValidationReport:
        return self.implementation.validate(
            canonical_input,
            result_snapshot,
            policy,
            context,
        )


def _snapshot_capability_descriptor(
    descriptor: CapabilityDescriptor,
) -> CapabilityDescriptor:
    return descriptor.model_copy(deep=True)


def _snapshot_validator_descriptor(
    descriptor: ValidatorDescriptor,
) -> ValidatorDescriptor:
    return descriptor.model_copy(deep=True)


class CapabilityRegistry:
    """Two-dictionary registry that becomes read-only after one validated seal."""

    def __init__(self, versions: VersionSet) -> None:
        self._versions = versions
        self._capabilities: dict[CapabilityKey, _CapabilityRegistration] = {}
        self._validators: dict[ValidatorKey, _ValidatorRegistration] = {}
        self._sealed = False

    @property
    def sealed(self) -> bool:
        return self._sealed

    def _require_open(self, subject: str) -> None:
        if self._sealed:
            _duplicate(subject)

    def _implementation_identity_exists(
        self, implementation_id: str, implementation_version: str
    ) -> bool:
        identity = (implementation_id, implementation_version)
        capability_identities = (
            (
                registration.descriptor.implementation_id,
                registration.descriptor.implementation_version,
            )
            for registration in self._capabilities.values()
        )
        validator_identities = (
            (
                registration.descriptor.implementation_id,
                registration.descriptor.implementation_version,
            )
            for registration in self._validators.values()
        )
        return identity in capability_identities or identity in validator_identities

    def register_capability(self, capability: BuiltInCapability) -> None:
        descriptor = _snapshot_capability_descriptor(capability.descriptor)
        key = (descriptor.capability_id, descriptor.contract_version)
        self._require_open("/".join(key))
        if descriptor.capability_api_version != self._versions.capability_api_version:
            _unsupported(
                "capability_api",
                descriptor.capability_api_version,
                (self._versions.capability_api_version,),
            )
        if key in self._capabilities or self._implementation_identity_exists(
            descriptor.implementation_id, descriptor.implementation_version
        ):
            _duplicate("/".join(key))
        self._capabilities[key] = _CapabilityRegistration(capability, descriptor)

    def register_validator(self, validator: CapabilityValidator) -> None:
        descriptor = _snapshot_validator_descriptor(validator.descriptor)
        key = (descriptor.validator_id, descriptor.policy_version)
        self._require_open("/".join(key))
        if key in self._validators or self._implementation_identity_exists(
            descriptor.implementation_id, descriptor.implementation_version
        ):
            _duplicate("/".join(key))
        self._validators[key] = _ValidatorRegistration(validator, descriptor)

    def _fingerprint_projection(self) -> JsonObject:
        capabilities: list[JsonObject] = []
        for key in sorted(self._capabilities):
            descriptor = self._capabilities[key].descriptor
            capabilities.append(
                {
                    "capability_api_version": descriptor.capability_api_version,
                    "capability_id": descriptor.capability_id,
                    "contract_version": descriptor.contract_version,
                    "implementation_id": descriptor.implementation_id,
                    "implementation_version": descriptor.implementation_version,
                    "schemas": {
                        "canonical_input": _schema_projection(
                            descriptor.canonical_input_schema
                        ),
                        "failure": _schema_projection(descriptor.failure_schema),
                        "input": _schema_projection(descriptor.input_schema),
                        "success": _schema_projection(descriptor.success_schema),
                    },
                    "validators": [
                        _validator_summary_projection(summary)
                        for summary in sorted(
                            descriptor.validators,
                            key=lambda item: item.validator_id,
                        )
                    ],
                }
            )
        validators: list[JsonObject] = []
        for key in sorted(self._validators):
            validator_descriptor = self._validators[key].descriptor
            validators.append(
                {
                    "implementation_id": validator_descriptor.implementation_id,
                    "implementation_version": (
                        validator_descriptor.implementation_version
                    ),
                    "policy": {
                        **_schema_projection(validator_descriptor.policy_schema),
                        "version": validator_descriptor.policy_version,
                    },
                    "report": _schema_projection(validator_descriptor.report_schema),
                    "supported_capabilities": [
                        _range_projection(item)
                        for item in validator_descriptor.supported_capabilities
                    ],
                    "validator_id": validator_descriptor.validator_id,
                }
            )
        return {"capabilities": capabilities, "validators": validators}

    def _summary(self) -> RegistrySummary:
        return RegistrySummary(
            sealed=self._sealed,
            fingerprint=sha256_json(self._fingerprint_projection()),
            capability_count=len(self._capabilities),
        )

    def _validate_validator_ranges(self) -> None:
        for registration in self._validators.values():
            descriptor = registration.descriptor
            for supported in descriptor.supported_capabilities:
                versions = sorted(
                    contract_version
                    for capability_id, contract_version in self._capabilities
                    if capability_id == supported.capability_id
                )
                if not any(supported.includes(version) for version in versions):
                    requested = versions[0] if versions else "<missing>"
                    _unsupported(
                        f"validator_contract_range:{descriptor.validator_id}",
                        requested,
                        (
                            f"{supported.minimum_contract_version}"
                            f"..{supported.maximum_contract_version}",
                        ),
                    )

    def _supporting_ranges(
        self,
        descriptor: ValidatorDescriptor,
        capability_key: CapabilityKey,
    ) -> tuple[SupportedCapabilityRange, ...]:
        capability_id, contract_version = capability_key
        return tuple(
            item
            for item in descriptor.supported_capabilities
            if item.capability_id == capability_id
            and item.includes(contract_version)
        )

    def _reconcile_capability_validators(self) -> None:
        for capability_key, capability_registration in self._capabilities.items():
            summaries = capability_registration.descriptor.validators
            advertised_ids = [summary.validator_id for summary in summaries]
            if len(set(advertised_ids)) != len(advertised_ids):
                _duplicate(
                    f"{'/'.join(capability_key)}/advertised-validator-summary"
                )
            advertised_by_id = {
                summary.validator_id: summary for summary in summaries
            }
            for summary in summaries:
                policy_versions = [
                    policy.policy_version for policy in summary.policies
                ]
                if len(set(policy_versions)) != len(policy_versions):
                    _duplicate(
                        f"{'/'.join(capability_key)}/{summary.validator_id}"
                        "/advertised-policy"
                    )

            registered_by_id: dict[str, dict[str, ValidatorDescriptor]] = {}
            for registration in self._validators.values():
                descriptor = registration.descriptor
                matching_ranges = self._supporting_ranges(
                    descriptor, capability_key
                )
                if len(matching_ranges) > 1:
                    _duplicate(
                        f"{'/'.join(capability_key)}/{descriptor.validator_id}"
                        f"/{descriptor.policy_version}/supported-range"
                    )
                if not matching_ranges:
                    continue
                policies = registered_by_id.setdefault(
                    descriptor.validator_id, {}
                )
                if descriptor.policy_version in policies:
                    _duplicate(
                        f"{'/'.join(capability_key)}/{descriptor.validator_id}"
                        f"/{descriptor.policy_version}"
                    )
                policies[descriptor.policy_version] = descriptor

            advertised_id_set = set(advertised_by_id)
            registered_id_set = set(registered_by_id)
            missing_ids = sorted(advertised_id_set - registered_id_set)
            orphan_ids = sorted(registered_id_set - advertised_id_set)
            if missing_ids:
                _integrity(
                    "registry_validator_mapping",
                    "advertised validators are not registered for "
                    f"{'/'.join(capability_key)}: {missing_ids}",
                )
            if orphan_ids:
                _integrity(
                    "registry_validator_mapping",
                    "registered validators are not advertised for "
                    f"{'/'.join(capability_key)}: {orphan_ids}",
                )

            for validator_id in sorted(advertised_id_set):
                summary = advertised_by_id[validator_id]
                registered_policies = registered_by_id[validator_id]
                advertised_policies = {
                    policy.policy_version: policy for policy in summary.policies
                }
                if set(advertised_policies) != set(registered_policies):
                    _integrity(
                        "registry_validator_mapping",
                        "advertised and registered policy versions differ for "
                        f"{'/'.join(capability_key)}/{validator_id}",
                    )
                for policy_version, policy in advertised_policies.items():
                    descriptor = registered_policies[policy_version]
                    if (
                        policy.policy_schema_hash
                        != descriptor.policy_schema.schema_hash
                    ):
                        _integrity(
                            "registry_validator_mapping",
                            "advertised and registered policy Schema hashes "
                            f"differ for {'/'.join(capability_key)}/"
                            f"{validator_id}/{policy_version}",
                        )
                    if (
                        summary.report_schema_version
                        != descriptor.report_schema.schema_version
                        or summary.report_schema_hash
                        != descriptor.report_schema.schema_hash
                    ):
                        _integrity(
                            "registry_validator_mapping",
                            "advertised and registered report contracts differ "
                            f"for {'/'.join(capability_key)}/{validator_id}",
                        )
                    if summary.summary != descriptor.summary:
                        _integrity(
                            "registry_validator_mapping",
                            "advertised and registered validator summaries "
                            f"differ for {'/'.join(capability_key)}/"
                            f"{validator_id}",
                        )

    def seal(
        self, required_capabilities: frozenset[CapabilityKey]
    ) -> RegistrySummary:
        if self._sealed:
            return self._summary()
        required = required_capabilities | _REQUIRED_M1A
        missing = sorted(required - self._capabilities.keys())
        if missing:
            raise RegistryError(
                "PRECONDITION_FAILED",
                "required Built-in Capability is not registered",
                details={
                    "condition": "missing_required_capability",
                    "current_state": "unsealed",
                    "missing": tuple("/".join(item) for item in missing),
                },
            )
        try:
            catalog = SchemaCatalog.load_packaged("0.1.0")
            capability_schema = catalog.common_schemas[
                _CAPABILITY_DESCRIPTOR_SCHEMA
            ]
            validator_schema = catalog.common_schemas[_VALIDATOR_DESCRIPTOR_SCHEMA]
        except (KeyError, OSError, ValueError) as error:
            raise RegistryError(
                "INTEGRITY_FAILURE",
                "packaged registry descriptor Schemas are unavailable",
                details={"subject": "registry_descriptor"},
            ) from error
        for capability_registration in self._capabilities.values():
            _validate_descriptor(
                capability_registration.descriptor, capability_schema
            )
        for validator_registration in self._validators.values():
            _validate_descriptor(
                validator_registration.descriptor, validator_schema
            )
        self._validate_validator_ranges()
        self._reconcile_capability_validators()
        self._sealed = True
        return self._summary()

    def _require_sealed(self) -> None:
        if not self._sealed:
            raise RegistryError(
                "PRECONDITION_FAILED",
                "capability registry is not sealed",
                details={
                    "condition": "registry_not_sealed",
                    "current_state": "unsealed",
                },
            )

    def list_summaries(
        self, category: str | None, capability_id: str | None
    ) -> list[CapabilitySummary]:
        self._require_sealed()
        summaries: list[CapabilitySummary] = []
        for key in sorted(self._capabilities):
            descriptor = self._capabilities[key].descriptor
            if category is not None and descriptor.category != category:
                continue
            if capability_id is not None and descriptor.capability_id != capability_id:
                continue
            summaries.append(
                CapabilitySummary(
                    capability_id=descriptor.capability_id,
                    contract_version=descriptor.contract_version,
                    title=descriptor.title,
                    summary=descriptor.summary,
                    category=descriptor.category,
                    tags=descriptor.tags,
                    determinism=descriptor.determinism,
                    randomness=descriptor.randomness,
                    input_schema_hash=descriptor.input_schema.schema_hash,
                    canonical_input_schema_version=(
                        descriptor.canonical_input_schema.schema_version
                    ),
                    canonical_input_schema_hash=(
                        descriptor.canonical_input_schema.schema_hash
                    ),
                    success_schema_hash=descriptor.success_schema.schema_hash,
                    failure_schema_hash=descriptor.failure_schema.schema_hash,
                )
            )
        return summaries

    def resolve(
        self, capability_id: str, contract_version: str
    ) -> BuiltInCapability:
        self._require_sealed()
        key = (capability_id, contract_version)
        try:
            return self._capabilities[key]
        except KeyError as error:
            raise RegistryError(
                "NOT_FOUND",
                "exact Built-in Capability version is not registered",
                details={
                    "resource_type": "capability",
                    "resource_id": "/".join(key),
                },
            ) from error

    def resolve_validator(
        self,
        validator_id: str,
        capability_id: str,
        contract_version: str,
        policy_version: str,
    ) -> CapabilityValidator:
        self.resolve(capability_id, contract_version)
        key = (validator_id, policy_version)
        try:
            registration = self._validators[key]
        except KeyError as error:
            raise RegistryError(
                "NOT_FOUND",
                "exact validator policy version is not registered",
                details={
                    "resource_type": "validator",
                    "resource_id": "/".join(key),
                },
            ) from error
        if not any(
            item.capability_id == capability_id and item.includes(contract_version)
            for item in registration.descriptor.supported_capabilities
        ):
            _unsupported(
                f"validator_contract_range:{validator_id}",
                contract_version,
                (
                    f"{item.minimum_contract_version}..{item.maximum_contract_version}"
                    for item in registration.descriptor.supported_capabilities
                    if item.capability_id == capability_id
                ),
            )
        return registration


__all__ = ["CapabilityRegistry", "RegistryError"]
