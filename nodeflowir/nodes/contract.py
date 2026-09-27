"""Node definition contracts, independent from application implementations."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, JsonValue, model_validator

from nodeflowir._model import NodeFlowModel
from nodeflowir.ir.types import NodeTypeId, PortName, SemanticVersion, TypeSpec
from nodeflowir.nodes.fields import BindingId, ConfigurationField

ContractName = Annotated[str, Field(min_length=1, max_length=200)]


class PortDefinition(NodeFlowModel):
    """The contract for one named input or output port."""

    type: TypeSpec
    required: bool = True
    description: str | None = None
    ui: dict[str, JsonValue] = Field(default_factory=dict)


class NodeDefinition(NodeFlowModel):
    """A versioned declaration of what a node type accepts and produces.

    It deliberately contains no callable implementation, credentials, or
    integration details.  Applications own those concerns.
    """

    type: NodeTypeId
    version: SemanticVersion
    display_name: ContractName | None = None
    description: str | None = None
    category: str | None = None
    inputs: dict[PortName, PortDefinition] = Field(default_factory=dict)
    outputs: dict[PortName, PortDefinition] = Field(default_factory=dict)
    config: tuple[ConfigurationField, ...] = ()
    handler: BindingId | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    ui: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_configuration_names(self) -> NodeDefinition:
        names = [field.name for field in self.config]
        if len(names) != len(set(names)):
            raise ValueError("node configuration field names must be unique")
        return self

    def metadata_document(self) -> dict[str, object]:
        """Return the framework-neutral, JSON-compatible node metadata shape."""

        return self.model_dump(mode="json")
