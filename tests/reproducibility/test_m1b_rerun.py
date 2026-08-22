from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from modeling_bootstrap.composition import build_composition
from modeling_core.contracts.tools import (
    CapabilitySelection,
    CreateProjectRequest,
    RootFindingInput,
    RunExperimentRequest,
    ValidateExperimentRequest,
)
from modeling_core.contracts.canonical_json import canonical_json_bytes, sha256_json
from modeling_harness.reproducibility import ReproducibilityAuditor


def _uuid(index: int) -> str:
    return f"30000000-0000-4000-8000-{index:012x}"


def _run_request(
    project_id: str,
    operation: int,
    *,
    experiment_id: str | None = None,
) -> RunExperimentRequest:
    return RunExperimentRequest(
        operation_id=_uuid(operation),
        project_id=project_id,
        mode="new" if experiment_id is None else "rerun",
        experiment_id=experiment_id,
        capability=CapabilitySelection(
            capability_id="numerical.root_finding", contract_version="1.0.0"
        ),
        payload=RootFindingInput(expression="x*x-2", lower=0.0, upper=2.0),
    )


def _validate(
    application: object, project_id: str, run: object, operation: int
) -> None:
    application.validate_experiment(  # type: ignore[attr-defined]
        ValidateExperimentRequest(
            operation_id=_uuid(operation),
            project_id=project_id,
            attempt_id=run.attempt_id,  # type: ignore[attr-defined]
            expected_result_hash=run.result_hash,  # type: ignore[attr-defined]
            validator_id="numerical.root_finding.residual",
            policy_version="1.0.0",
            policy={},
        )
    )


def test_new_replay_rerun_and_restart_rerun_match_declared_invariants(
    tmp_path: Path,
) -> None:
    """Catches rerun drift hidden by comparing whole responses or result bytes."""
    first_composition = build_composition(tmp_path)
    with first_composition:
        project = first_composition.application.create_project(
            CreateProjectRequest(operation_id=_uuid(1))
        )
        request = _run_request(project.project_id, 2)
        first = first_composition.application.run_experiment(request)
        replay = first_composition.application.run_experiment(request)
        assert replay.replayed is True
        assert replay.attempt_id == first.attempt_id
        _validate(first_composition.application, project.project_id, first, 3)
        rerun = first_composition.application.run_experiment(
            _run_request(
                project.project_id,
                4,
                experiment_id=first.experiment_id,
            )
        )
        _validate(first_composition.application, project.project_id, rerun, 5)

    second_composition = build_composition(tmp_path)
    with second_composition:
        restarted = second_composition.application.run_experiment(
            _run_request(
                project.project_id,
                6,
                experiment_id=first.experiment_id,
            )
        )
        _validate(second_composition.application, project.project_id, restarted, 7)

    report = ReproducibilityAuditor().audit(
        tmp_path,
        first.experiment_id,
        (first.attempt_id, rerun.attempt_id, restarted.attempt_id),
    )

    assert report.status == "PASS"
    assert report.mismatches == ()
    assert {item.invariant: item.outcome for item in report.comparisons} == {
        "environment_snapshot": "not_comparable",
        "immutable_intent": "equal",
        "implementation": "equal",
        "randomness": "equal",
        "result": "within_tolerance",
        "terminal_classification": "equal",
        "validation_conclusion": "equal",
    }

    database_path = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database_path)) as db:
        artifact = db.execute(
            "SELECT role, media_type, schema_id, created_at FROM artifacts "
            "WHERE artifact_id=?",
            (first.result_hash,),
        ).fetchone()
        assert artifact is not None
        result_path = (
            tmp_path
            / ".modeling"
            / "artifacts"
            / "sha256"
            / first.result_hash[7:9]
            / f"{first.result_hash[7:]}.json"
        )
        forged_document = json.loads(result_path.read_bytes())
        forged_document["data"]["function_value"] = 1.0
        forged_bytes = canonical_json_bytes(forged_document)
        forged_hash = sha256_json(forged_document)
        forged_path = (
            result_path.parents[1] / forged_hash[7:9] / f"{forged_hash[7:]}.json"
        )
        forged_path.parent.mkdir(exist_ok=True)
        forged_path.write_bytes(forged_bytes)
        db.execute(
            "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                forged_hash,
                artifact[0],
                artifact[1],
                len(forged_bytes),
                forged_hash,
                artifact[2],
                artifact[3],
            ),
        )
        db.execute(
            "UPDATE result_snapshots SET result_hash=?, result_artifact_id=? "
            "WHERE attempt_id=?",
            (forged_hash, forged_hash, first.attempt_id),
        )
        db.commit()
    forged = ReproducibilityAuditor().audit(
        tmp_path,
        first.experiment_id,
        (first.attempt_id, rerun.attempt_id, restarted.attempt_id),
    )
    assert {item.invariant for item in forged.mismatches} >= {"result"}

    with closing(sqlite3.connect(database_path)) as db:
        db.execute("UPDATE attempts SET randomness='used', seed=7")
        db.execute("DELETE FROM validations")
        db.commit()
    tampered = ReproducibilityAuditor().audit(
        tmp_path,
        first.experiment_id,
        (first.attempt_id, rerun.attempt_id, restarted.attempt_id),
    )
    assert tampered.status == "FAIL"
    assert {item.invariant for item in tampered.mismatches} >= {
        "randomness",
        "result",
        "validation_conclusion",
    }
