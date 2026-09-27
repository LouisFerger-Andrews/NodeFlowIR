from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import BaseModel, ValidationError

from nodeflowir.ir import (
    FlowBlock,
    NodeInstance,
    NodeStep,
    Workflow,
)
from nodeflowir.ir.types import TypeSpec, ValueKind
from nodeflowir.nodes import (
    ConfigField,
    ConfigurationField,
    DuplicateBindingError,
    DuplicateNodeDefinitionError,
    ExecutionHandlerRegistry,
    FieldConstraints,
    NodeDefinition,
    NodeRegistry,
    ProviderContext,
    ProviderRegistry,
    Select,
    UnknownBindingError,
    node,
)
from nodeflowir.validation import IssueCode, validate_workflow


class SuiteInputs(BaseModel):
    repository: str


class SuiteExecutionResult(BaseModel):
    passed: bool
    results: list[str]


def test_class_sdk_creates_a_serializable_versioned_node_contract() -> None:
    registry = NodeRegistry()

    @node(
        id="qa.test-suite",
        version="1.0",
        display_name="Test Suite",
        category="Quality Assurance",
        handler="test_management.run_suite",
        input_model=SuiteInputs,
        registry=registry,
    )
    class TestSuiteNode:
        """Run an application-owned Test Management suite."""

        suite_id: str = ConfigField(
            ui=Select(provider="test_management.suites"),
            description="Stable identifier of the suite to run.",
        )
        retry_limit: int = ConfigField(
            default=2,
            constraints=FieldConstraints(minimum=0, maximum=5),
        )
        output = SuiteExecutionResult

    definition = registry.resolve("qa.test-suite", "1.0")
    metadata = registry.metadata("qa.test-suite", "1.0")

    assert TestSuiteNode.__nodeflowir_definition__ == definition
    assert definition.handler == "test_management.run_suite"
    assert definition.inputs["repository"].type.kind is ValueKind.STRING
    assert definition.outputs["passed"].type.kind is ValueKind.BOOLEAN
    assert definition.config[0].ui is not None
    assert definition.config[0].ui.provider == "test_management.suites"
    assert metadata["display_name"] == "Test Suite"
    assert metadata["config"][0]["name"] == "suite_id"
    assert metadata["config"][0]["ui"]["widget"] == "select"
    assert json.loads(json.dumps(metadata))["handler"] == "test_management.run_suite"


def test_registry_supports_duplicate_detection_versions_and_latest_lookup() -> None:
    registry = NodeRegistry()
    first = NodeDefinition(type="qa.test-suite", version="1.0")
    second = NodeDefinition(type="qa.test-suite", version="2.0")
    registry.register(first)
    registry.register(second)

    assert registry.get("qa.test-suite") == second
    assert registry.versions("qa.test-suite") == ("2.0", "1.0")
    assert registry.node_types() == ("qa.test-suite",)
    assert registry.list_metadata()[0]["version"] == "1.0"
    with pytest.raises(DuplicateNodeDefinitionError):
        registry.register(first)


