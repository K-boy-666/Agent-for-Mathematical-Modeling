"""Safe canonical input boundary for the built-in root-finding capability."""

from modeling_capabilities.root_finding.contracts import (
    EvaluationBudget,
    InputValidationError,
    normalize_root_finding_input,
)

__all__ = [
    "EvaluationBudget",
    "InputValidationError",
    "normalize_root_finding_input",
]
