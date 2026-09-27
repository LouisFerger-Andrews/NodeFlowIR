"""One complete library scenario that deliberately stops before execution."""

from __future__ import annotations

import json

from pydantic import BaseModel

from nodeflowir import ConfigField, NodeFlow, Select, Workflow, node
from nodeflowir.serialization import workflow_to_json


class ScenarioResult(BaseModel):
    status: str


class ScenarioSuiteOutput(BaseModel):
    results: list[ScenarioResult]


@node(
    id="qa.test-suite",
    version="1.0",
    display_name="Test Suite",
    category="Testing",
    handler="test_management.run_suite",
)
class ScenarioTestSuiteNode:
    suite_id: str = ConfigField(ui=Select(provider="test_management.suites"))
    output = ScenarioSuiteOutput


@node(
    id="ticket.create",
    version="1.0",
    display_name="Create Ticket",
    category="Testing",
    handler="ticketing.create",
)
class ScenarioCreateTicketNode:
    output = str


@node(
    id="report.create",
    version="1.0",
    display_name="Create Report",
    category="Testing",
    handler="reporting.create",
)
class ScenarioCreateReportNode:
    output = str


def _workflow_payload() -> dict[str, object]:
    """The canonical IR for Test Suite → If ANY failed → Ticket / Report."""

    return {
        "schema_version": "1.0",
        "workflow_version": 1,
        "id": "nightly-regression",
        "name": "Nightly Regression",
        "nodes": [
            {
                "id": "tests",
                "type": "qa.test-suite",
                "type_version": "1.0",
                "config": {"suite_id": "suite_123"},
            },
            {"id": "ticket", "type": "ticket.create", "type_version": "1.0"},
            {"id": "report", "type": "report.create", "type_version": "1.0"},
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
                            "left": {
                                "kind": "loop_item",
                                "loop_id": "result",
                                "path": ["status"],
                            },
                            "right": {"kind": "literal", "value": "failed"},
                        },
                    },
                    "then": {"steps": [{"kind": "node", "node_id": "ticket"}]},
                    "else_body": {"steps": [{"kind": "node", "node_id": "report"}]},
                },
            ]
        },
        "outputs": {
            "results": {
                "kind": "node_output",
                "node_id": "tests",
                "output": "results",
            }
        },
    }


def test_library_contracts_converge_without_invoking_application_code() -> None:
    flow = NodeFlow()
    flow.register_node(ScenarioTestSuiteNode)
    flow.register_node(ScenarioCreateTicketNode)
    flow.register_node(ScenarioCreateReportNode)

    handler_calls: list[str] = []

    def run_suite(*_: object) -> None:
        handler_calls.append("test suite")

    def create_ticket(*_: object) -> None:
        handler_calls.append("ticket")

    def create_report(*_: object) -> None:
        handler_calls.append("report")

    flow.register_provider(
        "test_management.suites",
        lambda _: [{"value": "suite_123", "label": "Regression Suite"}],
    )
    flow.register_handler("test_management.run_suite", run_suite)
    flow.register_handler("ticketing.create", create_ticket)
    flow.register_handler("reporting.create", create_report)

    catalog = flow.build_catalog()
    catalog_items = {item.id: item for item in catalog.items}
    test_suite = catalog_items["node:qa.test-suite@1.0"]
    condition = catalog_items["control_flow:if"]
    assert test_suite.configuration_schema["suite_id"].provider == "test_management.suites"
    assert {port.id for port in test_suite.input_ports} >= {"$control.in"}
    assert {port.id for port in condition.output_ports} == {"true", "false"}

    canonical = Workflow.model_validate(_workflow_payload())
    assert flow.validate(canonical).is_valid

    restored = flow.load_workflow(json.loads(workflow_to_json(canonical)))
    formatted = flow.format_dsl(restored)
    reparsed = flow.parse_dsl(formatted)
    # Collection predicate scope IDs are lexical binders. The formatter emits
    # the DSL's compact implicit-item form, so an arbitrary canonical binder
    # name is normalized on parsing while the workflow meaning is preserved.
    assert flow.format_dsl(reparsed) == formatted
    assert flow.validate(reparsed).is_valid
    assert reparsed.body.steps[1].model_dump(mode="json")["condition"]["operator"] == "any"

    context = flow.build_authoring_context(
        provider_values={
            "test_management.suites": [
                {"value": "suite_123", "label": "Regression Suite"},
            ]
        }
    )
    assert {item.id for item in context.catalog.items} == set(catalog_items)
    assert flow.validate_authored_workflow(reparsed, authoring_context=context).is_valid

    handler = flow.resolve_handler(restored.nodes[0])
    assert handler is run_suite
    assert handler_calls == []
