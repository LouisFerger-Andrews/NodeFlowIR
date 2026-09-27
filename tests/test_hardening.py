"""Final contract hardening tests for compatibility, revisions, and limits."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from nodeflowir import (
    CATALOG_VERSION,
    CompatibilityCode,
    Deprecation,
    NodeDefinition,
    NodeFlow,
    NodeInstance,
    Workflow,
    WorkflowDiffKind,
    workflow_diff,
    workflow_fingerprint,
)
from nodeflowir.ir import FlowBlock, IfStep, LiteralValue, NodeStep, ObjectValue
from nodeflowir.serialization import workflow_from_json, workflow_to_json


def _workflow(*, version: int = 1, configured_value: str = "first") -> Workflow:
    return Workflow(
        id="wf_hardening",
        workflow_version=version,
        name="Hardening workflow",
        nodes=[
            NodeInstance(
                id="task",
                type="utility.task",
                type_version="1.0",
                config={"value": configured_value},
            )
        ],
        body=FlowBlock(steps=[NodeStep(node_id="task")]),
    )


def test_catalog_version_and_deprecation_keep_existing_nodes_loadable() -> None:
    flow = NodeFlow()
    old_node = NodeDefinition(
        type="utility.old-task",
        version="1.0",
        display_name="Old Task",
        deprecation=Deprecation(
            message="Use utility.task instead.", replacement="node:utility.task@1.0"
        ),
    )
    flow.register_node(old_node)

    catalog = flow.build_catalog()
    item = next(item for item in catalog.items if item.type == "utility.old-task")

    assert catalog.catalog_version == CATALOG_VERSION
    assert item.deprecation == old_node.deprecation
    assert item not in catalog.palette_items()
    assert flow.nodes.resolve("utility.old-task", "1.0") is old_node


def test_compatibility_preflight_reuses_migrations_and_node_registry_without_validation() -> None:
    flow = NodeFlow()
    flow.register_node(NodeDefinition(type="utility.task", version="1.0"))
    compatible_payload = _workflow().model_dump(mode="json")

    assert flow.check_compatibility(
        compatible_payload, catalog_version=CATALOG_VERSION
    ).is_compatible

    unknown = {
        **compatible_payload,
        "nodes": [{**compatible_payload["nodes"][0], "type_version": "2.0"}],
    }
    result = flow.check_compatibility(unknown, catalog_version="0.9")
    assert {issue.code for issue in result.issues} == {
        CompatibilityCode.UNSUPPORTED_CATALOG_VERSION,
        CompatibilityCode.UNSUPPORTED_NODE_DEFINITION,
    }

    legacy = {**compatible_payload, "schema_version": "0.9"}
    unsupported = flow.check_compatibility(legacy)
    assert unsupported.issues[0].code is CompatibilityCode.UNSUPPORTED_SCHEMA_VERSION

    flow.migrations.register("0.9", "1.0", lambda document: {**document, "schema_version": "1.0"})
    assert flow.check_compatibility(legacy).is_compatible


def test_canonical_fingerprint_ignores_formatting_identity_revision_and_display_metadata() -> None:
    workflow = _workflow()
    restored = workflow_from_json(json.dumps(workflow.model_dump(mode="json"), indent=4))
    renamed_revision = workflow.model_copy(
        update={
            "workflow_version": 2,
            "name": "Renamed workflow",
            "description": "Display-only change",
            "metadata": {"ui": "changed"},
            "nodes": [
                workflow.nodes[0].model_copy(
                    update={"label": "Display-only label", "metadata": {"x": True}}
                )
            ],
        }
    )
    semantic_change = _workflow(configured_value="second")

    assert workflow_fingerprint(workflow) == workflow_fingerprint(restored)
    assert workflow_fingerprint(workflow) == workflow_fingerprint(renamed_revision)
    assert workflow_fingerprint(workflow) != workflow_fingerprint(semantic_change)


def test_structural_diff_reports_revision_config_and_condition_changes_deterministically() -> None:
    before = _workflow()
    after = _workflow(version=2, configured_value="second")
    diff = workflow_diff(before, after)

    assert diff.workflow_id == "wf_hardening"
    assert [change.kind for change in diff.changes] == [
        WorkflowDiffKind.WORKFLOW_VERSION_CHANGED,
        WorkflowDiffKind.NODE_CONFIG_CHANGED,
    ]
    assert diff.changes[1].path == ("nodes", "task", "config")

    condition_before = before.model_copy(
        update={
            "body": FlowBlock(
                steps=[
                    IfStep(
                        condition=LiteralValue(value=True),
                        then=FlowBlock(steps=[NodeStep(node_id="task")]),
                    )
                ]
            )
        }
    )
    condition_after = condition_before.model_copy(
        update={
            "body": FlowBlock(
                steps=[
                    IfStep(
                        condition=LiteralValue(value=False),
                        then=FlowBlock(steps=[NodeStep(node_id="task")]),
                    )
                ]
            )
        }
    )
    condition_diff = workflow_diff(condition_before, condition_after)
    assert [change.kind for change in condition_diff.changes] == [
        WorkflowDiffKind.CONDITION_CHANGED
    ]


def test_facade_import_export_fingerprints_and_diffs_are_canonical_helpers() -> None:
    flow = NodeFlow()
    flow.register_node(NodeDefinition(type="utility.task", version="1.0"))
    workflow = _workflow().model_copy(
        update={"nodes": [_workflow().nodes[0].model_copy(update={"config": {}})]}
    )

    exported = flow.export_workflow(workflow)
    imported = flow.import_workflow(exported)

    assert imported == workflow
    assert flow.workflow_fingerprint(imported) == workflow_fingerprint(workflow)
    assert flow.diff_workflows(workflow, _workflow(version=2)).changes[0].kind is (
        WorkflowDiffKind.WORKFLOW_VERSION_CHANGED
    )
    assert json.loads(workflow_to_json(imported))["id"] == "wf_hardening"


def test_structural_limits_reject_excessive_configuration_and_nesting() -> None:
    with pytest.raises(ValidationError, match="at most 256 items"):
        NodeInstance(
            id="overconfigured",
            type="utility.task",
            type_version="1.0",
            config={f"field_{index}": index for index in range(257)},
        )

    nested = LiteralValue(value="leaf")
    for _ in range(65):
        nested = ObjectValue(fields={"nested": nested})
    with pytest.raises(ValidationError, match="nesting depth"):
        Workflow(
            id="wf_nested",
            workflow_version=1,
            name="Nested",
            nodes=[NodeInstance(id="task", type="utility.task", type_version="1.0")],
            body=FlowBlock(steps=[NodeStep(node_id="task")]),
            outputs={"nested": nested},
        )
