"""Tests for the shared structured authoring context, without an AI runtime."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from nodeflowir.authoring import (
    build_authoring_context,
    validate_authored_workflow,
    workflow_json_schema,
)
from nodeflowir.catalog import build_workflow_catalog
from nodeflowir.ir import Workflow
from nodeflowir.ir.types import TypeSpec, ValueKind
from nodeflowir.nodes import (
    ConfigurationField,
    NodeDefinition,
    NodeRegistry,
    PortDefinition,
    Select,
)
from nodeflowir.validation import IssueCode


def _type(kind: ValueKind, **kwargs: object) -> TypeSpec:
    return TypeSpec(kind=kind, **kwargs)


def _registry() -> NodeRegistry:
    result = _type(
        ValueKind.OBJECT,
        fields={"id": _type(ValueKind.STRING), "status": _type(ValueKind.STRING)},
    )
    registry = NodeRegistry()
    registry.register(
        NodeDefinition(
            type="qa.test-suite",
            version="1.0",
            display_name="Test Suite",
            category="Testing",
            config=(
                ConfigurationField(
                    name="suite_id",
                    type=_type(ValueKind.STRING),
                    ui=Select(provider="test_management.suites"),
                ),
            ),
            outputs={"results": PortDefinition(type=_type(ValueKind.ARRAY, items=result))},
        )
    )
    registry.register(
        NodeDefinition(
            type="ticket.create",
            version="1.0",
            display_name="Create Ticket",
            category="Testing",
        )
    )
    return registry


def _provider_values() -> dict[str, list[dict[str, str]]]:
    return {
        "test_management.suites": [
            {"value": "suite_123", "label": "Regression Suite"},
            {"value": "suite_456", "label": "Smoke Tests"},
        ]
    }


def _workflow_payload(*, suite_id: str = "suite_123", node_type: str = "qa.test-suite") -> dict:
    return {
        "schema_version": "1.0",
        "workflow_version": 1,
        "id": "nightly-regression",
        "name": "Nightly Regression",
        "nodes": [
            {
                "id": "tests",
                "type": node_type,
                "type_version": "1.0",
                "config": {"suite_id": suite_id},
            },
            {"id": "ticket", "type": "ticket.create", "type_version": "1.0"},
        ],
        "body": {
            "steps": [
                {"kind": "node", "node_id": "tests"},
                {
                    "kind": "if",
                    "condition": {
                        "kind": "collection",
                        "operator": "any",
                        "collection": {
                            "kind": "node_output",
                            "node_id": "tests",
                            "output": "results",
                        },
                        "item_scope": "result",
                        "predicate": {
                            "kind": "binary",
                            "operator": "eq",
                            "left": {"kind": "loop_item", "loop_id": "result", "path": ["status"]},
                            "right": {"kind": "literal", "value": "failed"},
                        },
                    },
                    "then": {"steps": [{"kind": "node", "node_id": "ticket"}]},
                },
            ]
        },
    }


def test_canonical_workflow_json_schema_is_structured_and_discriminated() -> None:
    schema = workflow_json_schema()

    assert schema["title"] == "Workflow"
    flow_items = schema["$defs"]["FlowBlock"]["properties"]["steps"]["items"]
    assert flow_items["discriminator"]["propertyName"] == "kind"
    assert {"node", "if", "foreach", "parallel"}.issubset(flow_items["discriminator"]["mapping"])
    assert Workflow.model_json_schema(mode="validation")["$defs"].keys() == schema["$defs"].keys()


def test_authoring_context_serializes_catalog_schema_and_current_provider_values() -> None:
    catalog = build_workflow_catalog(node_registry=_registry())
    context = build_authoring_context(catalog=catalog, provider_values=_provider_values())
    payload = context.model_dump(mode="json")
    items = {item["id"] for item in payload["catalog"]["items"]}

    assert payload["ir_schema_version"] == "1.0"
    assert payload["workflow_schema"]["title"] == "Workflow"
    assert "node:qa.test-suite@1.0" in items
    assert "control_flow:if" in items
    assert "collection_operation:any" in items
    assert payload["provider_values"] == [
        {
            "provider": "test_management.suites",
            "options": [
                {
                    "value": "suite_123",
                    "label": "Regression Suite",
                    "description": None,
                    "disabled": False,
                    "metadata": {},
                },
                {
                    "value": "suite_456",
                    "label": "Smoke Tests",
                    "description": None,
                    "disabled": False,
                    "metadata": {},
                },
            ],
        }
    ]
    assert payload["authoring_constraints"]["arbitrary_code_prohibited"] is True
    assert (
        json.loads(json.dumps(payload))["provider_values"][0]["options"][0]["value"] == "suite_123"
    )


def test_context_reuses_visual_catalog_and_can_be_filtered() -> None:
    catalog = build_workflow_catalog(node_registry=_registry())
    full_context = build_authoring_context(catalog=catalog, provider_values=_provider_values())
    filtered_context = build_authoring_context(
        catalog=catalog,
        provider_values=_provider_values(),
        categories=("Testing", "Logic"),
    )

    assert [item.id for item in full_context.catalog.items] == [item.id for item in catalog.items]
    assert "node:qa.test-suite@1.0" in {item.id for item in full_context.catalog.items}
    assert "control_flow:if" in {item.id for item in full_context.catalog.items}
    assert "collection_operation:any" in {item.id for item in full_context.catalog.items}
    assert {item.category for item in filtered_context.catalog.items} <= {"Testing", "Logic"}
    assert filtered_context.provider_values[0].provider == "test_management.suites"
    with pytest.raises(ValueError, match="not available"):
        build_authoring_context(catalog=catalog, item_ids=("node:missing@1.0",))
    with pytest.raises(ValueError, match="not referenced"):
        build_authoring_context(catalog=catalog, provider_values={"agents.available": []})


def test_test_management_ai_shaped_workflow_uses_stable_provider_value_and_normal_validation() -> (
    None
):
    registry = _registry()
    context = build_authoring_context(
        catalog=build_workflow_catalog(node_registry=registry),
        provider_values=_provider_values(),
    )
    workflow = Workflow.model_validate(_workflow_payload())

    assert workflow.nodes[0].config["suite_id"] == "suite_123"
    assert validate_authored_workflow(workflow, registry=registry, context=context).is_valid
    assert validate_authored_workflow(workflow, registry=registry).is_valid


def test_invalid_authored_workflows_use_structured_canonical_diagnostics() -> None:
    registry = _registry()
    context = build_authoring_context(
        catalog=build_workflow_catalog(node_registry=registry),
        provider_values=_provider_values(),
    )
    stale_suite = Workflow.model_validate(_workflow_payload(suite_id="suite_999"))
    dynamic_result = validate_authored_workflow(stale_suite, registry=registry, context=context)
    dynamic_issue = next(
        issue
        for issue in dynamic_result.issues
        if issue.code is IssueCode.INVALID_DYNAMIC_PROVIDER_VALUE
    )

    assert dynamic_issue.model_dump(mode="json") == {
        "code": "invalid_dynamic_provider_value",
        "message": (
            "configuration 'tests.suite_id' must use a current stable value from provider "
            "'test_management.suites'"
        ),
        "path": ["nodes", 0, "config", "suite_id"],
        "expected": "a stable value from provider 'test_management.suites'",
        "received": "suite_999",
    }

    unknown_node = Workflow.model_validate(_workflow_payload(node_type="qa.unknown"))
    static_result = validate_authored_workflow(unknown_node, registry=registry)
    assert IssueCode.UNKNOWN_NODE_DEFINITION in {issue.code for issue in static_result.issues}
    assert any(issue.path == ("nodes", 0) for issue in static_result.issues)

    malformed = deepcopy(_workflow_payload())
    malformed["generated_python"] = "import os"
    with pytest.raises(ValidationError):
        Workflow.model_validate(malformed)
