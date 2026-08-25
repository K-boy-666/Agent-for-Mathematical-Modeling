from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

from mcp.types import CallToolResult

from modeling_bootstrap.composition import build_composition


def _call(
    composition: object,
    tool: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    result = composition.adapter.call_tool(tool, arguments)  # type: ignore[attr-defined]
    assert isinstance(result, CallToolResult)
    assert result.isError is False, result.structuredContent
    assert isinstance(result.structuredContent, dict)
    return result.structuredContent


def test_c1_two_case_validations_publish_required_exports(tmp_path: Path) -> None:
    """Catches C1 runs bypassing validation or returning an empty export."""
    (tmp_path / "problem.txt").write_text("CUMCM 2022 A Q1", encoding="utf-8")
    composition = build_composition(tmp_path)

    with composition:
        project = _call(
            composition,
            "create_project",
            {
                "operation_id": "00000000-0000-4000-8000-000000000101",
                "display_name": "C1 workflow",
            },
        )
        project_id = project["project_id"]
        assets = _call(
            composition,
            "register_problem_assets",
            {
                "operation_id": "00000000-0000-4000-8000-000000000102",
                "project_id": project_id,
                "asset_paths": [{"label": "problem", "path": "problem.txt"}],
            },
        )
        snapshots = assets["snapshots"]
        mmir = _call(
            composition,
            "put_subproblem_mmir",
            {
                "operation_id": "00000000-0000-4000-8000-000000000103",
                "project_id": project_id,
                "subproblem_id": "CUMCM-2022-A-Q1",
                "mmir": {
                    "schema_version": "modeling-mmir/0.1.0",
                    "problem_id": "CUMCM-2022-A",
                    "question_id": "Q1",
                    "assumptions": [
                        "coordinates are deviations from static equilibrium"
                    ],
                    "asset_labels": ["problem"],
                    "derivation": "approved coupled-heave equations",
                    "parameters": {},
                },
            },
        )
        revision = mmir["mmir_revision"]
        _call(
            composition,
            "confirm_subproblem_mmir",
            {
                "operation_id": "00000000-0000-4000-8000-000000000104",
                "project_id": project_id,
                "subproblem_id": "CUMCM-2022-A-Q1",
                "mmir_revision": revision,
            },
        )

        for index, (mode, validator_id) in enumerate(
            (
                ("linear", "dynamics.coupled_heave.linear"),
                ("power_law", "dynamics.coupled_heave.power_law"),
            ),
            start=0,
        ):
            run = _call(
                composition,
                "run_experiment",
                {
                    "operation_id": f"00000000-0000-4000-8000-{105 + index * 2:012d}",
                    "project_id": project_id,
                    "mode": "new",
                    "capability": {
                        "capability_id": "dynamics.coupled_heave",
                        "contract_version": "0.1.0",
                    },
                    "payload": {
                        "subproblem_id": "CUMCM-2022-A-Q1",
                        "mmir_revision": revision,
                        "damping_mode": mode,
                        "asset_snapshots": snapshots,
                    },
                    "execution": {"timeout_ms": 60000, "seed": None},
                },
            )
            assert run["attempt_status"] == "SUCCEEDED", run
            assert run["result_summary"]["damping_mode"] == mode  # type: ignore[index]
            validation = _call(
                composition,
                "validate_experiment",
                {
                    "operation_id": f"00000000-0000-4000-8000-{106 + index * 2:012d}",
                    "project_id": project_id,
                    "attempt_id": run["attempt_id"],
                    "expected_result_hash": run["result_hash"],
                    "validator_id": validator_id,
                    "policy_version": "0.1.0",
                    "policy": {},
                    "timeout_ms": 60000,
                },
            )
            assert validation["validation_status"] == "SUCCEEDED"
            assert validation["outcome"] == "PASSED"

        exported = _call(
            composition,
            "export_subproblem",
            {
                "operation_id": "00000000-0000-4000-8000-000000000109",
                "project_id": project_id,
                "subproblem_id": "CUMCM-2022-A-Q1",
            },
        )

    exports = exported["exports"]
    assert isinstance(exports, list)
    assert {item["label"] for item in exports} == {
        "result1-1.xlsx",
        "result1-2.xlsx",
        "linear-timeseries.svg",
        "power-law-timeseries.svg",
        "result-card.json",
        "provenance.json",
    }
    assert len({item["sha256"] for item in exports}) == 6
    by_label = {item["label"]: item for item in exports}
    for label in ("result1-1.xlsx", "result1-2.xlsx"):
        digest = by_label[label]["sha256"].removeprefix("sha256:")
        path = (
            tmp_path
            / ".modeling"
            / "artifacts"
            / "sha256"
            / digest[:2]
            / f"{digest}.xlsx"
        )
        with ZipFile(path) as workbook:
            sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows = sheet.findall(".//m:sheetData/m:row", namespace)
        assert len(rows) == 900
        assert all(len(row.findall("m:c", namespace)) == 5 for row in rows[2:])
        assert [node.text for node in sheet.findall(".//m:t", namespace)] == [
            "时间 (s)",
            "振子",
            "浮子",
            "位移 (m)",
            "速度 (m/s)",
            "位移 (m)",
            "速度 (m/s)",
        ]
    card_item = by_label["result-card.json"]
    card_digest = card_item["sha256"].removeprefix("sha256:")
    card_path = (
        tmp_path
        / ".modeling"
        / "artifacts"
        / "sha256"
        / card_digest[:2]
        / f"{card_digest}.json"
    )
    assert json.loads(card_path.read_text(encoding="utf-8"))["times_seconds"] == [
        10,
        20,
        40,
        60,
        100,
    ]
