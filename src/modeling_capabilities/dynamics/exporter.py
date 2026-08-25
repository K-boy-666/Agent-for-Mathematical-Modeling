"""Deterministic C1 workbooks, figures, result card, and provenance."""

from __future__ import annotations

import math
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from modeling_core.contracts.canonical_json import canonical_json_bytes
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.tools import CoupledHeaveResultData

_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def _cell(reference: str, value: str | float) -> str:
    if isinstance(value, str):
        return f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'
    if not math.isfinite(value):
        raise ValueError("C1 export contains a non-finite value")
    return f'<c r="{reference}"><v>{value:.17g}</v></c>'


def _sheet(data: CoupledHeaveResultData) -> bytes:
    rows = [
        '<row r="1">'
        + _cell("A1", "时间 (s)")
        + _cell("B1", "振子")
        + _cell("D1", "浮子")
        + "</row>",
        '<row r="2">'
        + _cell("B2", "位移 (m)")
        + _cell("C2", "速度 (m/s)")
        + _cell("D2", "位移 (m)")
        + _cell("E2", "速度 (m/s)")
        + "</row>",
    ]
    for index, values in enumerate(
        zip(data.t, data.x_o, data.v_o, data.x_f, data.v_f, strict=True),
        start=3,
    ):
        rows.append(
            f'<row r="{index}">'
            + "".join(
                _cell(f"{column}{index}", value)
                for column, value in zip("ABCDE", values, strict=True)
            )
            + "</row>"
        )
    xml = (
        _HEAD
        + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + '<dimension ref="A1:E900"/><sheetData>'
        + "".join(rows)
        + '</sheetData><mergeCells count="3"><mergeCell ref="A1:A2"/>'
        + '<mergeCell ref="B1:C1"/><mergeCell ref="D1:E1"/></mergeCells>'
        + "</worksheet>"
    )
    return xml.encode("utf-8")


def _xlsx(data: CoupledHeaveResultData) -> bytes:
    documents = {
        "[Content_Types].xml": _HEAD
        + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        + '<Default Extension="xml" ContentType="application/xml"/>'
        + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        + "</Types>",
        "_rels/.rels": _HEAD
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        + "</Relationships>",
        "xl/workbook.xml": _HEAD
        + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        + '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": _HEAD
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        + "</Relationships>",
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name in sorted(documents):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, documents[name].encode("utf-8"))
        info = ZipInfo("xl/worksheets/sheet1.xml", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        archive.writestr(info, _sheet(data))
    return buffer.getvalue()


def _svg(data: CoupledHeaveResultData) -> bytes:
    width, height, margin = 1000.0, 600.0, 50.0
    values = (*data.x_f, *data.x_o)
    low, high = min(values), max(values)
    span = max(high - low, 1e-12)

    def points(series: tuple[float, ...]) -> str:
        return " ".join(
            f"{margin + index * (width - 2 * margin) / 897:.3f},"
            f"{height - margin - (value - low) * (height - 2 * margin) / span:.3f}"
            for index, value in enumerate(series)
        )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 600">'
        '<rect width="1000" height="600" fill="white"/>'
        f'<polyline fill="none" stroke="#0057b8" points="{points(data.x_f)}"/>'
        f'<polyline fill="none" stroke="#d62728" points="{points(data.x_o)}"/>'
        '<text x="50" y="30" font-family="sans-serif" font-size="20">x_f / x_o time series</text>'
        "</svg>"
    ).encode("utf-8")


def build_c1_exports(
    results: dict[str, JsonObject],
    provenance: JsonObject,
) -> tuple[tuple[str, str, str, bytes], ...]:
    typed = {
        mode: CoupledHeaveResultData.model_validate_json(canonical_json_bytes(value))
        for mode, value in results.items()
    }
    if set(typed) != {"linear", "power_law"}:
        raise ValueError("both C1 damping results are required")
    card: JsonObject = {"times_seconds": [10, 20, 40, 60, 100], "cases": {}}
    cases = card["cases"]
    assert isinstance(cases, dict)
    for mode, data in typed.items():
        cases[mode] = [
            {
                "time": float(data.t[index]),
                "x_f": float(data.x_f[index]),
                "v_f": float(data.v_f[index]),
                "x_o": float(data.x_o[index]),
                "v_o": float(data.v_o[index]),
            }
            for index in (50, 100, 200, 300, 500)
        ]
    return (
        (
            "workbook",
            "result1-1.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            _xlsx(typed["linear"]),
        ),
        (
            "workbook",
            "result1-2.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            _xlsx(typed["power_law"]),
        ),
        ("figure", "linear-timeseries.svg", "image/svg+xml", _svg(typed["linear"])),
        (
            "figure",
            "power-law-timeseries.svg",
            "image/svg+xml",
            _svg(typed["power_law"]),
        ),
        (
            "result_card",
            "result-card.json",
            "application/json",
            canonical_json_bytes(card),
        ),
        (
            "provenance",
            "provenance.json",
            "application/json",
            canonical_json_bytes(provenance),
        ),
    )


__all__ = ["build_c1_exports"]