def test_node_instance_configuration_is_validated_against_its_definition() -> None:
    registry = NodeRegistry()
    registry.register(
        NodeDefinition(
            type="qa.test-suite",
            version="1.0",
            config=(
                ConfigurationField(
                    name="suite_id",
                    type=TypeSpec(kind=ValueKind.STRING),
                    ui=Select(provider="test_management.suites"),
                ),
                ConfigurationField(
                    name="mode",
                    type=TypeSpec(kind=ValueKind.STRING, enum_values=("smoke", "full")),
                    required=False,
                    default="smoke",
                    has_default=True,
                ),
                ConfigurationField(
                    name="retry_limit",
                    type=TypeSpec(kind=ValueKind.INTEGER),
                    required=False,
                    constraints=FieldConstraints(minimum=0, maximum=5),
                ),
            ),
        )
    )
    workflow = Workflow(
        id="nightly-tests",
        workflow_version=1,
        name="Nightly Tests",
        nodes=[
            NodeInstance(
                id="nightly-regression",
                type="qa.test-suite",
                type_version="1.0",
                config={
                    "suite_id": 42,
                    "mode": "invalid",
                    "retry_limit": 7,
                    "unexpected": True,
                },
            )
        ],
        body=FlowBlock(steps=[NodeStep(node_id="nightly-regression")]),
    )

    codes = {issue.code for issue in validate_workflow(workflow, registry).issues}
    missing_config = workflow.model_copy(
        update={"nodes": [workflow.nodes[0].model_copy(update={"config": {}})]}
    )
    missing_codes = {issue.code for issue in validate_workflow(missing_config, registry).issues}

    assert IssueCode.UNKNOWN_CONFIGURATION_FIELD in codes
    assert IssueCode.INVALID_CONFIGURATION_VALUE in codes
    assert IssueCode.MISSING_REQUIRED_CONFIGURATION in missing_codes


def test_configuration_default_must_satisfy_its_constraints() -> None:
    with pytest.raises(ValidationError, match="configuration default is invalid"):
        ConfigurationField(
            name="retry_limit",
            type=TypeSpec(kind=ValueKind.INTEGER),
            required=False,
            default=6,
            has_default=True,
            constraints=FieldConstraints(maximum=5),
        )


def test_test_management_contract_uses_fresh_provider_options_and_stable_config() -> None:
    registry = NodeRegistry()
    definition = NodeDefinition(
        type="qa.test-suite",
        version="1.0",
        display_name="Test Suite",
        handler="test_management.run_suite",
        config=(
            ConfigurationField(
                name="suite_id",
                type=TypeSpec(kind=ValueKind.STRING),
                ui=Select(provider="test_management.suites"),
            ),
        ),
    )
    registry.register(definition)
    providers = ProviderRegistry()
    providers.register(
        "test_management.suites",
        lambda context: [
            {"value": "suite_123", "label": "Regression Suite"},
            {"value": "suite_456", "label": "Smoke Tests"},
        ],
    )

    options = asyncio.run(
        providers.options(
            "test_management.suites",
            context=ProviderContext(data={"environment": "nightly"}),
        )
    )
    workflow = Workflow(
        id="nightly",
        workflow_version=1,
        name="Nightly",
        nodes=[
            NodeInstance(
                id="nightly-regression",
                type="qa.test-suite",
                type_version="1.0",
                config={"suite_id": "suite_123"},
            )
        ],
        body=FlowBlock(steps=[NodeStep(node_id="nightly-regression")]),
    )

    assert [option.value for option in options] == ["suite_123", "suite_456"]
    assert validate_workflow(workflow, registry).is_valid
    assert "Regression Suite" not in str(definition.metadata_document())


def test_provider_and_handler_registries_only_bind_application_code() -> None:
    providers = ProviderRegistry()
    handlers = ExecutionHandlerRegistry()

    async def suites(_: ProviderContext):
        return [{"value": "suite_123", "label": "Regression Suite"}]

    def run_suite() -> None:
        raise AssertionError("NodeFlowIR must not execute this handler")

    providers.register("test_management.suites", suites)
    handlers.register("test_management.run_suite", run_suite)

    assert providers.identifiers() == ("test_management.suites",)
    assert handlers.resolve("test_management.run_suite") is run_suite
    assert asyncio.run(providers.options("test_management.suites"))[0].value == "suite_123"
    with pytest.raises(DuplicateBindingError):
        providers.register("test_management.suites", suites)
    with pytest.raises(UnknownBindingError):
        handlers.resolve("test_management.missing")
    with pytest.raises(ValidationError):
        providers.register("invalid provider id", suites)
    with pytest.raises(ValidationError):
        Select(provider="invalid provider id")
    with pytest.raises(ValidationError):
        NodeDefinition(type="qa.test-suite", version="1.0", handler="invalid handler id")
