"""Integration-facade tests; no provider or handler is executed implicitly."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import BaseModel

from nodeflowir import (
    ConfigField,
    NodeFlow,
    NodeHandlerResolutionError,
    NodeInstance,
    Select,
    Workflow,
    WorkflowValidationError,
    node,
)
from nodeflowir.nodes import (
    NodeDefinition,
    UnknownBindingError,
)
from nodeflowir.serialization import MigrationError
from nodeflowir.validation import IssueCode


class SuiteResult(BaseModel):
    status: str


class SuiteOutput(BaseModel):
    results: list[SuiteResult]


@node(
    id="qa.test-suite",
    version="1.0",
    display_name="Test Suite",
    category="Testing",
    handler="test_management.run_suite",
)
class TestSuiteNode:
    suite_id: str = ConfigField(ui=Select(provider="test_management.suites"))
    output = SuiteOutput


@node(
    id="ticket.create",
    version="1.0",
    display_name="Create Ticket",
    category="Testing",
    handler="ticketing.create",
)
class CreateTicketNode:
    output = str


def _flow() -> NodeFlow:
    flow = NodeFlow()
    flow.register_node(TestSuiteNode)
    flow.register_node(CreateTicketNode)
    return flow


def _payload(*, suite_type: str = "qa.test-suite") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "workflow_version": 1,
        "id": "nightly-regression",
        "name": "Nightly Regression",
        "nodes": [
            {
                "id": "tests",
                "type": suite_type,
                "type_version": "1.0",
                "config": {"suite_id": "suite_123"},
            },
            {"id": "ticket", "type": "ticket.create", "type_version": "1.0"},
        ],
        "body": {
            "steps": [
                {"kind": "node", "node_id": "tests"},
                {"kind": "node", "node_id": "ticket"},
            ]
        },
    }


def test_facade_instances_keep_node_provider_and_handler_registries_isolated() -> None:
    first = _flow()
    second = NodeFlow()
    first.register_provider(
        "test_management.suites",
        lambda _: [{"value": "suite_123", "label": "Regression Suite"}],
    )

    assert first.nodes.node_types() == ("qa.test-suite", "ticket.create")
    assert second.nodes.node_types() == ()
    assert asyncio.run(first.resolve_provider("test_management.suites"))[0].value == "suite_123"
    with pytest.raises(UnknownBindingError):
        asyncio.run(second.resolve_provider("test_management.suites"))

    first.migrations.register(
        "0.9",
        "1.0",
        lambda document: {**document, "schema_version": "1.0"},
    )
    assert (
        first.migrations.migrate({"schema_version": "0.9"}, from_version="0.9", to_version="1.0")[
            "schema_version"
        ]
        == "1.0"
    )
    with pytest.raises(MigrationError, match="no migration path"):
        second.migrations.migrate({"schema_version": "0.9"}, from_version="0.9", to_version="1.0")


def test_end_to_end_consumer_handoff_stops_before_handler_execution() -> None:
    flow = _flow()
    calls: list[object] = []

    def run_suite(*_: object) -> None:
        calls.append("called")

    def create_ticket(*_: object) -> None:
        calls.append("ticket")

    flow.register_provider(
        "test_management.suites",
        lambda _: [
            {"value": "suite_123", "label": "Regression Suite"},
            {"value": "suite_456", "label": "Smoke Tests"},
        ],
    )
    flow.register_handler("test_management.run_suite", run_suite)
    flow.register_handler("ticketing.create", create_ticket)

    catalog = flow.build_catalog()
    workflow = flow.load_workflow(json.dumps(_payload()))
    options = asyncio.run(flow.resolve_provider("test_management.suites"))
    handler = flow.resolve_handler(workflow.nodes[0])

    assert "node:qa.test-suite@1.0" in {item.id for item in catalog.items}
    assert [option.value for option in options] == ["suite_123", "suite_456"]
    assert flow.validate(workflow).is_valid
    assert handler is run_suite
    assert calls == []


def test_facade_loads_canonical_json_and_exposes_structured_validation_diagnostics() -> None:
    flow = _flow()

    loaded = flow.load_workflow(_payload())
    assert isinstance(loaded, Workflow)
    assert loaded.model_dump(mode="json")["id"] == "nightly-regression"

    with pytest.raises(WorkflowValidationError) as error:
        flow.load_workflow(_payload(suite_type="qa.unknown"))
    issue = next(
        issue
        for issue in error.value.result.issues
        if issue.code is IssueCode.UNKNOWN_NODE_DEFINITION
    )
    assert issue.model_dump(mode="json")["path"] == ["nodes", 0]


def test_facade_compiles_and_formats_dsl_as_canonical_workflow() -> None:
    flow = _flow()
    source = """
nodeflow 1.0

workflow NightlyRegression version 1 {
    tests = run qa.test-suite@1.0
        with {
            suite_id = "suite_123"
        }
}
"""

    workflow = flow.parse_dsl(source)
    formatted = flow.format_dsl(workflow)

    assert isinstance(workflow, Workflow)
    assert workflow.nodes[0].config["suite_id"] == "suite_123"
    assert flow.parse_dsl(formatted) == workflow


def test_facade_builds_shared_authoring_context_and_uses_optional_dynamic_validation() -> None:
    flow = _flow()
    context = flow.build_authoring_context(
        provider_values={
            "test_management.suites": [
                {"value": "suite_123", "label": "Regression Suite"},
            ]
        }
    )
    workflow = Workflow.model_validate(_payload())

    assert "node:qa.test-suite@1.0" in {item.id for item in context.catalog.items}
    assert "control_flow:if" in {item.id for item in context.catalog.items}
    assert flow.validate_authored_workflow(workflow, authoring_context=context).is_valid


def test_handler_resolution_uses_exact_node_version_and_reports_missing_bindings() -> None:
    flow = NodeFlow()

    def first_handler() -> None:
        pass

    def second_handler() -> None:
        pass

    flow.register_node(NodeDefinition(type="qa.versioned", version="1.0", handler="qa.run.first"))
    flow.register_node(NodeDefinition(type="qa.versioned", version="2.0", handler="qa.run.second"))
    flow.register_handler("qa.run.first", first_handler)
    flow.register_handler("qa.run.second", second_handler)

    assert (
        flow.resolve_handler(NodeInstance(id="versioned", type="qa.versioned", type_version="2.0"))
        is second_handler
    )

    flow.register_node(
        NodeDefinition(type="qa.missing-handler", version="1.0", handler="qa.run.missing")
    )
    missing = NodeInstance(id="missing", type="qa.missing-handler", type_version="1.0")
    with pytest.raises(NodeHandlerResolutionError, match="requires unregistered handler") as error:
        flow.resolve_handler(missing)
    assert error.value.handler_id == "qa.run.missing"
