"""Schema compatibility comparator — immutable 1.0 baseline enforcement."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    """A single incompatibility between a baseline and candidate schema."""

    path: str
    rule: str
    baseline_value: object
    candidate_value: object


@dataclass
class CompatibilityReport:
    """Report from comparing two schema sets."""

    compatible: bool
    issues: list[CompatibilityIssue] = field(default_factory=list)


def compare_schema_sets(
    baseline: dict[str, object],
    candidate: dict[str, object],
) -> CompatibilityReport:
    """Compare candidate schema set against a frozen baseline.

    The baseline is an immutable manifest mapping tool names to their
    request/result/error schemas.  The candidate is a modified version
    being checked for compatibility.
    """
    issues: list[CompatibilityIssue] = []

    baseline_tools = _non_meta_keys(baseline)
    candidate_tools = _non_meta_keys(candidate)

    if baseline_tools != candidate_tools:
        added = candidate_tools - baseline_tools
        removed = baseline_tools - candidate_tools
        if added:
            issues.append(
                CompatibilityIssue(
                    path="",
                    rule="tool-set",
                    baseline_value=sorted(baseline_tools),
                    candidate_value=sorted(candidate_tools),
                )
            )
        if removed:
            issues.append(
                CompatibilityIssue(
                    path="",
                    rule="tool-set",
                    baseline_value=sorted(baseline_tools),
                    candidate_value=sorted(candidate_tools),
                )
            )

    for tool_name in sorted(baseline_tools & candidate_tools):
        baseline_tool = baseline[tool_name]
        candidate_tool = candidate[tool_name]
        if not isinstance(baseline_tool, dict) or not isinstance(candidate_tool, dict):
            continue
        baseline_kinds = _non_meta_keys(baseline_tool)
        candidate_kinds = _non_meta_keys(candidate_tool)
        for kind in sorted(baseline_kinds & candidate_kinds):
            _compare_schemas(
                baseline_tool[kind],
                candidate_tool[kind],
                f"/{tool_name}/{kind}",
                issues,
            )

    issues.sort(key=lambda issue: issue.path)
    return CompatibilityReport(
        compatible=len(issues) == 0,
        issues=issues,
    )


def _non_meta_keys(schema: dict[str, object]) -> set[str]:
    return {k for k in schema if not k.startswith("$") and k != "baseline_hash"}


def _compare_schemas(
    baseline: object,
    candidate: object,
    path: str,
    issues: list[CompatibilityIssue],
) -> None:
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        if baseline != candidate:
            issues.append(
                CompatibilityIssue(
                    path=path,
                    rule="value-changed",
                    baseline_value=baseline,
                    candidate_value=candidate,
                )
            )
        return

    # Check $id stability
    if "$id" in baseline:
        if "$id" not in candidate or baseline["$id"] != candidate["$id"]:
            issues.append(
                CompatibilityIssue(
                    path=f"{path}/$id",
                    rule="id-changed",
                    baseline_value=baseline.get("$id"),
                    candidate_value=candidate.get("$id"),
                )
            )

    # Check type stability
    if "type" in baseline:
        if "type" not in candidate or baseline["type"] != candidate["type"]:
            issues.append(
                CompatibilityIssue(
                    path=f"{path}/type",
                    rule="type-changed",
                    baseline_value=baseline.get("type"),
                    candidate_value=candidate.get("type"),
                )
            )
    elif "type" in candidate:
        issues.append(
            CompatibilityIssue(
                path=f"{path}/type",
                rule="type-added",
                baseline_value=None,
                candidate_value=candidate["type"],
            )
        )

    # Check additionalProperties tightening
    for key in ("additionalProperties",):
        if key in baseline and key in candidate:
            if baseline[key] is False and candidate[key] is not False:
                issues.append(
                    CompatibilityIssue(
                        path=f"{path}/{key}",
                        rule="additional-properties-relaxed",
                        baseline_value=baseline[key],
                        candidate_value=candidate[key],
                    )
                )

    # Check property stability
    baseline_props = _safe_obj(baseline.get("properties"))
    candidate_props = _safe_obj(candidate.get("properties"))

    for prop_name in sorted(baseline_props):
        if prop_name not in candidate_props:
            issues.append(
                CompatibilityIssue(
                    path=f"{path}/properties/{prop_name}",
                    rule="property-removed",
                    baseline_value=baseline_props[prop_name],
                    candidate_value=None,
                )
            )
        else:
            _compare_schemas(
                baseline_props[prop_name],
                candidate_props[prop_name],
                f"{path}/properties/{prop_name}",
                issues,
            )

    for prop_name in sorted(set(candidate_props) - set(baseline_props)):
        issues.append(
            CompatibilityIssue(
                path=f"{path}/properties/{prop_name}",
                rule="property-added",
                baseline_value=None,
                candidate_value=candidate_props[prop_name],
            )
        )

    # Check required stability
    baseline_required = set(
        candidate.get("required", [])
        if isinstance(baseline.get("required"), list)
        else []
    )
    candidate_required = set(
        candidate.get("required", [])
        if isinstance(candidate.get("required"), list)
        else []
    )
    added_required = candidate_required - baseline_required
    if added_required:
        for prop in sorted(added_required):
            issues.append(
                CompatibilityIssue(
                    path=f"{path}/required/{prop}",
                    rule="required-added",
                    baseline_value=None,
                    candidate_value=prop,
                )
            )
    # relaxing required is accepted, so no issue for removed_required

    # Check enum stability
    baseline_enum = _safe_list(baseline.get("enum"))
    candidate_enum = _safe_list(candidate.get("enum"))
    if baseline_enum:
        if not candidate_enum or set(baseline_enum) - set(candidate_enum):
            issues.append(
                CompatibilityIssue(
                    path=f"{path}/enum",
                    rule="enum-narrowed",
                    baseline_value=baseline_enum,
                    candidate_value=candidate_enum,
                )
            )
        elif set(candidate_enum) - set(baseline_enum):
            # Widening: accepted for request, rejected for result
            if "/result/" in path:
                issues.append(
                    CompatibilityIssue(
                        path=f"{path}/enum",
                        rule="response-enum-widened",
                        baseline_value=baseline_enum,
                        candidate_value=candidate_enum,
                    )
                )
    elif candidate_enum:
        # Adding an enum where there was none
        issues.append(
            CompatibilityIssue(
                path=f"{path}/enum",
                rule="enum-added",
                baseline_value=None,
                candidate_value=candidate_enum,
            )
        )

    # Check numeric range stability
    for bound in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if bound in baseline and bound in candidate:
            if bound in ("minimum", "maximum"):
                # narrowing (lower min, higher max) is accepted for request
                # widening (higher min, lower max) is rejected
                if bound == "minimum" and candidate[bound] > baseline[bound]:
                    issues.append(
                        CompatibilityIssue(
                            path=f"{path}/{bound}",
                            rule="bound-narrowed",
                            baseline_value=baseline[bound],
                            candidate_value=candidate[bound],
                        )
                    )
                elif bound == "maximum" and candidate[bound] < baseline[bound]:
                    issues.append(
                        CompatibilityIssue(
                            path=f"{path}/{bound}",
                            rule="bound-narrowed",
                            baseline_value=baseline[bound],
                            candidate_value=candidate[bound],
                        )
                    )

    # Recurse into oneOf / anyOf / allOf
    for combinator in ("oneOf", "anyOf", "allOf"):
        baseline_items = _safe_list(baseline.get(combinator))
        candidate_items = _safe_list(candidate.get(combinator))
        if len(baseline_items) != len(candidate_items):
            issues.append(
                CompatibilityIssue(
                    path=f"{path}/{combinator}",
                    rule="combinator-count-changed",
                    baseline_value=len(baseline_items),
                    candidate_value=len(candidate_items),
                )
            )
        else:
            for i, (b_item, c_item) in enumerate(zip(baseline_items, candidate_items)):
                _compare_schemas(b_item, c_item, f"{path}/{combinator}/{i}", issues)

    # Recurse into $defs
    baseline_defs = _safe_obj(baseline.get("$defs"))
    candidate_defs = _safe_obj(candidate.get("$defs"))
    for def_name in sorted(baseline_defs):
        if def_name in candidate_defs:
            _compare_schemas(
                baseline_defs[def_name],
                candidate_defs[def_name],
                f"{path}/$defs/{def_name}",
                issues,
            )


def _safe_obj(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _safe_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []
