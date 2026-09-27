"""Tests for generic frontend presentation metadata in the unified catalog."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nodeflowir.catalog import (
    CatalogItemKind,
    CatalogPort,
    CatalogPortKind,
    CatalogPortRole,
    CatalogPresentation,
    PortDirection,
    RendererKind,
    VisualMode,
    WorkflowCatalogItem,
    build_workflow_catalog,
)
from nodeflowir.dsl import compile_dsl
from nodeflowir.ir import Workflow
from nodeflowir.ir.types import TypeSpec, ValueKind
from nodeflowir.nodes import NodeDefinition, NodeRegistry


def _catalog() -> tuple[NodeRegistry, dict[str, WorkflowCatalogItem]]:
    registry = NodeRegistry()
    registry.register(
        NodeDefinition(
            type="qa.test-suite",
            version="1.0",
            display_name="Test Suite",
            category="Testing",
            icon="flask-conical",
            search_terms=("quality", "regression"),
            handler="test_management.run_suite",
        )
    )
    registry.register(NodeDefinition(type="utility.noop", version="1.0"))
    catalog = build_workflow_catalog(node_registry=registry)
    return registry, {item.id: item for item in catalog.items}


def test_normal_custom_nodes_have_standard_canvas_presentation_defaults() -> None:
    _, items = _catalog()
    test_suite = items["node:qa.test-suite@1.0"]
    default_node = items["node:utility.noop@1.0"]

    assert test_suite.visual_mode is VisualMode.CANVAS
    assert test_suite.presentation is not None
    assert test_suite.presentation.renderer is RendererKind.STANDARD
    assert test_suite.presentation.icon == "flask-conical"
    assert test_suite.presentation.search_terms == ("quality", "regression")
    assert test_suite.behavior.supports_retry
    assert test_suite.behavior.supports_timeout
    assert test_suite.behavior.supports_error_path
    assert default_node.presentation is not None
    assert default_node.presentation.renderer is RendererKind.STANDARD
    assert default_node.presentation.category == "General"
    assert default_node.presentation.icon is None


def test_control_flow_presentation_is_renderer_and_port_role_driven() -> None:
    _, items = _catalog()

    if_item = items["control_flow:if"]
    assert if_item.visual_mode is VisualMode.CANVAS
    assert if_item.presentation is not None
    assert if_item.presentation.renderer is RendererKind.BRANCH
    assert if_item.presentation.icon == "git-branch"
    assert [port.role for port in if_item.output_ports] == [
        CatalogPortRole.TRUE,
        CatalogPortRole.FALSE,
    ]

    match = items["control_flow:match"]
    assert match.presentation is not None
    assert match.presentation.renderer is RendererKind.SWITCH
    assert match.branch_definition is not None
    assert match.branch_definition.dynamic
    assert match.branch_definition.branch_id_template == "case_{index}"
    assert match.branch_definition.label_template == "Case {value}"
    assert match.branch_definition.default_branch
    assert [port.role for port in match.output_ports] == [
        CatalogPortRole.DEFAULT_CASE,
        CatalogPortRole.CASE,
    ]

    foreach = items["control_flow:foreach"]
    repeat = items["control_flow:repeat"]
    assert foreach.presentation is not None
    assert foreach.presentation.renderer is RendererKind.LOOP
    assert [port.role for port in foreach.output_ports] == [
        CatalogPortRole.EACH,
        CatalogPortRole.COMPLETED,
    ]
    assert repeat.presentation is not None
    assert repeat.presentation.renderer is RendererKind.LOOP
    assert repeat.behavior.supports_nested_content

    parallel = items["control_flow:parallel"]
    assert parallel.presentation is not None
    assert parallel.presentation.renderer is RendererKind.PARALLEL
    assert parallel.behavior.supports_dynamic_branches
    assert parallel.branch_definition is not None
    assert parallel.branch_definition.minimum_branches == 2
    assert parallel.branch_definition.branch_id_template == "branch_{index}"
    assert [port.role for port in parallel.output_ports] == [
        CatalogPortRole.BRANCH,
        CatalogPortRole.COMPLETED,
    ]


def test_terminal_and_configuration_capabilities_do_not_need_type_specific_canvas_nodes() -> None:
    _, items = _catalog()

    for type_id in ("break", "continue"):
        item = items[f"control_flow:{type_id}"]
        assert item.visual_mode is VisualMode.CANVAS
        assert item.presentation is not None
        assert item.presentation.renderer is RendererKind.TERMINAL
        assert item.behavior.terminal

    for item_id in (
        "expression:eq",
        "collection_operation:filter",
        "transformation:sort_by",
        "aggregation:avg",
        "value:object",
        "execution_policy:retry",
        "control_flow:error_flow",
    ):
        item = items[item_id]
        assert item.visual_mode is VisualMode.CONFIGURATION
        assert item.presentation is not None
        assert item.presentation.renderer is None

    assert items["control_flow:error_flow"].behavior.supports_nested_content


def test_every_catalog_item_has_complete_generic_presentation_metadata() -> None:
    registry, _ = _catalog()
    catalog = build_workflow_catalog(node_registry=registry)
    serialized = {item["id"]: item for item in catalog.model_dump(mode="json")["items"]}

    known_renderers = set(RendererKind)
    for item in catalog.items:
        assert item.presentation is not None
        assert item.presentation.name
        assert item.presentation.category
        if item.kind is not CatalogItemKind.NODE:
            assert item.presentation.icon
        if item.visual_mode is VisualMode.CANVAS:
            assert item.presentation.renderer in known_renderers
        else:
            assert item.presentation.renderer is None

    assert {item.type for item in catalog.by_visual_mode(VisualMode.CANVAS)} >= {
        "if",
        "match",
        "foreach",
        "parallel",
        "qa.test-suite",
    }
    assert serialized["control_flow:if"]["presentation"]["renderer"] == "branch"
    assert serialized["control_flow:match"]["branch_definition"]["branch_id_template"] == (
        "case_{index}"
    )


def test_presentation_and_port_models_reject_ambiguous_frontend_contracts() -> None:
    with pytest.raises(ValidationError, match="renderer"):
        CatalogPresentation(name="Bad", category="Tests", renderer="unknown")
    with pytest.raises(ValidationError, match="default semantic role"):
        CatalogPort(
            id="value",
            kind=CatalogPortKind.DATA,
            direction=PortDirection.INPUT,
            data_type=TypeSpec(kind=ValueKind.STRING),
            role=CatalogPortRole.TRUE,
        )
    with pytest.raises(ValidationError, match="canvas catalog items require a renderer"):
        WorkflowCatalogItem(
            id="bad-canvas",
            kind=CatalogItemKind.VALUE,
            type="bad",
            display_name="Bad",
            category="Tests",
            visual_mode=VisualMode.CANVAS,
            presentation=CatalogPresentation(name="Bad", category="Tests"),
        )


def test_dsl_creates_deterministic_ids_for_dynamic_match_and_parallel_branches() -> None:
    registry, _ = _catalog()
    workflow = compile_dsl(
        """
        nodeflow 1.0
        workflow BranchIds version 1 (environment: String) {
            match input.environment {
                case "development" { run utility.noop }
                case "production" { run utility.noop }
            }
            parallel {
                run utility.noop
                run utility.noop
            }
        }
        """,
        registry,
    )

    match_step, parallel_step = workflow.body.steps
    assert [case.id for case in match_step.cases] == ["case_1", "case_2"]
    assert [branch.id for branch in parallel_step.branches] == ["branch_1", "branch_2"]

    restored = Workflow.model_validate(workflow.model_dump(mode="json"))
    restored_match, restored_parallel = restored.body.steps
    assert [case.id for case in restored_match.cases] == ["case_1", "case_2"]
    assert [branch.id for branch in restored_parallel.branches] == ["branch_1", "branch_2"]
