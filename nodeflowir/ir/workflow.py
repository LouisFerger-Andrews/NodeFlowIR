"""The top-level, canonical NodeFlowIR workflow document."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, JsonValue, model_validator

from nodeflowir._model import NodeFlowModel
from nodeflowir.ir.control_flow import FlowBlock
from nodeflowir.ir.edge import DataConnection
from nodeflowir.ir.node import NodeInstance
from nodeflowir.ir.types import Identifier, PortName, TypeSpec
from nodeflowir.ir.values import LiteralValue, Value

CURRENT_SCHEMA_VERSION = "1.0"
MAX_WORKFLOW_NODES = 1_000
MAX_WORKFLOW_CONNECTIONS = 5_000
MAX_WORKFLOW_NESTING_DEPTH = 64


class WorkflowInput(NodeFlowModel):
    """A typed value supplied by the caller when starting a workflow."""

    type: TypeSpec
    required: bool = True
    default: LiteralValue | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _check_default(self) -> WorkflowInput:
        if self.default is not None:
            if self.required:
                raise ValueError("a workflow input with a default must not be required")
            literal_type = self.default.type
            if literal_type is not None and not literal_type.is_assignable_to(self.type):
                raise ValueError("workflow input default type is not compatible with input type")
            if literal_type is None and not self.type.accepts(self.default.value):
                raise ValueError("workflow input default does not match input type")
        return self


class WorkflowConstant(NodeFlowModel):
    """A named, typed literal available to values throughout the workflow."""

    type: TypeSpec
    value: LiteralValue
    description: str | None = None

    @model_validator(mode="after")
    def _check_value(self) -> WorkflowConstant:
        if self.value.type is not None and not self.value.type.is_assignable_to(self.type):
            raise ValueError("constant literal type is not compatible with constant type")
        if self.value.type is None and not self.type.accepts(self.value.value):
            raise ValueError("constant literal does not match constant type")
        return self


class Workflow(NodeFlowModel):
    """A versioned workflow definition represented independently of any UI."""

    schema_version: Literal["1.0"] = CURRENT_SCHEMA_VERSION
    workflow_version: int = Field(ge=1)
    id: Identifier
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    inputs: dict[PortName, WorkflowInput] = Field(default_factory=dict, max_length=256)
    constants: dict[Identifier, WorkflowConstant] = Field(default_factory=dict, max_length=256)
    nodes: list[NodeInstance] = Field(min_length=1, max_length=MAX_WORKFLOW_NODES)
    connections: list[DataConnection] = Field(
        default_factory=list, max_length=MAX_WORKFLOW_CONNECTIONS
    )
    body: FlowBlock
    outputs: dict[PortName, Value] = Field(default_factory=dict, max_length=256)
    metadata: dict[str, JsonValue] = Field(default_factory=dict, max_length=256)

    @property
    def workflow_id(self) -> str:
        """Stable identity alias for ``id``, retained for schema-1.0 compatibility.

        The wire field remains ``id`` in schema 1.0.  Governance contracts use
        the clearer ``workflow_id`` spelling because they often travel outside
        the semantic workflow document.
        """

        return self.id

    @model_validator(mode="after")
    def _require_unique_node_ids(self) -> Workflow:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("workflow node ids must be unique")
        if _maximum_depth(self) > MAX_WORKFLOW_NESTING_DEPTH:
            raise ValueError(f"workflow nesting depth must not exceed {MAX_WORKFLOW_NESTING_DEPTH}")
        return self


def _maximum_depth(value: object, depth: int = 0) -> int:
    """Calculate model/document nesting without evaluating workflow semantics."""

    if isinstance(value, BaseModel):
        children = (getattr(value, name) for name in value.__class__.model_fields)
    elif isinstance(value, dict):
        children = value.values()
    elif isinstance(value, (list, tuple)):
        children = iter(value)
    else:
        return depth
    return max((depth, *(_maximum_depth(child, depth + 1) for child in children)), default=depth)
