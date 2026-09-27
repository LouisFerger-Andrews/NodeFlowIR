"""Portable ownership, revision, and resource-dependency contract tests."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from nodeflowir import (
    AccessGrant,
    ConfigField,
    ExecutionIdentityMode,
    ExecutionIdentityPolicy,
    NodeFlow,
    NodeInstance,
    ResourceDependency,
    ResourceFieldContract,
    ResourceReference,
    RevisionPrecondition,
    Select,
    SubjectReference,
    SubjectType,
    Workflow,
    WorkflowAccessPolicy,
    WorkflowAccessRole,
    WorkflowIdentity,
    WorkflowRevision,
    WorkflowVisibility,
    build_workflow_catalog,
    node,
)
from nodeflowir.ir import FlowBlock, NodeStep


@node(
    id="qa.test-suite",
    version="1.0",
    display_name="Test Suite",
    category="Testing",
    handler="test_management.run_suite",
)
class TestSuiteNode:
    suite_id: str = ConfigField(
        ui=Select(provider="test_management.suites"),
        resource=ResourceFieldContract(
            resource_type="test_suite",
            provider_id="test_management.suites",
        ),
    )
    output = bool


@node(id="data.dataset", version="1.0", display_name="Dataset")
class DatasetNode:
    target: dict[str, str] = ConfigField(
        resource=ResourceFieldContract(resource_type="dataset"),
    )
    output = bool


def _workflow(*, suite_id: str = "suite_123") -> Workflow:
    return Workflow(
        id="wf_123",
        workflow_version=8,
        name="Nightly Regression",
        nodes=[
            NodeInstance(
                id="nightly_tests",
                type="qa.test-suite",
                type_version="1.0",
                config={"suite_id": suite_id},
            )
        ],
        body=FlowBlock(steps=[NodeStep(node_id="nightly_tests")]),
    )


def _alice() -> SubjectReference:
    return SubjectReference(type=SubjectType.USER, id="user_alice")


def test_workflow_identity_schema_and_revision_are_independent_and_serializable() -> None:
    workflow = _workflow()
    revision = WorkflowRevision(
        workflow_id=workflow.workflow_id,
        schema_version=workflow.schema_version,
        workflow_version=workflow.workflow_version,
        based_on_version=7,
        created_by=_alice(),
    )
    precondition = RevisionPrecondition(workflow_id="wf_123", expected_version=7)

    assert workflow.id == workflow.workflow_id == "wf_123"
    assert workflow.schema_version == "1.0"
    assert workflow.workflow_version == 8
    assert json.loads(revision.model_dump_json()) == {
        "workflow_id": "wf_123",
        "schema_version": "1.0",
        "workflow_version": 8,
        "based_on_version": 7,
        "created_by": {"type": "user", "id": "user_alice"},
    }
    assert precondition.expected_version == 7

    with pytest.raises(ValidationError, match="based_on_version must precede"):
        WorkflowRevision(
            workflow_id="wf_123",
            schema_version="1.0",
            workflow_version=8,
            based_on_version=8,
        )


def test_access_policy_expresses_sharing_intent_without_authorization_decisions() -> None:
    project = SubjectReference(type=SubjectType.PROJECT, id="project_quality")
    bob = SubjectReference(type=SubjectType.USER, id="user_bob")
    policy = WorkflowAccessPolicy(
        owner=_alice(),
        visibility=WorkflowVisibility.PROJECT,
        entries=(
            AccessGrant(subject=project, role=WorkflowAccessRole.EDITOR),
            AccessGrant(subject=bob, role=WorkflowAccessRole.VIEWER),
            AccessGrant(subject=bob, role=WorkflowAccessRole.EXECUTOR),
        ),
    )
    identity = WorkflowIdentity(workflow_id="wf_123", project_scope=project)

    assert identity.project_scope == project
    assert policy.owner == _alice()
    assert [entry.role for entry in policy.entries] == [
        WorkflowAccessRole.EDITOR,
        WorkflowAccessRole.VIEWER,
        WorkflowAccessRole.EXECUTOR,
    ]
    assert policy.model_dump(mode="json")["entries"][0]["subject"]["id"] == "project_quality"

    with pytest.raises(ValidationError, match="owner must be declared"):
        WorkflowAccessPolicy(
            owner=_alice(),
            entries=(AccessGrant(subject=_alice(), role=WorkflowAccessRole.OWNER),),
        )
    with pytest.raises(ValidationError, match="project_scope"):
        WorkflowIdentity(workflow_id="wf_123", project_scope=_alice())


def test_execution_identity_contract_supports_owner_caller_service_and_subject() -> None:
    assert ExecutionIdentityPolicy(mode=ExecutionIdentityMode.OWNER).mode == "owner"
    assert ExecutionIdentityPolicy(mode=ExecutionIdentityMode.CALLER).mode == "caller"
    assert ExecutionIdentityPolicy(mode=ExecutionIdentityMode.SERVICE).mode == "service"
    service = SubjectReference(type=SubjectType.SERVICE, id="scheduler_service")
    explicit = ExecutionIdentityPolicy(mode=ExecutionIdentityMode.SUBJECT, subject=service)
    assert explicit.subject == service

    with pytest.raises(ValidationError, match="requires subject"):
        ExecutionIdentityPolicy(mode=ExecutionIdentityMode.SUBJECT)
    with pytest.raises(ValidationError, match="only valid"):
        ExecutionIdentityPolicy(mode=ExecutionIdentityMode.OWNER, subject=_alice())


def test_resource_dependencies_are_collected_without_resolution_or_authorization() -> None:
    flow = NodeFlow()
    flow.register_node(TestSuiteNode)
    workflow = _workflow()

    dependencies = flow.collect_resource_dependencies(workflow)

    assert dependencies == (
        ResourceDependency(
            node_id="nightly_tests",
            node_type="qa.test-suite",
            node_version="1.0",
            config_field="suite_id",
            resource=ResourceReference(
                resource_type="test_suite",
                resource_id="suite_123",
                provider_id="test_management.suites",
            ),
            requires_authorization=True,
        ),
    )
    assert flow.validate(workflow).is_valid
    assert flow.providers.identifiers() == ()
    assert flow.handlers.identifiers() == ()


def test_protected_resource_field_is_available_in_the_shared_catalog_contract() -> None:
    flow = NodeFlow()
    flow.register_node(TestSuiteNode)

    item = next(item for item in flow.build_catalog().items if item.type == "qa.test-suite")
    field = item.configuration_schema["suite_id"]

    assert field.resource == ResourceFieldContract(
        resource_type="test_suite",
        provider_id="test_management.suites",
    )
    assert build_workflow_catalog(node_registry=flow.nodes).model_dump(mode="json")["items"][-1][
        "configuration_schema"
    ]["suite_id"]["resource"] == {
        "resource_type": "test_suite",
        "provider_id": "test_management.suites",
        "requires_authorization": True,
    }


def test_structured_resource_references_and_multiple_nodeflow_instances_remain_isolated() -> None:
    first = NodeFlow()
    second = NodeFlow()
    first.register_node(DatasetNode)
    structured_workflow = Workflow(
        id="wf_dataset",
        workflow_version=1,
        name="Dataset workflow",
        nodes=[
            NodeInstance(
                id="load_dataset",
                type="data.dataset",
                type_version="1.0",
                config={
                    "target": {
                        "resource_type": "dataset",
                        "resource_id": "dataset_456",
                    }
                },
            )
        ],
        body=FlowBlock(steps=[NodeStep(node_id="load_dataset")]),
    )

    assert first.validate(structured_workflow).is_valid
    dependency = first.collect_resource_dependencies(structured_workflow)[0]
    assert dependency.resource.resource_id == "dataset_456"
    assert second.collect_resource_dependencies(structured_workflow) == ()


def test_sharing_and_run_as_owner_are_structural_even_without_application_authorization() -> None:
    flow = NodeFlow()
    flow.register_node(TestSuiteNode)
    workflow = _workflow()
    access = WorkflowAccessPolicy(
        owner=_alice(),
        entries=(
            AccessGrant(
                subject=SubjectReference(type=SubjectType.USER, id="user_bob"),
                role=WorkflowAccessRole.EDITOR,
            ),
        ),
    )
    execution = ExecutionIdentityPolicy(mode=ExecutionIdentityMode.OWNER)

    assert access.entries[0].role is WorkflowAccessRole.EDITOR
    assert execution.mode is ExecutionIdentityMode.OWNER
    assert flow.load_workflow(workflow) == workflow
    assert flow.collect_resource_dependencies(workflow)[0].resource.resource_id == "suite_123"
