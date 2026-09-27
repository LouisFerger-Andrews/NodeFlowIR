from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from nodeflowir.catalog import (
    BranchDefinition,
    CatalogConfigurationField,
    CatalogFieldType,
    CatalogItemKind,
    CatalogPort,
    CatalogPortKind,
    PortCardinality,
    PortDirection,
    WorkflowCatalog,
    WorkflowCatalogItem,
    build_workflow_catalog,
    ports_are_compatible,
)
from nodeflowir.ir.types import TypeSpec, ValueKind
from nodeflowir.nodes import (
    ConfigurationField,
    NodeDefinition,
    NodeRegistry,
    PortDefinition,
    Select,
)


def _type(kind: ValueKind, **kwargs: object) -> TypeSpec:
    return TypeSpec(kind=kind, **kwargs)


def _registry() -> NodeRegistry:
    result = _type(
        ValueKind.OBJECT,
        fields={"status": _type(ValueKind.STRING), "severity": _type(ValueKind.INTEGER)},
    )
    registry = NodeRegistry()
    registry.register(
        NodeDefinition(
            type="qa.test-suite",
            version="1.0",
            display_name="Test Suite",
            category="Testing",
            handler="test_management.run_suite",
            config=(
                ConfigurationField(
                    name="suite_id",
                    type=_type(ValueKind.STRING),
                    ui=Select(provider="test_management.suites"),
                ),
                ConfigurationField(
                    name="mode",
                    type=_type(ValueKind.STRING, enum_values=("smoke", "full")),
                    required=False,
                ),
            ),
            inputs={
                "environment": PortDefinition(
                    type=_type(ValueKind.STRING), ui={"accepts": "deployment-environment"}
                )
            },
            outputs={
                "passed": PortDefinition(type=_type(ValueKind.BOOLEAN)),
                "results": PortDefinition(type=_type(ValueKind.ARRAY, items=result)),
            },
        )
    )
    registry.register(
        NodeDefinition(
            type="ticket.create",
            version="1.0",
            display_name="Create Ticket",
            category="Testing",
            inputs={"details": PortDefinition(type=_type(ValueKind.ARRAY, items=result))},
        )
    )
    registry.register(
        NodeDefinition(
            type="report.create",
            version="1.0",
            display_name="Create Report",
            category="Testing",
            inputs={"passed": PortDefinition(type=_type(ValueKind.BOOLEAN))},
        )
    )
    return registry


def test_builds_a_unified_builtin_and_custom_node_catalog() -> None:
    catalog = build_workflow_catalog(node_registry=_registry())
    items = {item.id: item for item in catalog.items}

    assert items["control_flow:if"].kind is CatalogItemKind.CONTROL_FLOW
    assert items["aggregation:count"].display_name == "Count"
    assert items["collection_operation:count"].display_name == "Count"
    assert items["transformation:join"].category == "Collections"
    assert items["expression:between"].category == "Logic"
    assert items["value:convert"].display_name == "Convert Type"
    node = items["node:qa.test-suite@1.0"]
    assert node.kind is CatalogItemKind.NODE
    assert node.display_name == "Test Suite"
    assert node.capabilities["handler_reference"] is True
    assert node.configuration_schema["suite_id"].type is CatalogFieldType.DYNAMIC_SELECT
    assert node.configuration_schema["suite_id"].provider == "test_management.suites"
    assert node.configuration_schema["mode"].type is CatalogFieldType.ENUM
    assert {port.id for port in node.input_ports} == {"$control.in", "environment"}
    assert {port.id for port in node.output_ports} == {"$control.out", "passed", "results"}
    assert next(port for port in node.input_ports if port.id == "environment").required is True
    assert next(port for port in node.input_ports if port.id == "environment").ui == {
        "accepts": "deployment-environment"
    }
    assert all(port.required is False for port in node.output_ports)
    assert node.capabilities["structured_control_step"] is True


def test_builtin_control_flow_ports_and_dynamic_branches_are_explicit() -> None:
    catalog = build_workflow_catalog(node_registry=_registry())
    items = {item.type: item for item in catalog.by_kind(CatalogItemKind.CONTROL_FLOW)}

    if_item = items["if"]
    assert [port.id for port in if_item.input_ports] == ["in"]
    assert [port.id for port in if_item.output_ports] == ["true", "false"]
    assert if_item.configuration_schema["condition"].type is CatalogFieldType.EXPRESSION

    foreach = items["foreach"]
    assert [port.id for port in foreach.output_ports] == ["each", "completed"]
    assert foreach.configuration_schema["collection"].type is CatalogFieldType.COLLECTION_REFERENCE

    parallel = items["parallel"]
    assert parallel.branch_definition is not None
    assert parallel.branch_definition.dynamic
    assert parallel.branch_definition.minimum_branches == 2
    assert next(port for port in parallel.output_ports if port.id == "branch").dynamic

    match = items["match"]
    assert match.branch_definition is not None
    assert match.branch_definition.dynamic
    assert match.branch_definition.default_branch
    assert (
        match.branch_definition.branch_config_schema["case_value"].type is CatalogFieldType.LITERAL
    )


