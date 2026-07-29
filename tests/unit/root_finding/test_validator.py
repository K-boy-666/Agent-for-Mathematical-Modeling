"""Behavior, contract, and schema tests for residual validation."""

from __future__ import annotations

import json
from collections.abc import Iterator
from importlib.util import module_from_spec, spec_from_file_location
from importlib.resources import files
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
import pytest

from modeling_capabilities.root_finding.contracts import (
    EvaluationBudget,
    EvaluationBudgetExceeded,
    EvaluationCancelled,
    EvaluationDeadlineExceeded,
)
from modeling_capabilities.root_finding.descriptor import (
    build_root_finding_descriptor,
)
from modeling_capabilities.root_finding.expression.validator_evaluator import (
    ValidatorEvaluator,
)
from modeling_capabilities.root_finding.solver import (
    BisectionRootFindingCapability,
)
from modeling_capabilities.root_finding.validator import (
    EMPTY_POLICY_HASH,
    ResidualRootFindingValidator,
    ValidationInputError,
)
from modeling_core.contracts.capability import (
    CancellationSignal,
    CanonicalInputRecord,
    ResultSnapshotView,
    ValidationContext,
)
from modeling_core.contracts.canonical_json import (
    canonical_json_bytes,
    sha256_json,
)
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.versions import VersionSet
from modeling_core.registry import CapabilityRegistry
_FIXTURE_SPEC = spec_from_file_location(
    "a8_forged_results",
    Path(__file__).parents[2] / "fixtures" / "forged_results.py",
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_FIXTURES = module_from_spec(_FIXTURE_SPEC)
_FIXTURE_SPEC.loader.exec_module(_FIXTURES)
canonical_input = _FIXTURES.canonical_input
numerical_failure_snapshot = _FIXTURES.numerical_failure_snapshot
success_snapshot = _FIXTURES.success_snapshot

_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_POLICY_HASH = (
    "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
)


class _Clock:
    def __init__(self, values: Iterator[float] | None = None) -> None:
        self.values = values
        self.last = 0.0

    def utc_now(self) -> object:
        raise AssertionError("validator must not read wall-clock time")

    def monotonic(self) -> float:
        if self.values is not None:
            self.last = next(self.values, self.last)
        return self.last


class _Cancellation:
    def __init__(
        self, cancelled: bool = False, *, cancel_on_check: int | None = None
    ) -> None:
        self.cancelled = cancelled
        self.cancel_on_check = cancel_on_check
        self.checks = 0

    def is_cancelled(self) -> bool:
        self.checks += 1
        return self.cancelled or (
            self.cancel_on_check is not None
            and self.checks >= self.cancel_on_check
        )


def _context(
    *,
    clock: _Clock | None = None,
    cancellation: _Cancellation | None = None,
    deadline: float = 10.0,
) -> ValidationContext:
    return ValidationContext(
        deadline=deadline,
        clock=clock or _Clock(),
        cancellation=cast(
            CancellationSignal, cancellation or _Cancellation()
        ),
    )


def _validate(
    canonical: CanonicalInputRecord | None = None,
    result: ResultSnapshotView | None = None,
    *,
    policy: object = None,
    context: ValidationContext | None = None,
) -> object:
    actual_policy = {} if policy is None else policy
    return ResidualRootFindingValidator().validate(
        canonical or canonical_input(),
        result or success_snapshot(),
        cast(JsonObject, actual_policy),
        context or _context(),
    )


def test_golden_success_is_passed_with_exact_metrics_and_hashes() -> None:
    canonical = canonical_input()
    result = success_snapshot()

    report = _validate(canonical, result)

    assert report.outcome == "PASSED"
    assert report.metrics.failed_checks == ()
    assert set(report.metrics.model_dump(mode="json")) == {
        "root_within_interval",
        "reported_function_value",
        "recomputed_function_value",
        "absolute_reported_delta",
        "absolute_residual",
        "function_tolerance",
        "failed_checks",
    }
    assert report.metrics.root_within_interval is True
    assert report.metrics.recomputed_function_value == pytest.approx(
        result.result_payload.data.root**2 - 2.0  # type: ignore[union-attr]
    )
    assert report.canonical_payload_hash == canonical.canonical_payload_hash
    assert report.model_snapshot_hash == canonical.model_snapshot_hash
    assert (
        report.data_snapshot_set_hash == canonical.data_snapshot_set_hash
    )
    assert report.result_hash == result.result_hash
    assert report.policy_hash == _POLICY_HASH == EMPTY_POLICY_HASH
    assert report.policy == {}


@pytest.mark.parametrize("root", [-0.25, 2.25])
def test_root_below_or_above_interval_is_first_failure(root: float) -> None:
    report = _validate(
        canonical_input(expression="x", lower=0.0, upper=2.0),
        success_snapshot(root=root, function_value=root),
    )

    assert report.metrics.root_within_interval is False
    assert report.metrics.failed_checks[0] == "root_out_of_interval"


@pytest.mark.parametrize(
    ("expression", "root", "expected_check"),
    [
        ("1/x", 0.0, "expression_undefined"),
        ("exp(x)", 1000.0, "non_finite_recomputed_value"),
    ],
)
def test_undefined_or_nonfinite_recomputation_has_three_null_metrics(
    expression: str, root: float, expected_check: str
) -> None:
    canonical = canonical_input(
        expression=expression,
        lower=root - 1.0,
        upper=root + 1.0,
    )

    report = _validate(
        canonical, success_snapshot(root=root, function_value=0.0)
    )

    assert report.outcome == "FAILED"
    assert report.metrics.recomputed_function_value is None
    assert report.metrics.absolute_reported_delta is None
    assert report.metrics.absolute_residual is None
    assert report.metrics.failed_checks == (expected_check,)


def test_forged_reported_value_is_detected_independently() -> None:
    report = _validate(
        canonical_input(expression="x-1", lower=0.0, upper=2.0),
        success_snapshot(root=1.0, function_value=9.0),
    )

    assert report.metrics.recomputed_function_value == 0.0
    assert report.metrics.absolute_reported_delta == 9.0
    assert report.metrics.absolute_residual == 0.0
    assert report.metrics.failed_checks == ("reported_value_mismatch",)


def test_excessive_residual_is_detected_even_when_reported_value_matches() -> None:
    report = _validate(
        canonical_input(
            expression="x-1",
            lower=0.0,
            upper=2.0,
            function_tolerance=1e-12,
        ),
        success_snapshot(root=1.5, function_value=0.5),
    )

    assert report.metrics.absolute_reported_delta == 0.0
    assert report.metrics.absolute_residual == 0.5
    assert report.metrics.failed_checks == (
        "residual_exceeds_tolerance",
    )


def test_simultaneous_finite_failures_have_fixed_order() -> None:
    report = _validate(
        canonical_input(
            expression="x-1",
            lower=0.0,
            upper=2.0,
            function_tolerance=1e-12,
        ),
        success_snapshot(root=3.0, function_value=99.0),
    )

    assert report.metrics.failed_checks == (
        "root_out_of_interval",
        "reported_value_mismatch",
        "residual_exceeds_tolerance",
    )


def test_out_of_range_undefined_failures_keep_fixed_order() -> None:
    report = _validate(
        canonical_input(expression="1/x", lower=1.0, upper=2.0),
        success_snapshot(root=0.0, function_value=0.0),
    )

    assert report.metrics.failed_checks == (
        "root_out_of_interval",
        "expression_undefined",
    )


def test_self_consistent_forged_result_hash_still_fails_mathematically() -> None:
    result = success_snapshot(root=1.0, function_value=-1.0)
    assert result.result_hash == sha256_json(
        cast(JsonObject, result.result_payload.model_dump(mode="json"))
    )

    report = _validate(canonical_input(), result)

    assert report.result_hash == result.result_hash
    assert report.outcome == "FAILED"
    assert report.metrics.failed_checks == (
        "residual_exceeds_tolerance",
    )


def test_legal_interval_tolerance_success_can_validate_failed() -> None:
    report = _validate(
        canonical_input(
            expression="x-1",
            lower=0.0,
            upper=2.0,
            function_tolerance=1e-12,
        ),
        success_snapshot(
            root=1.5,
            function_value=0.5,
            termination_reason="interval_tolerance",
        ),
    )

    assert report.outcome == "FAILED"
    assert report.metrics.failed_checks == (
        "residual_exceeds_tolerance",
    )


@pytest.mark.parametrize(
    "policy",
    [
        {"unexpected": True},
        {"function_tolerance": 1e-6},
        [],
        None,
        "empty",
        0,
    ],
)
def test_policy_is_a_strict_empty_builtin_object(policy: object) -> None:
    validator = ResidualRootFindingValidator()
    with pytest.raises(ValidationInputError, match="policy"):
        validator.validate(
            canonical_input(),
            success_snapshot(),
            cast(JsonObject, policy),
            _context(),
        )


@pytest.mark.parametrize(
    ("canonical", "result", "field"),
    [
        (
            canonical_input(outer_schema_version="wrong/0.1.0"),
            success_snapshot(),
            "canonical_input_schema_version",
        ),
        (
            canonical_input(inner_schema_version="wrong/0.1.0"),
            success_snapshot(),
            "canonical_payload.canonical_input_schema_version",
        ),
        (
            canonical_input(),
            success_snapshot(outer_capability_id="other"),
            "result_snapshot.capability_id",
        ),
        (
            canonical_input(),
            success_snapshot(outer_contract_version="9.9.9"),
            "result_snapshot.contract_version",
        ),
        (
            canonical_input(),
            success_snapshot(outer_result_schema_version="wrong/0.1.0"),
            "result_snapshot.result_schema_version",
        ),
        (
            canonical_input(),
            success_snapshot(inner_capability_id="other"),
            "result_payload.capability_id",
        ),
        (
            canonical_input(),
            success_snapshot(inner_contract_version="9.9.9"),
            "result_payload.contract_version",
        ),
        (
            canonical_input(),
            success_snapshot(inner_result_schema_version="wrong/0.1.0"),
            "result_payload.result_schema_version",
        ),
        (
            canonical_input(),
            success_snapshot(inner_result_kind="numerical_failure"),
            "result_payload.result_kind",
        ),
        (
            canonical_input(),
            numerical_failure_snapshot(),
            "result_payload.result_kind",
        ),
    ],
)
def test_identity_and_success_preconditions_reject_before_math(
    monkeypatch: pytest.MonkeyPatch,
    canonical: CanonicalInputRecord,
    result: ResultSnapshotView,
    field: str,
) -> None:
    evaluations = 0

    def forbidden(*_args: object, **_kwargs: object) -> float:
        nonlocal evaluations
        evaluations += 1
        raise AssertionError("precondition violation reached math")

    monkeypatch.setattr(ValidatorEvaluator, "evaluate", forbidden)

    with pytest.raises(ValidationInputError) as caught:
        _validate(canonical, result)
    assert caught.value.field_path == field
    assert evaluations == 0


def test_invalid_canonical_payload_shape_rejects_before_math() -> None:
    valid = canonical_input()
    payload = valid.canonical_payload
    payload["unexpected"] = True
    invalid = CanonicalInputRecord(
        canonical_input_schema_version=valid.canonical_input_schema_version,
        canonical_payload=payload,
        canonical_payload_hash=sha256_json(payload),
        model_snapshot_hash=valid.model_snapshot_hash,
        data_snapshot_references=(),
        data_snapshot_set_hash=valid.data_snapshot_set_hash,
    )

    with pytest.raises(ValidationInputError) as caught:
        _validate(invalid)
    assert caught.value.field_path == "canonical_payload"


def test_deadline_equality_is_operational_not_a_report() -> None:
    with pytest.raises(EvaluationDeadlineExceeded):
        _validate(context=_context(clock=_Clock(iter([10.0])), deadline=10.0))


def test_cancellation_has_priority_over_equal_deadline() -> None:
    cancellation = _Cancellation(cancelled=True)
    with pytest.raises(EvaluationCancelled):
        _validate(
            context=_context(
                clock=_Clock(iter([10.0])),
                cancellation=cancellation,
                deadline=10.0,
            )
        )
    assert cancellation.checks == 1


@pytest.mark.parametrize(
    ("control", "check_index"),
    [("cancel", 2), ("deadline", 2), ("cancel", 3), ("deadline", 3)],
)
def test_mid_validation_and_final_return_control_checks_propagate(
    control: str, check_index: int
) -> None:
    cancellation = _Cancellation(
        cancel_on_check=check_index if control == "cancel" else None
    )
    clock = _Clock(
        iter(
            [0.0] * (check_index - 1)
            + [10.0]
            + [10.0] * 8
        )
    )
    expected = (
        EvaluationCancelled
        if control == "cancel"
        else EvaluationDeadlineExceeded
    )

    with pytest.raises(expected):
        _validate(
            canonical_input(expression="x", lower=-1.0, upper=1.0),
            success_snapshot(root=0.0, function_value=0.0),
            context=_context(
                clock=clock,
                cancellation=cancellation,
                deadline=10.0,
            ),
        )


@pytest.mark.parametrize(
    "error",
    [
        EvaluationBudgetExceeded("function_evaluations", 1),
        EvaluationCancelled("cancelled in evaluator"),
        EvaluationDeadlineExceeded("deadline in evaluator"),
    ],
)
def test_control_and_budget_exceptions_propagate_unchanged(
    monkeypatch: pytest.MonkeyPatch, error: RuntimeError
) -> None:
    def raise_exact(
        _self: ValidatorEvaluator,
        _ast: object,
        _root: float,
        _budget: EvaluationBudget,
    ) -> float:
        raise error

    monkeypatch.setattr(ValidatorEvaluator, "evaluate", raise_exact)

    with pytest.raises(type(error)) as caught:
        _validate()
    assert caught.value is error


def test_recomputation_uses_one_fresh_bounded_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budgets: list[EvaluationBudget] = []

    def capture(
        _self: ValidatorEvaluator,
        _ast: object,
        root: float,
        budget: EvaluationBudget,
    ) -> float:
        budgets.append(budget)
        budget.begin_evaluation()
        return root * root - 2.0

    monkeypatch.setattr(ValidatorEvaluator, "evaluate", capture)

    report = _validate()

    assert report.outcome == "PASSED"
    assert len(budgets) == 1
    assert budgets[0].max_evaluations == 20_000
    assert budgets[0].evaluations_used == 1


def test_finite_subtraction_overflow_is_mismatch_not_nonfinite_value() -> None:
    report = _validate(
        canonical_input(
            expression="x", lower=-1.7e308, upper=1.7e308
        ),
        success_snapshot(root=1.7e308, function_value=-1.7e308),
    )

    assert report.metrics.recomputed_function_value == 1.7e308
    assert report.metrics.absolute_reported_delta is None
    assert report.metrics.absolute_residual == 1.7e308
    assert report.metrics.failed_checks == (
        "reported_value_mismatch",
        "residual_exceeds_tolerance",
    )
    payload = report.model_dump(mode="json")
    assert "Infinity" not in json.dumps(payload)


def test_validator_descriptor_and_capability_summary_reconcile_exactly() -> None:
    validator = ResidualRootFindingValidator()
    descriptor = validator.descriptor
    capability = build_root_finding_descriptor()
    assert descriptor.validator_id == "numerical.root_finding.residual"
    assert descriptor.implementation_id == (
        "builtin.numerical.root_finding.residual"
    )
    assert descriptor.implementation_version == "0.1.0"
    assert descriptor.policy_version == "0.1.0"
    assert len(descriptor.supported_capabilities) == 1
    supported = descriptor.supported_capabilities[0]
    assert supported.capability_id == "numerical.root_finding"
    assert supported.minimum_contract_version == "0.1.0"
    assert supported.maximum_contract_version == "0.1.0"
    assert sha256_json({}) == _POLICY_HASH
    assert descriptor.policy_schema.schema_hash == sha256_json(
        descriptor.policy_schema.schema
    )

    assert len(capability.validators) == 1
    summary = capability.validators[0]
    assert summary.validator_id == descriptor.validator_id
    assert summary.summary == descriptor.summary
    assert summary.report_schema_version == (
        descriptor.report_schema.schema_version
    )
    assert summary.report_schema == descriptor.report_schema.schema
    assert summary.report_schema_hash == descriptor.report_schema.schema_hash
    assert len(summary.policies) == 1
    advertised_policy = summary.policies[0]
    assert advertised_policy.policy_version == descriptor.policy_version
    assert advertised_policy.policy_schema == descriptor.policy_schema.schema
    assert canonical_json_bytes(advertised_policy.policy_schema) == (
        descriptor.policy_schema.schema_bytes
    )
    assert (
        advertised_policy.policy_schema_hash
        == descriptor.policy_schema.schema_hash
    )
    assert canonical_json_bytes(summary.report_schema) == (
        descriptor.report_schema.schema_bytes
    )


def test_test_local_registry_seals_and_resolves_exact_validator() -> None:
    capability = BisectionRootFindingCapability()
    validator = ResidualRootFindingValidator()
    registry = CapabilityRegistry(VersionSet.m1a())
    registry.register_capability(capability)
    registry.register_validator(validator)
    summary = registry.seal(
        frozenset({("numerical.root_finding", "0.1.0")})
    )

    assert summary.sealed is True
    resolved = registry.resolve_validator(
        "numerical.root_finding.residual",
        "numerical.root_finding",
        "0.1.0",
        "0.1.0",
    )
    assert resolved.descriptor == validator.descriptor


def _load_schema(package: str, *parts: str) -> JsonObject:
    return cast(
        JsonObject,
        json.loads(
            files(package).joinpath(*parts).read_text(encoding="utf-8")
        ),
    )


def test_policy_report_and_common_schemas_are_strict_draft_2020_12() -> None:
    validator = ResidualRootFindingValidator()
    report = cast(JsonObject, _validate().model_dump(mode="json"))
    policy_schema = validator.descriptor.policy_schema.schema
    report_schema = validator.descriptor.report_schema.schema
    common_schema = _load_schema(
        "modeling_core.contracts",
        "schemas",
        "common",
        "0.1.0",
        "modeling-validation-report.schema.json",
    )

    for schema in (policy_schema, report_schema, common_schema):
        assert schema["$schema"] == _DRAFT
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        Draft202012Validator.check_schema(schema)

    policy_validator = Draft202012Validator(policy_schema)
    policy_validator.validate({})
    for invalid in ({"x": 1}, [], None, "empty"):
        assert list(policy_validator.iter_errors(invalid))

    for schema in (report_schema, common_schema):
        schema_validator = Draft202012Validator(schema)
        schema_validator.validate(report)
        extra = dict(report)
        extra["unexpected"] = True
        assert list(schema_validator.iter_errors(extra))


def test_report_schemas_accept_null_recomputation_branch_and_reject_unknowns() -> None:
    report = cast(
        JsonObject,
        _validate(
            canonical_input(expression="1/x", lower=-1.0, upper=1.0),
            success_snapshot(root=0.0, function_value=0.0),
        ).model_dump(mode="json"),
    )
    schemas = (
        ResidualRootFindingValidator().descriptor.report_schema.schema,
        _load_schema(
            "modeling_core.contracts",
            "schemas",
            "common",
            "0.1.0",
            "modeling-validation-report.schema.json",
        ),
    )

    for schema in schemas:
        validator = Draft202012Validator(schema)
        validator.validate(report)

        unknown_outcome = dict(report)
        unknown_outcome["outcome"] = "INCONCLUSIVE"
        assert list(validator.iter_errors(unknown_outcome))

        unknown_check = json.loads(json.dumps(report))
        unknown_check["metrics"]["failed_checks"] = ["unknown"]
        assert list(validator.iter_errors(unknown_check))

        mixed_null_branch = json.loads(json.dumps(report))
        mixed_null_branch["metrics"]["absolute_residual"] = 0.0
        assert list(validator.iter_errors(mixed_null_branch))


def test_report_schemas_bind_outcome_to_empty_or_nonempty_checks() -> None:
    passed = cast(JsonObject, _validate().model_dump(mode="json"))
    failed = cast(
        JsonObject,
        _validate(
            canonical_input(expression="x-1"),
            success_snapshot(root=1.5, function_value=0.5),
        ).model_dump(mode="json"),
    )
    schemas = (
        ResidualRootFindingValidator().descriptor.report_schema.schema,
        _load_schema(
            "modeling_core.contracts",
            "schemas",
            "common",
            "0.1.0",
            "modeling-validation-report.schema.json",
        ),
    )

    passed_with_failure = json.loads(json.dumps(passed))
    passed_with_failure["metrics"]["failed_checks"] = [
        "residual_exceeds_tolerance"
    ]
    failed_without_failure = json.loads(json.dumps(failed))
    failed_without_failure["metrics"]["failed_checks"] = []

    for schema in schemas:
        validator = Draft202012Validator(schema)
        assert list(validator.iter_errors(passed_with_failure))
        assert list(validator.iter_errors(failed_without_failure))


def test_validator_never_returns_inconclusive() -> None:
    outcomes = {
        _validate().outcome,
        _validate(
            canonical_input(expression="x-1"),
            success_snapshot(root=1.5, function_value=0.5),
        ).outcome,
    }
    assert outcomes == {"PASSED", "FAILED"}
