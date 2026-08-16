from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Mapping

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from referencing import Registry, Resource

from modeling_core.contracts.canonical_json import sha256_json
from modeling_core.contracts.common import JsonObject

ToolSchemaKey = tuple[str, str]


@dataclass(frozen=True)
class SchemaCatalog:
    tool_schemas: Mapping[ToolSchemaKey, JsonObject]
    common_schemas: Mapping[str, JsonObject]
    fingerprint: str
    _registry: Registry[Any]

    @classmethod
    def load_packaged(cls, version: str = "0.1.0") -> SchemaCatalog:
        if version != "0.1.0":
            raise ValueError(f"unsupported packaged tool contract version: {version}")
        root = files("modeling_core.contracts")
        tool_root = root.joinpath("schemas", "tools", version)
        common_root = root.joinpath("schemas", "common", version)

        tool_schemas: dict[ToolSchemaKey, JsonObject] = {}
        common_schemas: dict[str, JsonObject] = {}
        registry: Registry[Any] = Registry()
        fingerprint_input: dict[str, JsonObject] = {}

        for asset in sorted(common_root.iterdir(), key=lambda item: item.name):
            if not asset.name.endswith(".schema.json"):
                continue
            schema = json.loads(asset.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            schema_id = schema["$id"]
            common_schemas[schema_id] = schema
            fingerprint_input[f"common/{asset.name}"] = schema
            registry = registry.with_resource(schema_id, Resource.from_contents(schema))

        for asset in sorted(tool_root.iterdir(), key=lambda item: item.name):
            if not asset.name.endswith(".schema.json"):
                continue
            stem = asset.name.removesuffix(".schema.json")
            tool, kind = stem.rsplit(".", 1)
            if kind not in {"request", "result", "error"}:
                raise ValueError(f"unexpected tool schema kind: {asset.name}")
            schema = json.loads(asset.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            key = (tool, kind)
            if key in tool_schemas:
                raise ValueError(f"duplicate tool schema: {key}")
            tool_schemas[key] = schema
            fingerprint_input[f"tools/{asset.name}"] = schema
            registry = registry.with_resource(
                schema["$id"], Resource.from_contents(schema)
            )

        expected_tools = {
            "health_check",
            "create_project",
            "get_project_status",
            "list_capabilities",
            "run_experiment",
            "validate_experiment",
            "register_problem_assets",
            "put_subproblem_mmir",
            "confirm_subproblem_mmir",
            "export_subproblem",
        }
        expected = {
            (tool, kind)
            for tool in expected_tools
            for kind in ("request", "result", "error")
        }
        if set(tool_schemas) != expected:
            missing = sorted(expected - set(tool_schemas))
            extra = sorted(set(tool_schemas) - expected)
            raise ValueError(
                f"incomplete tool schema catalog; missing={missing}, extra={extra}"
            )
        return cls(
            tool_schemas=tool_schemas,
            common_schemas=common_schemas,
            fingerprint=sha256_json(fingerprint_input),
            _registry=registry,
        )

    def for_tool(self, tool: str, kind: str) -> JsonObject:
        try:
            return self.tool_schemas[(tool, kind)]
        except KeyError as error:
            raise KeyError(f"unknown tool schema: {tool}.{kind}") from error

    def validator(self, tool: str, kind: str) -> Draft202012Validator:
        return Draft202012Validator(
            self.for_tool(tool, kind),
            registry=self._registry,
        )
