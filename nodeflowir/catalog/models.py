"""Frontend-neutral, serializable workflow catalog contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, JsonValue, model_validator

from nodeflowir._model import NodeFlowModel
from nodeflowir.ir.types import PortName, SemanticVersion, TypeSpec, ValueKind
from nodeflowir.nodes.fields import BindingId, FieldConstraints, FieldUI


class CatalogItemKind(StrEnum):
    """Semantic families displayed together by a workflow-builder menu."""

    NODE = "node"
    CONTROL_FLOW = "control_flow"
    EXPRESSION = "expression"
    COLLECTION_OPERATION = "collection_operation"
    TRANSFORMATION = "transformation"
    AGGREGATION = "aggregation"
    VALUE = "value"
    EXECUTION_POLICY = "execution_policy"


class CatalogFieldType(StrEnum):
    """Semantic editors a frontend may provide for configuration fields."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    DURATION = "duration"
    LITERAL = "literal"
    ENUM = "enum"
    EXPRESSION = "expression"
    REFERENCE = "reference"
    NODE_OUTPUT_REFERENCE = "node_output_reference"
    COLLECTION_REFERENCE = "collection_reference"
    FIELD_REFERENCE = "field_reference"
    DYNAMIC_SELECT = "dynamic_select"
    MULTI_SELECT = "multi_select"
    OBJECT = "object"
    LIST = "list"
    TYPE_SPEC = "type_spec"


class CatalogPortKind(StrEnum):
    CONTROL = "control"
    DATA = "data"


