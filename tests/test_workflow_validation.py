from __future__ import annotations

from nodeflowir.ir import (
    AggregationExpression,
    BinaryExpression,
    CollectionExpression,
    DataConnection,
    FlowBlock,
    IfStep,
    LiteralValue,
    LogicalExpression,
    LoopItemReference,
    NodeInstance,
    NodeOutputReference,
    NodeStep,
    PortAddress,
    Workflow,
)
from nodeflowir.ir.values import (
    AggregationOperator,
    BinaryOperator,
    CollectionOperator,
    LogicalOperator,
)
from nodeflowir.validation import IssueCode, validate_workflow


def _failed_and_severe(scope: str) -> LogicalExpression:
    return LogicalExpression(
        operator=LogicalOperator.AND,
        operands=[
            BinaryExpression(
                operator=BinaryOperator.EQUAL,
                left=LoopItemReference(loop_id=scope, path=("status",)),
                right=LiteralValue(value="failed"),
            ),
            BinaryExpression(
                operator=BinaryOperator.GREATER_THAN_OR_EQUAL,
                left=LoopItemReference(loop_id=scope, path=("severity",)),
                right=LiteralValue(value=3),
            ),
        ],
    )


def test_validates_a_linear_workflow_with_branching_and_collection_logic(registry) -> None:
    failures = _failed_and_severe("test")
    results = NodeOutputReference(node_id="run-tests", output="results")
    failed_count = AggregationExpression(
        operator=AggregationOperator.COUNT,
        collection=results,
        item_scope="test",
        predicate=failures,
    )
    any_failure = CollectionExpression(
        operator=CollectionOperator.ANY,
        collection=results,
        item_scope="test",
        predicate=failures,
    )
    all_passed = CollectionExpression(
        operator=CollectionOperator.ALL,
        collection=results,
        item_scope="test",
        predicate=BinaryExpression(
            operator=BinaryOperator.EQUAL,
            left=LoopItemReference(loop_id="test", path=("passed",)),
            right=LiteralValue(value=True),
        ),
    )
    workflow = Workflow(
        id="nightly-tests",
        workflow_version=12,
        name="Nightly Tests",
        nodes=[
            NodeInstance(id="run-tests", type="qa.test-suite", type_version="1.0.0"),
            NodeInstance(id="create-ticket", type="tickets.create", type_version="1.0.0"),
            NodeInstance(id="create-report", type="reports.create", type_version="1.0.0"),
        ],
        connections=[
            DataConnection(
                target=PortAddress(node_id="run-tests", port="repository"),
                value=LiteralValue(value="service-api"),
            ),
            DataConnection(
                target=PortAddress(node_id="create-ticket", port="failed_count"),
                value=failed_count,
            ),
            DataConnection(
                target=PortAddress(node_id="create-report", port="all_passed"),
                value=all_passed,
            ),
        ],
        body=FlowBlock(
            steps=[
                NodeStep(node_id="run-tests"),
                IfStep(
                    condition=any_failure,
                    then=FlowBlock(steps=[NodeStep(node_id="create-ticket")]),
                    else_body=FlowBlock(steps=[NodeStep(node_id="create-report")]),
                ),
            ]
        ),
        outputs={"failed_count": failed_count},
    )

    assert validate_workflow(workflow, registry).is_valid


def test_rejects_unknown_output_invalid_operator_and_incompatible_input(registry) -> None:
    workflow = Workflow(
        id="invalid-values",
        workflow_version=1,
        name="Invalid values",
        nodes=[
            NodeInstance(id="run-tests", type="qa.test-suite", type_version="1.0.0"),
            NodeInstance(id="create-ticket", type="tickets.create", type_version="1.0.0"),
        ],
        connections=[
            DataConnection(
                target=PortAddress(node_id="run-tests", port="repository"),
                value=LiteralValue(value="service-api"),
            ),
            DataConnection(
                target=PortAddress(node_id="create-ticket", port="failed_count"),
                value=LiteralValue(value="not-an-integer"),
            ),
        ],
        body=FlowBlock(steps=[NodeStep(node_id="run-tests"), NodeStep(node_id="create-ticket")]),
        outputs={
            "invalid_arithmetic": BinaryExpression(
                operator=BinaryOperator.ADD,
                left=LiteralValue(value="not-a-number"),
                right=LiteralValue(value=1),
            ),
            "missing": NodeOutputReference(node_id="run-tests", output="unknown"),
        },
    )

    codes = {issue.code for issue in validate_workflow(workflow, registry).issues}

    assert IssueCode.INVALID_EXPRESSION_OPERATOR in codes
    assert IssueCode.INCOMPATIBLE_VALUE_TYPE in codes
    assert IssueCode.UNKNOWN_NODE_OUTPUT in codes
