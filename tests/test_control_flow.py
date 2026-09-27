from __future__ import annotations

from nodeflowir.ir import (
    BreakStep,
    DataConnection,
    FlowBlock,
    ForeachStep,
    LiteralValue,
    LoopItemReference,
    NodeInstance,
    NodeStep,
    PortAddress,
    RepeatStep,
    Workflow,
    WorkflowInput,
    WorkflowInputReference,
)
from nodeflowir.ir.control_flow import (
    ErrorCategory,
    ErrorFlow,
    MatchCase,
    MatchStep,
    ParallelBranch,
    ParallelStep,
)
from nodeflowir.ir.types import TypeSpec, ValueKind
from nodeflowir.validation import IssueCode, validate_workflow


def test_validates_foreach_current_item_and_bounded_repeat(registry) -> None:
    workflow = Workflow(
        id="deploy-targets",
        workflow_version=3,
        name="Deploy targets",
        inputs={
            "targets": WorkflowInput(
                type=TypeSpec(kind=ValueKind.ARRAY, items=TypeSpec(kind=ValueKind.STRING))
            )
        },
        nodes=[NodeInstance(id="deploy", type="deploy.apply", type_version="1.0.0")],
        connections=[
            DataConnection(
                target=PortAddress(node_id="deploy", port="target"),
                value=LoopItemReference(loop_id="target"),
            )
        ],
        body=FlowBlock(
            steps=[
                ForeachStep(
                    id="target",
                    collection=WorkflowInputReference(name="targets"),
                    body=FlowBlock(
                        steps=[
                            RepeatStep(
                                id="retry-window",
                                times=3,
                                body=FlowBlock(steps=[NodeStep(node_id="deploy")]),
                            )
                        ]
                    ),
                )
            ]
        ),
    )

    assert validate_workflow(workflow, registry).is_valid


def test_rejects_break_outside_a_bounded_loop(registry) -> None:
    workflow = Workflow(
        id="bad-break",
        workflow_version=1,
        name="Bad break",
        nodes=[NodeInstance(id="deploy", type="deploy.apply", type_version="1.0.0")],
        connections=[
            DataConnection(
                target=PortAddress(node_id="deploy", port="target"),
                value=LiteralValue(value="prod"),
            )
        ],
        body=FlowBlock(steps=[BreakStep(), NodeStep(node_id="deploy")]),
    )

    codes = {issue.code for issue in validate_workflow(workflow, registry).issues}

    assert IssueCode.INVALID_LOOP_CONTROL in codes


def test_validates_match_parallel_fan_in_and_error_flow(registry) -> None:
    workflow = Workflow(
        id="structured-control",
        workflow_version=4,
        name="Structured control",
        nodes=[
            NodeInstance(id="first", type="utility.first", type_version="1.0.0"),
            NodeInstance(id="second", type="utility.second", type_version="1.0.0"),
            NodeInstance(id="third", type="utility.third", type_version="1.0.0"),
            NodeInstance(id="fourth", type="utility.fourth", type_version="1.0.0"),
            NodeInstance(id="fifth", type="utility.fifth", type_version="1.0.0"),
        ],
        body=FlowBlock(
            steps=[
                MatchStep(
                    subject=LiteralValue(value="production"),
                    cases=[
                        MatchCase(
                            value=LiteralValue(value="production"),
                            body=FlowBlock(
                                steps=[
                                    NodeStep(
                                        node_id="first",
                                        on_error=ErrorFlow(
                                            categories=(ErrorCategory.TIMEOUT,),
                                            body=FlowBlock(steps=[NodeStep(node_id="third")]),
                                        ),
                                    )
                                ]
                            ),
                        )
                    ],
                    default=FlowBlock(steps=[NodeStep(node_id="second")]),
                ),
                ParallelStep(
                    id="fan-out",
                    convergence="all",
                    branches=[
                        ParallelBranch(
                            id="left", body=FlowBlock(steps=[NodeStep(node_id="fourth")])
                        ),
                        ParallelBranch(
                            id="right", body=FlowBlock(steps=[NodeStep(node_id="fifth")])
                        ),
                    ],
                ),
            ]
        ),
    )

    assert validate_workflow(workflow, registry).is_valid
