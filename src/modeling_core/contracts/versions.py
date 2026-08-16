from __future__ import annotations

from typing import Self

from modeling_core.contracts.common import StrictModel


class VersionSet(StrictModel):
    application_release: str
    mcp_protocol_version: str
    tool_contract_version: str
    project_format_version: str
    database_schema_version: int
    capability_api_version: str
    error_schema_version: str
    result_schema_version: str
    validation_report_schema_version: str
    canonicalization_version: str
    root_finding_contract_version: str
    root_finding_canonical_input_version: str
    residual_policy_version: str

    @classmethod
    def m1a(cls) -> Self:
        return cls(
            application_release="0.1.0",
            mcp_protocol_version="2025-11-25",
            tool_contract_version="modeling-tools/0.1.0",
            project_format_version="modeling-project/0.1.0",
            database_schema_version=1,
            capability_api_version="modeling-capability/0.1.0",
            error_schema_version="modeling-error/0.1.0",
            result_schema_version="modeling-result/0.1.0",
            validation_report_schema_version="modeling-validation-report/0.1.0",
            canonicalization_version="canonical-json/0.1.0",
            root_finding_contract_version="numerical.root_finding/0.1.0",
            root_finding_canonical_input_version=(
                "numerical.root_finding.canonical-input/0.1.0"
            ),
            residual_policy_version="numerical.root_finding.residual/0.1.0",
        )

    @classmethod
    def m1b(cls) -> Self:
        return cls(
            application_release="0.2.0",
            mcp_protocol_version="2025-11-25",
            tool_contract_version="modeling-tools/1.0.0",
            project_format_version="modeling-project/1.0.0",
            database_schema_version=2,
            capability_api_version="modeling-capability/1.0.0",
            error_schema_version="modeling-error/1.0.0",
            result_schema_version="modeling-result/1.0.0",
            validation_report_schema_version="modeling-validation-report/1.0.0",
            canonicalization_version="canonical-json/1.0.0",
            root_finding_contract_version="numerical.root_finding/1.0.0",
            root_finding_canonical_input_version=(
                "numerical.root_finding.canonical-input/1.0.0"
            ),
            residual_policy_version="numerical.root_finding.residual/1.0.0",
        )
