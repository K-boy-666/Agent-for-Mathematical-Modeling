"""B3 echo capability test fixture — excluded from the production wheel."""

from __future__ import annotations

from modeling_core.contracts.capability import (
    CapabilityDescriptor,
    CanonicalInputRecord,
    ExecutionContext,
    ExecutionOutcome,
    ResultSnapshotView,
    ValidationContext,
    ValidationReport,
    ValidatorDescriptor,
    SchemaReference,
    SupportedCapabilityRange,
)
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.tools import (
    CapabilityLimits,
    PolicyContract,
    SuccessResultPayload,
    ValidationReportPayload,
    ValidatorSummary,
)
from modeling_core.registry import CapabilityRegistry


def _make_echo_descriptor() -> CapabilityDescriptor:
    from modeling_core.contracts.canonical_json import sha256_json
    from modeling_core.contracts.schema_catalog import SchemaCatalog

    catalog = SchemaCatalog.load_packaged("0.1.0")
    simple_schema = catalog.for_tool("health_check", "request")
    schema_hash = sha256_json(simple_schema)
    input_schema = SchemaReference(
        schema_version="0.1.0",
        schema=simple_schema,
        schema_hash=schema_hash,
    )
    return CapabilityDescriptor(
        kind="built_in",
        capability_api_version="modeling-capability/0.1.0",
        capability_id="test.echo",
        contract_version="0.1.0",
        implementation_id="test.echo",
        implementation_version="0.1.0",
        title="Test Echo",
        summary="Returns its canonical input unchanged for extension testing.",
        category="test",
        tags=("extension", "test"),
        determinism="deterministic",
        randomness="not_used",
        input_schema=input_schema,
        canonical_input_schema=input_schema,
        success_schema=input_schema,
        failure_schema=input_schema,
        default_limits=CapabilityLimits(
            timeout_ms=60000, max_iterations=10000, max_evaluations=20000
        ),
        maximum_limits=CapabilityLimits(
            timeout_ms=60000, max_iterations=10000, max_evaluations=20000
        ),
        artifact_roles=(),
        validators=[
            ValidatorSummary(
                validator_id="test.echo",
                summary="Test echo validator.",
                report_schema_version="0.1.0",
                report_schema=input_schema.schema,
                report_schema_hash=schema_hash,
                policies=(
                    PolicyContract(
                        policy_version="1.0.0",
                        policy_schema=input_schema.schema,
                        policy_schema_hash=schema_hash,
                    ),
                ),
            )
        ],
        context_ref="test",
    )


class EchoCapability:
    """Test-only capability that returns its canonical input unchanged."""

    def __init__(self) -> None:
        self._descriptor = _make_echo_descriptor()

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return self._descriptor

    def normalize_and_validate(self, raw_payload: JsonObject) -> CanonicalInputRecord:
        from modeling_core.contracts.canonical_json import sha256_json

        return CanonicalInputRecord(
            canonical_input_schema_version="1.0.0",
            canonical_payload=raw_payload,
            canonical_payload_hash=sha256_json(raw_payload),
            model_snapshot_hash=sha256_json({}),
            data_snapshot_references=(),
            data_snapshot_set_hash=sha256_json([]),
        )

    def execute(
        self,
        canonical_input: CanonicalInputRecord,
        context: ExecutionContext,
    ) -> ExecutionOutcome:
        # Use model_construct to bypass root_finding-specific Literal
        # constraints — this is a test-only capability, not a real solver.
        payload = SuccessResultPayload.model_construct(
            _fields_set={
                "result_schema_version",
                "capability_id",
                "contract_version",
                "result_kind",
                "data",
            },
            result_schema_version="modeling-result/0.1.0",
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
            result_kind="success",
            data={
                "root": 0.0,
                "function_value": 0.0,
                "iterations": 0,
                "evaluations": 1,
                "termination_reason": "endpoint_root",
            },
        )
        return ExecutionOutcome(result_kind="success", result_payload=payload)


class EchoValidator:
    """Test-only validator that computes a fresh equality check."""

    def __init__(self) -> None:
        from modeling_core.contracts.canonical_json import sha256_json
        from modeling_core.contracts.schema_catalog import SchemaCatalog

        catalog = SchemaCatalog.load_packaged("0.1.0")
        simple_schema = catalog.for_tool("health_check", "request")
        schema_hash = sha256_json(simple_schema)
        policy_schema = SchemaReference(
            schema_version="0.1.0",
            schema=simple_schema,
            schema_hash=schema_hash,
        )
        self._descriptor = ValidatorDescriptor(
            kind="built_in",
            validator_id="test.echo",
            supported_capabilities=(
                SupportedCapabilityRange(
                    capability_id="test.echo",
                    minimum_contract_version="0.1.0",
                    maximum_contract_version="0.1.0",
                ),
            ),
            implementation_id="test.echo.validator",
            implementation_version="0.1.0",
            policy_version="1.0.0",
            policy_schema=policy_schema,
            report_schema=policy_schema,
            summary="Test echo validator.",
        )

    @property
    def descriptor(self) -> ValidatorDescriptor:
        return self._descriptor

    def validate(
        self,
        canonical_input: CanonicalInputRecord,
        result_snapshot: ResultSnapshotView,
        policy: JsonObject,
        context: ValidationContext,
    ) -> ValidationReport:
        from modeling_core.contracts.tools import ValidationMetrics

        return ValidationReportPayload.model_construct(
            _fields_set={
                "report_schema_version",
                "validator_id",
                "validator_implementation_id",
                "validator_implementation_version",
                "policy_version",
                "policy",
                "policy_hash",
                "capability_id",
                "contract_version",
                "canonical_payload_hash",
                "model_snapshot_hash",
                "data_snapshot_set_hash",
                "result_hash",
                "outcome",
                "metrics",
            },
            report_schema_version="modeling-validation-report/0.1.0",
            validator_id="numerical.root_finding.residual",
            validator_implementation_id="test.echo.validator",
            validator_implementation_version="0.1.0",
            policy_version="0.1.0",
            policy={},
            policy_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
            canonical_payload_hash=canonical_input.canonical_payload_hash,
            model_snapshot_hash=canonical_input.model_snapshot_hash,
            data_snapshot_set_hash=canonical_input.data_snapshot_set_hash,
            result_hash=result_snapshot.result_hash,
            outcome="PASSED",
            metrics=ValidationMetrics.model_construct(
                _fields_set={
                    "root_within_interval",
                    "reported_function_value",
                    "recomputed_function_value",
                    "absolute_reported_delta",
                    "absolute_residual",
                    "function_tolerance",
                    "failed_checks",
                },
                root_within_interval=True,
                reported_function_value=0.0,
                recomputed_function_value=None,
                absolute_reported_delta=None,
                absolute_residual=None,
                function_tolerance=1e-10,
                failed_checks=(),
            ),
        )


def compose_test_echo_registry() -> CapabilityRegistry:
    """Compose a sealed registry with test.echo for architecture tests."""
    from modeling_core.contracts.versions import VersionSet
    from modeling_capabilities.root_finding.solver import (
        BisectionRootFindingCapability,
    )
    from modeling_capabilities.root_finding.validator import (
        ResidualRootFindingValidator,
    )

    registry = CapabilityRegistry(VersionSet.m1a())
    registry.register_capability(BisectionRootFindingCapability())
    registry.register_validator(ResidualRootFindingValidator())
    registry.register_capability(EchoCapability())
    registry.register_validator(EchoValidator())
    registry.seal(frozenset())
    return registry
