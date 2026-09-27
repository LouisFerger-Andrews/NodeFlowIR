from __future__ import annotations

import pytest

from nodeflowir.ir.types import TypeSpec, ValueKind
from nodeflowir.nodes import NodeDefinition, NodeRegistry, PortDefinition


def scalar(kind: ValueKind) -> TypeSpec:
    return TypeSpec(kind=kind)


@pytest.fixture
def registry() -> NodeRegistry:
    result_item = TypeSpec(
        kind=ValueKind.OBJECT,
        fields={
            "id": scalar(ValueKind.STRING),
            "status": scalar(ValueKind.STRING),
            "severity": scalar(ValueKind.INTEGER),
            "passed": scalar(ValueKind.BOOLEAN),
        },
    )
    registry = NodeRegistry()
    registry.register(
        NodeDefinition(
            type="qa.test-suite",
            version="1.0.0",
            inputs={"repository": PortDefinition(type=scalar(ValueKind.STRING))},
            outputs={
                "results": PortDefinition(type=TypeSpec(kind=ValueKind.ARRAY, items=result_item))
            },
        )
    )
    registry.register(
        NodeDefinition(
            type="tickets.create",
            version="1.0.0",
            inputs={"failed_count": PortDefinition(type=scalar(ValueKind.INTEGER))},
            outputs={"ticket_id": PortDefinition(type=scalar(ValueKind.STRING))},
        )
    )
    registry.register(
        NodeDefinition(
            type="reports.create",
            version="1.0.0",
            inputs={"all_passed": PortDefinition(type=scalar(ValueKind.BOOLEAN))},
        )
    )
    registry.register(
        NodeDefinition(
            type="deploy.apply",
            version="1.0.0",
            inputs={"target": PortDefinition(type=scalar(ValueKind.STRING))},
        )
    )
    registry.register(
        NodeDefinition(
            type="data.consume",
            version="1.0.0",
            inputs={"value": PortDefinition(type=scalar(ValueKind.OBJECT))},
        )
    )
    for type_id in (
        "utility.first",
        "utility.second",
        "utility.third",
        "utility.fourth",
        "utility.fifth",
    ):
        registry.register(NodeDefinition(type=type_id, version="1.0.0"))
    return registry