class PortDirection(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class PortCardinality(StrEnum):
    ONE = "one"
    MANY = "many"


CatalogName = Annotated[str, Field(min_length=1, max_length=200)]


class CatalogPort(NodeFlowModel):
    """A connectable structural port, without frontend layout or styling."""

    id: CatalogName
    label: CatalogName | None = None
    kind: CatalogPortKind
    direction: PortDirection
    cardinality: PortCardinality = PortCardinality.ONE
    required: bool = True
    data_type: TypeSpec | None = None
    dynamic: bool = False
    description: str | None = None
    ui: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_shape(self) -> CatalogPort:
        if self.kind is CatalogPortKind.CONTROL and self.data_type is not None:
            raise ValueError("a control port cannot declare a data_type")
        if self.kind is CatalogPortKind.DATA and self.data_type is None:
            raise ValueError("a data port requires a data_type")
        if self.direction is PortDirection.OUTPUT and self.required:
            raise ValueError("an output port cannot be required")
        if self.dynamic and self.direction is not PortDirection.OUTPUT:
            raise ValueError("only output ports may be dynamic")
        return self


class CatalogConfigurationField(NodeFlowModel):
    """A semantic configuration contract a backend can expose to any frontend."""

    type: CatalogFieldType
    required: bool = True
    description: str | None = None
    data_type: TypeSpec | None = None
    default: JsonValue | None = None
    has_default: bool = False
    enum_values: tuple[JsonValue, ...] | None = None
    provider: BindingId | None = None
    constraints: FieldConstraints | None = None
    ui: FieldUI | None = None
    capabilities: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_shape(self) -> CatalogConfigurationField:
        if self.has_default and self.required:
            raise ValueError("a configuration field with a default must not be required")
        if not self.has_default and self.default is not None:
            raise ValueError("default requires has_default=True")
        dynamic_types = {CatalogFieldType.DYNAMIC_SELECT, CatalogFieldType.MULTI_SELECT}
        if self.provider is not None and self.type not in dynamic_types:
            raise ValueError("a provider is only valid for dynamic_select or multi_select")
        if self.type in dynamic_types and self.provider is None:
            raise ValueError("a dynamic select field requires a provider reference")
        if self.type is CatalogFieldType.ENUM and not self.enum_values:
            raise ValueError("an enum configuration field requires enum_values")
        if self.enum_values is not None and self.type is not CatalogFieldType.ENUM:
            raise ValueError("enum_values are only valid for enum configuration fields")
        if (
            self.data_type is not None
            and self.has_default
            and not self.data_type.accepts(self.default)
        ):
            raise ValueError("configuration default does not match data_type")
        return self


class BranchDefinition(NodeFlowModel):
    """Metadata for dynamically configurable control-flow branches."""

    dynamic: bool = False
    minimum_branches: int | None = Field(default=None, ge=1)
    maximum_branches: int | None = Field(default=None, ge=1)
    branch_port_kind: CatalogPortKind = CatalogPortKind.CONTROL
    branch_config_schema: dict[PortName, CatalogConfigurationField] = Field(default_factory=dict)
    default_branch: bool = False

    @model_validator(mode="after")
    def _check_shape(self) -> BranchDefinition:
        if not self.dynamic and (
            self.minimum_branches is not None
            or self.maximum_branches is not None
            or self.branch_config_schema
            or self.default_branch
        ):
            raise ValueError("branch details require dynamic=True")
        if (
            self.minimum_branches is not None
            and self.maximum_branches is not None
            and self.minimum_branches > self.maximum_branches
        ):
            raise ValueError("minimum_branches cannot exceed maximum_branches")
        return self


class WorkflowCatalogItem(NodeFlowModel):
    """One discoverable building block for a visual workflow authoring tool."""

    id: CatalogName
    kind: CatalogItemKind
    type: CatalogName
    version: SemanticVersion | None = None
    display_name: CatalogName
    description: str | None = None
    category: CatalogName
    configuration_schema: dict[PortName, CatalogConfigurationField] = Field(default_factory=dict)
    input_ports: tuple[CatalogPort, ...] = ()
    output_ports: tuple[CatalogPort, ...] = ()
    branch_definition: BranchDefinition | None = None
    capabilities: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_shape(self) -> WorkflowCatalogItem:
        ports = (*self.input_ports, *self.output_ports)
        port_ids = [port.id for port in ports]
        if len(port_ids) != len(set(port_ids)):
            raise ValueError("catalog port ids must be unique within an item")
        if any(port.direction is not PortDirection.INPUT for port in self.input_ports):
            raise ValueError("input_ports must use input direction")
        if any(port.direction is not PortDirection.OUTPUT for port in self.output_ports):
            raise ValueError("output_ports must use output direction")
        if any(port.dynamic for port in self.input_ports):
            raise ValueError("input ports cannot be dynamic")
        if self.kind is CatalogItemKind.CONTROL_FLOW and not any(
            port.kind is CatalogPortKind.CONTROL for port in self.input_ports
        ):
            raise ValueError("a control-flow item requires an input control port")
        dynamic_outputs = tuple(port for port in self.output_ports if port.dynamic)
        if dynamic_outputs and self.branch_definition is None:
            raise ValueError("dynamic output ports require a branch definition")
        if self.branch_definition is not None and not any(
            port.kind is CatalogPortKind.CONTROL for port in ports
        ):
            raise ValueError("branch definitions require at least one control port")
        if self.branch_definition is not None and self.branch_definition.dynamic:
            if not dynamic_outputs:
                raise ValueError("a dynamic branch definition requires a dynamic output port")
            if any(
                port.kind is not self.branch_definition.branch_port_kind for port in dynamic_outputs
            ):
                raise ValueError("dynamic output port kind must match the branch definition")
        return self


class WorkflowCatalog(NodeFlowModel):
    """The complete serializable catalog a backend may expose through its API."""

    schema_version: str = "1.0"
    items: tuple[WorkflowCatalogItem, ...]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> WorkflowCatalog:
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("catalog item ids must be unique")
        return self

    def by_kind(self, kind: CatalogItemKind) -> tuple[WorkflowCatalogItem, ...]:
        """Return deterministically ordered entries in one semantic family."""

        return tuple(item for item in self.items if item.kind is kind)


def catalog_type_for_value_kind(kind: ValueKind) -> CatalogFieldType:
    """Choose the most useful generic frontend field editor for a portable type."""

    mapping = {
        ValueKind.STRING: CatalogFieldType.STRING,
        ValueKind.INTEGER: CatalogFieldType.INTEGER,
        ValueKind.NUMBER: CatalogFieldType.NUMBER,
        ValueKind.BOOLEAN: CatalogFieldType.BOOLEAN,
        ValueKind.DATE: CatalogFieldType.DATE,
        ValueKind.DATETIME: CatalogFieldType.DATETIME,
        ValueKind.DURATION: CatalogFieldType.DURATION,
        ValueKind.ARRAY: CatalogFieldType.LIST,
        ValueKind.OBJECT: CatalogFieldType.OBJECT,
    }
    return mapping.get(kind, CatalogFieldType.LITERAL)


def ports_are_compatible(source: CatalogPort, target: CatalogPort) -> bool:
    """Return whether an output port may connect to an input port.

    This is deliberately structural.  It checks port direction, port family,
    and portable ``TypeSpec`` assignability; it does not infer control-flow
    reachability or replace full workflow validation.
    """

    if source.direction is not PortDirection.OUTPUT or target.direction is not PortDirection.INPUT:
        return False
    if source.kind is not target.kind:
        return False
    if source.kind is CatalogPortKind.CONTROL:
        return True
    assert source.data_type is not None
    assert target.data_type is not None
    return source.data_type.is_assignable_to(target.data_type)
