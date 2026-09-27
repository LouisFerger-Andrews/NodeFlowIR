"""Explicit data-flow bindings between workflow values and node inputs."""

from __future__ import annotations

from pydantic import Field, JsonValue

from nodeflowir._model import NodeFlowModel
from nodeflowir.ir.types import Identifier, PortName
from nodeflowir.ir.values import Value


class PortAddress(NodeFlowModel):
    """A named port on a configured node instance."""

    node_id: Identifier
    port: PortName


class DataConnection(NodeFlowModel):
    """Bind a typed literal, reference, or expression to one node input.

    A connection has a target rather than a source-only graph edge because the
    source may be a nested transformation, object construction, or fallback
    expression.  A ``node_output`` value remains an explicit node-to-node
    connection without duplicating that reference in a separate edge list.
    """

    target: PortAddress
    value: Value
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
