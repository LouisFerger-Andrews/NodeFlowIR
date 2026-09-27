from __future__ import annotations

import json

import pytest

from nodeflowir.ir import (
    BinaryExpression,
    FlowBlock,
    LiteralValue,
    LogicalExpression,
    NodeInstance,
    NodeStep,
    Workflow,
)
from nodeflowir.ir.values import BinaryOperator, LogicalOperator
from nodeflowir.serialization import (
    MigrationError,
    MigrationRegistry,
    workflow_from_json,
    workflow_to_json,
)


def _workflow() -> Workflow:
    return Workflow(
        id="example",
        workflow_version=12,
        name="Example",
        nodes=[NodeInstance(id="task", type="example.task", type_version="1.0.0")],
        body=FlowBlock(steps=[NodeStep(node_id="task")]),
        outputs={
            "ok": LogicalExpression(
                operator=LogicalOperator.AND,
                operands=[
                    BinaryExpression(
                        operator=BinaryOperator.EQUAL,
                        left=LiteralValue(value="current"),
                        right=LiteralValue(value="current"),
                    ),
                    LiteralValue(value=True),
                ],
            )
        },
    )


def test_workflow_round_trips_stable_json() -> None:
    workflow = _workflow()

    assert workflow_from_json(workflow_to_json(workflow)) == workflow


def test_schema_migration_is_explicit_and_workflow_revision_is_independent() -> None:
    migrations = MigrationRegistry()
    migrations.register(
        "0.9",
        "1.0",
        lambda document: {
            **document,
            "schema_version": "1.0",
            "workflow_version": 12,
            "body": {"steps": [{"kind": "node", "node_id": "task"}]},
        },
    )
    old_document = {
        "schema_version": "0.9",
        "workflow_version": "legacy-revision",
        "id": "example",
        "name": "Example",
        "nodes": [{"id": "task", "type": "example.task", "type_version": "1.0.0"}],
    }

    workflow = workflow_from_json(json.dumps(old_document), migrations=migrations)

    assert workflow.schema_version == "1.0"
    assert workflow.workflow_version == 12
    with pytest.raises(MigrationError):
        workflow_from_json(json.dumps(old_document))
