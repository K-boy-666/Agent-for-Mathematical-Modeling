"""Generate 1.0.0 baseline manifests."""

import json
from pathlib import Path

from modeling_core.contracts.canonical_json import canonical_json_bytes, sha256_json
from modeling_core.contracts.schema_catalog import SchemaCatalog

BASELINE_ROOT = Path(__file__).parent / "baselines"


def generate_tool_baseline() -> None:
    catalog = SchemaCatalog.load_packaged("1.0.0")
    entries = []
    for (tool, kind), schema in sorted(catalog.tool_schemas.items()):
        entries.append(
            {
                "path": f"schemas/tools/1.0.0/{tool}.{kind}.schema.json",
                "$id": schema["$id"],
                "sha256": sha256_json(schema),
                "kind": kind,
            }
        )
    manifest = canonical_json_bytes(entries)
    path = BASELINE_ROOT / "modeling-tools-1.0.0.json"
    path.write_bytes(manifest)
    print(f"tools baseline: {len(entries)} entries, {path}")


def generate_capability_baseline() -> None:
    cap_root = (
        Path(__file__).parents[2]
        / "src"
        / "modeling_capabilities"
        / "root_finding"
        / "schemas"
        / "1.0.0"
    )
    entries = []
    for asset in sorted(cap_root.iterdir()):
        if not asset.name.endswith(".schema.json"):
            continue
        schema = json.loads(asset.read_text(encoding="utf-8"))
        entries.append(
            {
                "path": f"schemas/1.0.0/{asset.name}",
                "$id": schema["$id"],
                "sha256": sha256_json(schema),
                "kind": "schema",
            }
        )
    manifest = canonical_json_bytes(entries)
    path = BASELINE_ROOT / "modeling-capability-1.0.0.json"
    path.write_bytes(manifest)
    print(f"capability baseline: {len(entries)} entries, {path}")


if __name__ == "__main__":
    generate_tool_baseline()
    generate_capability_baseline()
