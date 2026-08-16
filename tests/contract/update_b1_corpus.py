"""Update 1.0.0 corpus files with 1.0.0 version constants."""

from pathlib import Path

REPLACEMENTS = {
    '"modeling-tools/0.1.0"': '"modeling-tools/1.0.0"',
    '"modeling-project/0.1.0"': '"modeling-project/1.0.0"',
    '"modeling-error/0.1.0"': '"modeling-error/1.0.0"',
    '"modeling-result/0.1.0"': '"modeling-result/1.0.0"',
    '"modeling-validation-report/0.1.0"': '"modeling-validation-report/1.0.0"',
    '"modeling-capability/0.1.0"': '"modeling-capability/1.0.0"',
    '"application_version": "0.1.0"': '"application_version": "0.2.0"',
    '"canonical-json/0.1.0"': '"canonical-json/1.0.0"',
    '"numerical.root_finding/0.1.0"': '"numerical.root_finding/1.0.0"',
    '"numerical.root_finding.canonical-input/0.1.0"': '"numerical.root_finding.canonical-input/1.0.0"',
    '"numerical.root_finding.residual/0.1.0"': '"numerical.root_finding.residual/1.0.0"',
    '"database_schema_version": 1': '"database_schema_version": 2',
}

if __name__ == "__main__":
    root = Path("tests/contract/corpus/tools/1.0.0")
    for f in sorted(root.glob("*.json")):
        text = f.read_text(encoding="utf-8")
        changed = False
        for old, new in REPLACEMENTS.items():
            if old in text:
                text = text.replace(old, new)
                changed = True
        if changed:
            f.write_text(text, encoding="utf-8")
            print(f"updated: {f.name}")
        else:
            print(f"skipped: {f.name}")
