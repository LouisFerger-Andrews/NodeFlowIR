"""Structured diagnostics produced by non-throwing workflow validation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import AliasChoices, ConfigDict, Field, JsonValue

from nodeflowir._model import NodeFlowModel


class IssueCode(StrEnum):
    UNKNOWN_NODE_DEFINITION = "unknown_node_definition"
    UNKNOWN_NODE = "unknown_node"
    UNKNOWN_NODE_OUTPUT = "unknown_node_output"
    UNAVAILABLE_NODE_OUTPUT = "unavailable_node_output"
    UNKNOWN_WORKFLOW_INPUT = "unknown_workflow_input"
    UNKNOWN_CONSTANT = "unknown_constant"
    UNKNOWN_LOOP_SCOPE = "unknown_loop_scope"
    INVALID_REFERENCE_PATH = "invalid_reference_path"
    UNKNOWN_TARGET_PORT = "unknown_target_port"
    UNKNOWN_CONFIGURATION_FIELD = "unknown_configuration_field"
    MISSING_REQUIRED_CONFIGURATION = "missing_required_configuration"
    INVALID_CONFIGURATION_VALUE = "invalid_configuration_value"
    DUPLICATE_NODE_STEP = "duplicate_node_step"
    UNUSED_NODE = "unused_node"
    INVALID_LITERAL_TYPE = "invalid_literal_type"
    MISSING_REQUIRED_INPUT = "missing_required_input"
    DUPLICATE_INPUT_BINDING = "duplicate_input_binding"
    INCOMPATIBLE_VALUE_TYPE = "incompatible_value_type"
    INVALID_EXPRESSION_OPERATOR = "invalid_expression_operator"
    INVALID_COLLECTION_OPERATION = "invalid_collection_operation"
    INVALID_CONVERSION = "invalid_conversion"
    INVALID_CONDITION_TYPE = "invalid_condition_type"
    INVALID_MATCH_CASE = "invalid_match_case"
    INVALID_LOOP_COLLECTION = "invalid_loop_collection"
    INVALID_LOOP_CONTROL = "invalid_loop_control"
    INVALID_PARALLEL_BRANCH = "invalid_parallel_branch"
    INVALID_ERROR_FLOW = "invalid_error_flow"
    INVALID_DYNAMIC_PROVIDER_VALUE = "invalid_dynamic_provider_value"


class ValidationIssue(NodeFlowModel):
    """One machine-readable validation failure."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True)

    code: IssueCode
    message: str
    path: tuple[str | int, ...] = Field(
        default_factory=tuple,
        validation_alias=AliasChoices("path", "location"),
    )
    expected: JsonValue | None = None
    received: JsonValue | None = None

    @property
    def location(self) -> tuple[str | int, ...]:
        """Compatibility alias for callers using the previous diagnostic name."""

        return self.path


class ValidationResult(NodeFlowModel):
    """All diagnostics from validating a workflow against node contracts."""

    issues: tuple[ValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def raise_for_errors(self) -> None:
        if self.issues:
            messages = "; ".join(issue.message for issue in self.issues)
            raise ValueError(f"workflow validation failed: {messages}")
