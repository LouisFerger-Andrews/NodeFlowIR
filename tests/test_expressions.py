from __future__ import annotations

from nodeflowir.ir import (
    DataConnection,
    FlowBlock,
    LiteralValue,
    NodeInstance,
    NodeStep,
    PortAddress,
    Workflow,
)
from nodeflowir.ir.types import TypeSpec, ValueKind
from nodeflowir.ir.values import (
    AggregationExpression,
    AggregationOperator,
    ArrayValue,
    CollectionExpression,
    CollectionOperator,
    CompositionExpression,
    CompositionOperator,
    ConversionExpression,
    ObjectValue,
    UnaryExpression,
    UnaryOperator,
)
from nodeflowir.validation import IssueCode, validate_workflow


def test_validates_merge_concat_aggregation_and_explicit_conversion(registry) -> None:
    workflow = Workflow(
        id="reshape-data",
        workflow_version=1,
        name="Reshape data",
        nodes=[NodeInstance(id="consume", type="data.consume", type_version="1.0.0")],
        connections=[
            DataConnection(
                target=PortAddress(node_id="consume", port="value"),
                value=CompositionExpression(
                    operator=CompositionOperator.MERGE,
                    values=[
                        ObjectValue(fields={"environment": LiteralValue(value="prod")}),
                        ObjectValue(
                            fields={
                                "ids": CompositionExpression(
                                    operator=CompositionOperator.CONCAT,
                                    values=[
                                        ArrayValue(items=[LiteralValue(value="a")]),
                                        ArrayValue(items=[LiteralValue(value="b")]),
                                    ],
                                ),
                                "count": AggregationExpression(
                                    operator=AggregationOperator.COUNT,
                                    collection=ArrayValue(
                                        items=[LiteralValue(value=1), LiteralValue(value=2)]
                                    ),
                                ),
                                "enabled": ConversionExpression(
                                    value=LiteralValue(value="true"),
                                    target_type=TypeSpec(kind=ValueKind.BOOLEAN),
                                ),
                            }
                        ),
                    ],
                ),
            )
        ],
        body=FlowBlock(steps=[NodeStep(node_id="consume")]),
    )

    assert validate_workflow(workflow, registry).is_valid


def test_rejects_non_collection_filter_and_invalid_conversion(registry) -> None:
    invalid_filter = CollectionExpression(
        operator=CollectionOperator.FILTER,
        collection=LiteralValue(value="not-a-list"),
        item_scope="item",
        predicate=LiteralValue(value=True),
        mapper=None,
        fields=(),
        rename={},
        other=None,
        direction="ascending",
    )
    workflow = Workflow(
        id="invalid-transform",
        workflow_version=1,
        name="Invalid transform",
        nodes=[NodeInstance(id="consume", type="data.consume", type_version="1.0.0")],
        connections=[
            DataConnection(
                target=PortAddress(node_id="consume", port="value"),
                value=ObjectValue(
                    fields={
                        "bad_filter": invalid_filter,
                        "bad_conversion": ConversionExpression(
                            value=LiteralValue(value=True),
                            target_type=TypeSpec(kind=ValueKind.OBJECT),
                        ),
                        "empty": UnaryExpression(
                            operator=UnaryOperator.EMPTY, operand=LiteralValue(value=2)
                        ),
                    }
                ),
            )
        ],
        body=FlowBlock(steps=[NodeStep(node_id="consume")]),
    )

    codes = {issue.code for issue in validate_workflow(workflow, registry).issues}

    assert IssueCode.INVALID_COLLECTION_OPERATION in codes
    assert IssueCode.INVALID_CONVERSION in codes
    assert IssueCode.INVALID_EXPRESSION_OPERATOR in codes