def test_context_aware_collection_and_reference_configuration_is_discoverable() -> None:
    catalog = build_workflow_catalog(node_registry=_registry())
    items = {item.id: item for item in catalog.items}

    filter_item = items["collection_operation:filter"]
    assert (
        filter_item.configuration_schema["collection"].type is CatalogFieldType.COLLECTION_REFERENCE
    )
    assert filter_item.configuration_schema["collection"].capabilities["earlier_nodes_only"] is True
    assert (
        filter_item.configuration_schema["item_scope"].capabilities["generated_identifier"] is True
    )
    assert (
        filter_item.configuration_schema["predicate"].capabilities["collection_item_scope"] is True
    )

    reference = items["value:node_output_reference"]
    assert reference.configuration_schema["source"].type is CatalogFieldType.NODE_OUTPUT_REFERENCE
    assert reference.configuration_schema["source"].capabilities["earlier_nodes_only"] is True
    assert (
        items["value:field_reference"].configuration_schema["source"].type
        is CatalogFieldType.FIELD_REFERENCE
    )

    multi_select = CatalogConfigurationField(
        type=CatalogFieldType.MULTI_SELECT,
        provider="test_management.suites",
    )
    assert multi_select.provider == "test_management.suites"


def test_catalog_is_json_serializable_without_resolving_dynamic_providers() -> None:
    catalog = build_workflow_catalog(node_registry=_registry())
    payload = catalog.model_dump(mode="json")
    rendered = json.dumps(payload)

    assert "test_management.suites" in rendered
    assert "Regression Suite" not in rendered
    assert payload["schema_version"] == "1.0"


def test_catalog_metadata_supports_test_suite_if_ticket_report_structure() -> None:
    catalog = build_workflow_catalog(node_registry=_registry())
    items = {item.id: item for item in catalog.items}
    tests = items["node:qa.test-suite@1.0"]
    condition = items["control_flow:if"]
    ticket = items["node:ticket.create@1.0"]
    report = items["node:report.create@1.0"]

    results = next(port for port in tests.output_ports if port.id == "results")
    passed = next(port for port in tests.output_ports if port.id == "passed")
    tests_next = next(port for port in tests.output_ports if port.id == "$control.out")
    tests_in = next(port for port in tests.input_ports if port.id == "$control.in")
    ticket_in = next(port for port in ticket.input_ports if port.id == "$control.in")
    report_in = next(port for port in report.input_ports if port.id == "$control.in")
    ticket_details = next(port for port in ticket.input_ports if port.id == "details")
    report_passed = next(port for port in report.input_ports if port.id == "passed")
    assert results.kind is CatalogPortKind.DATA
    assert results.data_type is not None and results.data_type.kind is ValueKind.ARRAY
    assert condition.configuration_schema["condition"].type is CatalogFieldType.EXPRESSION
    assert [port.id for port in condition.output_ports] == ["true", "false"]
    assert ticket_details.data_type == results.data_type
    assert report_passed.data_type == passed.data_type
    assert ports_are_compatible(results, ticket_details)
    assert not ports_are_compatible(passed, ticket_details)
    assert ports_are_compatible(tests_next, condition.input_ports[0])
    assert ports_are_compatible(condition.output_ports[0], ticket_in)
    assert ports_are_compatible(condition.output_ports[1], report_in)
    assert not ports_are_compatible(tests_in, ticket_in)


def test_catalog_models_reject_invalid_ports_configuration_and_branches() -> None:
    with pytest.raises(ValidationError, match="control port"):
        CatalogPort(
            id="in",
            kind=CatalogPortKind.CONTROL,
            direction=PortDirection.INPUT,
            data_type=_type(ValueKind.STRING),
        )
    with pytest.raises(ValidationError, match="dynamic select"):
        CatalogConfigurationField(type=CatalogFieldType.DYNAMIC_SELECT)
    with pytest.raises(ValidationError, match="String should match pattern"):
        CatalogConfigurationField(
            type=CatalogFieldType.DYNAMIC_SELECT,
            provider="invalid provider id",
        )
    with pytest.raises(ValidationError, match="branch details"):
        BranchDefinition(minimum_branches=2)
    with pytest.raises(ValidationError, match="port ids must be unique"):
        WorkflowCatalogItem(
            id="invalid",
            kind=CatalogItemKind.EXPRESSION,
            type="invalid",
            display_name="Invalid",
            category="Tests",
            input_ports=(
                CatalogPort(
                    id="value",
                    kind=CatalogPortKind.DATA,
                    direction=PortDirection.INPUT,
                    data_type=_type(ValueKind.STRING),
                ),
            ),
            output_ports=(
                CatalogPort(
                    id="value",
                    kind=CatalogPortKind.DATA,
                    direction=PortDirection.OUTPUT,
                    required=False,
                    data_type=_type(ValueKind.STRING),
                ),
            ),
        )
    with pytest.raises(ValidationError, match="requires an input control port"):
        WorkflowCatalogItem(
            id="missing-control-input",
            kind=CatalogItemKind.CONTROL_FLOW,
            type="invalid",
            display_name="Invalid",
            category="Tests",
        )
    with pytest.raises(ValidationError, match="dynamic output ports require a branch definition"):
        WorkflowCatalogItem(
            id="missing-branch-definition",
            kind=CatalogItemKind.CONTROL_FLOW,
            type="invalid",
            display_name="Invalid",
            category="Tests",
            input_ports=(
                CatalogPort(
                    id="in",
                    kind=CatalogPortKind.CONTROL,
                    direction=PortDirection.INPUT,
                ),
            ),
            output_ports=(
                CatalogPort(
                    id="branch",
                    kind=CatalogPortKind.CONTROL,
                    direction=PortDirection.OUTPUT,
                    cardinality=PortCardinality.MANY,
                    required=False,
                    dynamic=True,
                ),
            ),
        )
    with pytest.raises(ValidationError, match="output port cannot be required"):
        CatalogPort(
            id="out",
            kind=CatalogPortKind.CONTROL,
            direction=PortDirection.OUTPUT,
        )
    item = WorkflowCatalogItem(
        id="valid",
        kind=CatalogItemKind.VALUE,
        type="literal",
        display_name="Literal",
        category="Values",
    )
    with pytest.raises(ValidationError, match="item ids must be unique"):
        WorkflowCatalog(items=(item, item))
