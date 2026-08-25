"""Declared-tolerance reproducibility audit for one stable experiment."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from modeling_capabilities.root_finding.descriptor import build_root_finding_descriptor
from modeling_core.contracts.canonical_json import sha256_json, strict_json_loads
from modeling_core.contracts.common import JsonObject, JsonValue
from modeling_core.contracts.tools import CanonicalRootFindingInput
from modeling_core.contracts.versions import VersionSet
from modeling_core.ports.artifact_store import ArtifactStoreError
from modeling_infrastructure.artifacts.store import ContentAddressedArtifactStore
from modeling_infrastructure.project_paths import ProjectPaths

ComparisonOutcome = Literal["equal", "within_tolerance", "not_comparable", "mismatch"]


@dataclass(frozen=True)
class ReproducibilityComparison:
    invariant: str
    outcome: ComparisonOutcome


@dataclass(frozen=True)
class ReproducibilityMismatch:
    attempt_id: str
    invariant: str
    reason: str


@dataclass(frozen=True)
class ReproducibilityReport:
    experiment_id: str
    attempt_ids: tuple[str, ...]
    status: Literal["PASS", "FAIL"]
    comparisons: tuple[ReproducibilityComparison, ...]
    mismatches: tuple[ReproducibilityMismatch, ...]


class ReproducibilityAuditor:
    """Compare named invariants without claiming byte-for-byte reproducibility."""

    def audit(
        self,
        project_root: Path,
        experiment_id: str,
        attempts: tuple[str, ...],
    ) -> ReproducibilityReport:
        if len(attempts) < 2 or len(set(attempts)) != len(attempts):
            raise ValueError("audit requires at least two unique attempt IDs")
        paths = ProjectPaths.bind(project_root)
        database_uri = paths.database.resolve().as_uri() + "?mode=ro"
        placeholders = ",".join("?" for _ in attempts)
        with sqlite3.connect(database_uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute(
                f"""
                SELECT a.attempt_id, a.experiment_id, a.implementation_id,
                       a.implementation_version, a.randomness, a.seed,
                       a.input_snapshot_id, a.environment_snapshot_id, a.status,
                       e.capability_id, e.contract_version,
                       e.input_snapshot_id AS experiment_input_snapshot_id,
                       e.canonical_input_schema_version, e.canonical_payload,
                       e.canonical_payload_hash, e.model_snapshot_hash,
                       e.data_snapshot_references, e.data_snapshot_set_hash,
                       i.canonical_input_schema_version AS input_schema_version,
                       i.canonical_payload_hash AS input_payload_hash,
                       i.model_snapshot_hash AS input_model_hash,
                       i.data_snapshot_references AS input_data_references,
                       i.data_snapshot_set_hash AS input_data_hash,
                       r.result_kind, r.result_hash, r.result_schema_version,
                       r.result_artifact_id, art.artifact_id,
                       art.role AS artifact_role, art.media_type AS artifact_media_type,
                       art.byte_size, art.sha256 AS artifact_sha256,
                       art.schema_id AS artifact_schema_id
                  FROM attempts AS a
                  JOIN experiments AS e ON e.experiment_id=a.experiment_id
                  JOIN input_snapshots AS i ON i.input_snapshot_id=a.input_snapshot_id
             LEFT JOIN result_snapshots AS r ON r.attempt_id=a.attempt_id
             LEFT JOIN artifacts AS art ON art.artifact_id=r.result_artifact_id
                 WHERE a.attempt_id IN ({placeholders})
                 ORDER BY a.attempt_id COLLATE BINARY
                """,
                attempts,
            ).fetchall()
            validation_rows = connection.execute(
                f"""
                SELECT v.attempt_id, v.status, v.outcome, v.expected_result_hash,
                       v.result_hash AS validated_result_hash,
                       v.validation_report_hash, v.report_artifact_id, art.artifact_id,
                       art.role AS artifact_role, art.media_type AS artifact_media_type,
                       art.byte_size, art.sha256 AS artifact_sha256,
                       art.schema_id AS artifact_schema_id
                  FROM validations AS v
             LEFT JOIN artifacts AS art ON art.artifact_id=v.report_artifact_id
                 WHERE v.attempt_id IN ({placeholders})
                 ORDER BY v.attempt_id COLLATE BINARY, v.validation_id COLLATE BINARY
                """,
                attempts,
            ).fetchall()

        by_id = {row["attempt_id"]: row for row in rows}
        if set(by_id) != set(attempts):
            raise ValueError("one or more audit attempts do not exist")
        ordered = [by_id[attempt_id] for attempt_id in attempts]
        if any(row["experiment_id"] != experiment_id for row in ordered):
            raise ValueError("all audit attempts must belong to the experiment")

        mismatches: list[ReproducibilityMismatch] = []

        def mismatch(attempt_id: str, invariant: str, reason: str) -> None:
            mismatches.append(ReproducibilityMismatch(attempt_id, invariant, reason))

        def compare_equal(invariant: str, fields: tuple[str, ...]) -> None:
            baseline = tuple(ordered[0][field] for field in fields)
            for row in ordered[1:]:
                if tuple(row[field] for field in fields) != baseline:
                    mismatch(row["attempt_id"], invariant, "recorded value changed")

        compare_equal(
            "immutable_intent",
            (
                "capability_id",
                "contract_version",
                "canonical_input_schema_version",
                "canonical_payload_hash",
                "model_snapshot_hash",
                "data_snapshot_set_hash",
                "input_snapshot_id",
            ),
        )
        compare_equal("implementation", ("implementation_id", "implementation_version"))
        compare_equal("randomness", ("randomness", "seed"))
        compare_equal("terminal_classification", ("status", "result_kind"))

        descriptor = build_root_finding_descriptor(VersionSet.m1b())
        for row in ordered:
            if (
                row["capability_id"] != descriptor.capability_id
                or row["contract_version"] != descriptor.contract_version
                or row["input_snapshot_id"] != row["experiment_input_snapshot_id"]
                or row["canonical_input_schema_version"]
                != descriptor.canonical_input_schema.schema_version
            ):
                mismatch(row["attempt_id"], "immutable_intent", "descriptor changed")
            if (
                row["implementation_id"] != descriptor.implementation_id
                or row["implementation_version"] != descriptor.implementation_version
            ):
                mismatch(row["attempt_id"], "implementation", "descriptor changed")
            if row["randomness"] != descriptor.randomness or row["seed"] is not None:
                mismatch(row["attempt_id"], "randomness", "descriptor claim violated")

        baseline = ordered[0]
        payload_value = strict_json_loads(baseline["canonical_payload"].encode("utf-8"))
        if not isinstance(payload_value, dict):
            raise ValueError("canonical payload must be an object")
        canonical = CanonicalRootFindingInput.model_validate(payload_value, strict=True)
        payload = cast(JsonObject, canonical.model_dump(mode="json"))
        data_references = strict_json_loads(
            baseline["data_snapshot_references"].encode("utf-8")
        )
        if not isinstance(data_references, list):
            raise ValueError("data snapshot references must be an array")
        observed_hashes = (
            sha256_json(payload),
            sha256_json(
                cast(
                    JsonObject,
                    {"language": "math-expr-v1", "ast": payload["expression_ast"]},
                )
            ),
            sha256_json(cast(JsonValue, data_references)),
        )
        recorded_hashes = (
            baseline["canonical_payload_hash"],
            baseline["model_snapshot_hash"],
            baseline["data_snapshot_set_hash"],
        )
        input_hashes = (
            baseline["input_payload_hash"],
            baseline["input_model_hash"],
            baseline["input_data_hash"],
        )
        if (
            observed_hashes != recorded_hashes
            or input_hashes != recorded_hashes
            or baseline["input_schema_version"]
            != baseline["canonical_input_schema_version"]
            or baseline["input_data_references"] != baseline["data_snapshot_references"]
        ):
            mismatch(
                baseline["attempt_id"], "immutable_intent", "snapshot hash mismatch"
            )

        artifact_store = ContentAddressedArtifactStore(paths, schema_version="1.0.0")
        schema_version = VersionSet.m1b().result_schema_version.rsplit("/", 1)[1]
        result_schema_id = (
            "https://schemas.math-modeling-mcp.local/common/"
            f"{schema_version}/modeling-result.schema.json"
        )
        report_schema_id = (
            "https://schemas.math-modeling-mcp.local/common/"
            f"{schema_version}/modeling-validation-report.schema.json"
        )

        validation_by_attempt: dict[str, list[str]] = {item: [] for item in attempts}
        for row in validation_rows:
            if row["status"] != "SUCCEEDED":
                continue
            validation_by_attempt[row["attempt_id"]].append(row["outcome"])
            if (
                row["expected_result_hash"] != by_id[row["attempt_id"]]["result_hash"]
                or row["validated_result_hash"]
                != by_id[row["attempt_id"]]["result_hash"]
                or row["validation_report_hash"] is None
                or row["report_artifact_id"] != row["validation_report_hash"]
                or row["artifact_id"] != row["report_artifact_id"]
                or row["artifact_sha256"] != row["report_artifact_id"]
                or row["artifact_role"] != "validation_report"
                or row["artifact_media_type"] != "application/json"
                or row["artifact_schema_id"] != report_schema_id
                or row["byte_size"] is None
            ):
                mismatch(
                    row["attempt_id"],
                    "validation_conclusion",
                    "report relation invalid",
                )
                continue
            try:
                artifact_store.read_verified(
                    row["report_artifact_id"], row["byte_size"], row["artifact_sha256"]
                )
            except ArtifactStoreError:
                mismatch(
                    row["attempt_id"],
                    "validation_conclusion",
                    "report verification failed",
                )
        for attempt_id, validation_outcomes in validation_by_attempt.items():
            if not validation_outcomes:
                mismatch(
                    attempt_id, "validation_conclusion", "no successful validation"
                )
        baseline_validations = tuple(validation_by_attempt[attempts[0]])
        for attempt_id in attempts[1:]:
            if tuple(validation_by_attempt[attempt_id]) != baseline_validations:
                mismatch(attempt_id, "validation_conclusion", "conclusion changed")

        seen_environments: set[str] = set()
        for row in ordered:
            if row["environment_snapshot_id"] in seen_environments:
                mismatch(
                    row["attempt_id"],
                    "environment_snapshot",
                    "rerun reused an environment snapshot",
                )
            seen_environments.add(row["environment_snapshot_id"])

        results: list[tuple[sqlite3.Row, float, float]] = []
        for row in ordered:
            if (
                row["result_hash"] is None
                or row["result_artifact_id"] != row["result_hash"]
                or row["artifact_id"] != row["result_artifact_id"]
                or row["artifact_sha256"] != row["result_artifact_id"]
                or row["artifact_role"] != "result"
                or row["artifact_media_type"] != "application/json"
                or row["artifact_schema_id"] != result_schema_id
                or row["byte_size"] is None
            ):
                mismatch(row["attempt_id"], "result", "result relation invalid")
                continue
            try:
                raw = artifact_store.read_verified(
                    row["result_artifact_id"], row["byte_size"], row["artifact_sha256"]
                )
            except ArtifactStoreError:
                mismatch(row["attempt_id"], "result", "result verification failed")
                continue
            document = strict_json_loads(raw)
            if not isinstance(document, dict) or not isinstance(
                document.get("data"), dict
            ):
                mismatch(row["attempt_id"], "result", "result payload invalid")
                continue
            data = document["data"]
            root = float(data["root"])
            function_value = float(data["function_value"])
            if (
                not math.isfinite(root)
                or not math.isfinite(function_value)
                or abs(function_value) > canonical.function_tolerance
            ):
                mismatch(row["attempt_id"], "result", "result residual invalid")
            results.append((row, root, function_value))
        if len(results) == len(attempts):
            baseline_root = results[0][1]
            for row, root, _ in results[1:]:
                limit = max(
                    canonical.absolute_tolerance,
                    canonical.relative_tolerance * max(abs(baseline_root), abs(root)),
                )
                if abs(root - baseline_root) > limit:
                    mismatch(row["attempt_id"], "result", "declared tolerance exceeded")

        outcomes: dict[str, ComparisonOutcome] = {
            "environment_snapshot": "not_comparable",
            "immutable_intent": "equal",
            "implementation": "equal",
            "randomness": "equal",
            "result": "within_tolerance",
            "terminal_classification": "equal",
            "validation_conclusion": "equal",
        }
        for item in mismatches:
            outcomes[item.invariant] = "mismatch"
        comparisons = tuple(
            ReproducibilityComparison(name, outcome)
            for name, outcome in sorted(outcomes.items())
        )
        ordered_mismatches = tuple(
            sorted(
                mismatches,
                key=lambda item: (item.invariant, item.attempt_id, item.reason),
            )
        )
        return ReproducibilityReport(
            experiment_id=experiment_id,
            attempt_ids=attempts,
            status="FAIL" if ordered_mismatches else "PASS",
            comparisons=comparisons,
            mismatches=ordered_mismatches,
        )


__all__ = [
    "ReproducibilityAuditor",
    "ReproducibilityComparison",
    "ReproducibilityMismatch",
    "ReproducibilityReport",
]
