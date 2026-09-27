"""Small, structured comparisons between two canonical workflow revisions."""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import JsonValue

from nodeflowir._model import NodeFlowModel
from nodeflowir.ir.workflow import Workflow


class WorkflowDiffKind(StrEnum):
    """Meaningful structural changes that can be surfaced by revision tooling."""

    WORKFLOW_ID_CHANGED = "workflow_id_changed"
    SCHEMA_VERSION_CHANGED = "schema_version_changed"
    WORKFLOW_VERSION_CHANGED = "workflow_version_changed"
    WORKFLOW_METADATA_CHANGED = "workflow_metadata_changed"
    WORKFLOW_INPUT_ADDED = "workflow_input_added"
    WORKFLOW_INPUT_REMOVED = "workflow_input_removed"
    WORKFLOW_INPUT_CHANGED = "workflow_input_changed"
    WORKFLOW_OUTPUT_ADDED = "workflow_output_added"
    WORKFLOW_OUTPUT_REMOVED = "workflow_output_removed"
    WORKFLOW_OUTPUT_CHANGED = "workflow_output_changed"
    CONSTANT_ADDED = "constant_added"
    CONSTANT_REMOVED = "constant_removed"
    CONSTANT_CHANGED = "constant_changed"
    NODE_ADDED = "node_added"
    NODE_REMOVED = "node_removed"
    NODE_CONTRACT_CHANGED = "node_contract_changed"
    NODE_CONFIG_CHANGED = "node_config_changed"
    NODE_POLICY_CHANGED = "node_policy_changed"
    NODE_METADATA_CHANGED = "node_metadata_changed"
    CONNECTION_ADDED = "connection_added"
    CONNECTION_REMOVED = "connection_removed"
    CONDITION_CHANGED = "condition_changed"
    CONTROL_FLOW_CHANGED = "control_flow_changed"


class WorkflowDiffChange(NodeFlowModel):
    """One deterministic structural difference, with JSON-safe before/after data."""

    kind: WorkflowDiffKind
    path: tuple[str | int, ...]
    before: JsonValue | None = None
    after: JsonValue | None = None


class WorkflowDiff(NodeFlowModel):
    """A portable, ordered comparison of two canonical workflow documents."""

    workflow_id: str | None = None
    from_workflow_version: int
    to_workflow_version: int
    changes: tuple[WorkflowDiffChange, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Return whether the comparison contains no structural or revision changes."""

        return not self.changes


def _document(value: object) -> JsonValue:
    """Normalize nested JSON objects to a stable representation for diff values."""

    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mapping_changes(
    before: dict[str, JsonValue],
    after: dict[str, JsonValue],
    *,
    path: tuple[str | int, ...],
    added: WorkflowDiffKind,
    removed: WorkflowDiffKind,
    changed: WorkflowDiffKind,
) -> list[WorkflowDiffChange]:
    changes: list[WorkflowDiffChange] = []
    for key in sorted(set(before).union(after)):
        key_path = (*path, key)
        if key not in before:
            changes.append(WorkflowDiffChange(kind=added, path=key_path, after=after[key]))
        elif key not in after:
            changes.append(WorkflowDiffChange(kind=removed, path=key_path, before=before[key]))
        elif before[key] != after[key]:
            changes.append(
                WorkflowDiffChange(
                    kind=changed,
                    path=key_path,
                    before=before[key],
                    after=after[key],
                )
            )
    return changes


def _condition_map(
    value: JsonValue, path: tuple[str | int, ...] = ()
) -> dict[tuple[str | int, ...], JsonValue]:
    """Find branch/match conditions in a JSON flow tree without evaluating them."""

    conditions: dict[tuple[str | int, ...], JsonValue] = {}
    if isinstance(value, dict):
        kind = value.get("kind")
        if kind == "if" and "condition" in value:
            conditions[(*path, "condition")] = value["condition"]
        if kind == "match" and "subject" in value:
            conditions[(*path, "subject")] = value["subject"]
        for key, nested in value.items():
            conditions.update(_condition_map(nested, (*path, key)))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            conditions.update(_condition_map(nested, (*path, index)))
    return conditions


def _without_conditions(value: JsonValue) -> JsonValue:
    """Remove condition-bearing values to distinguish condition from shape changes."""

    if isinstance(value, dict):
        return {
            key: _without_conditions(nested)
            for key, nested in value.items()
            if not (
                (value.get("kind") == "if" and key == "condition")
                or (value.get("kind") == "match" and key == "subject")
            )
        }
    if isinstance(value, list):
        return [_without_conditions(item) for item in value]
    return value


def workflow_diff(before: Workflow, after: Workflow) -> WorkflowDiff:
    """Compare two workflow revisions without persistence, execution, or I/O."""

    before_document = before.model_dump(mode="json")
    after_document = after.model_dump(mode="json")
    changes: list[WorkflowDiffChange] = []

    if before.id != after.id:
        changes.append(
            WorkflowDiffChange(
                kind=WorkflowDiffKind.WORKFLOW_ID_CHANGED,
                path=("id",),
                before=before.id,
                after=after.id,
            )
        )
    if before.schema_version != after.schema_version:
        changes.append(
            WorkflowDiffChange(
                kind=WorkflowDiffKind.SCHEMA_VERSION_CHANGED,
                path=("schema_version",),
                before=before.schema_version,
                after=after.schema_version,
            )
        )
    if before.workflow_version != after.workflow_version:
        changes.append(
            WorkflowDiffChange(
                kind=WorkflowDiffKind.WORKFLOW_VERSION_CHANGED,
                path=("workflow_version",),
                before=before.workflow_version,
                after=after.workflow_version,
            )
        )
    if any(
        before_document[field] != after_document[field]
        for field in ("name", "description", "metadata")
    ):
        changes.append(
            WorkflowDiffChange(
                kind=WorkflowDiffKind.WORKFLOW_METADATA_CHANGED,
                path=("metadata",),
                before=_document(
                    {field: before_document[field] for field in ("name", "description", "metadata")}
                ),
                after=_document(
                    {field: after_document[field] for field in ("name", "description", "metadata")}
                ),
            )
        )

    changes.extend(
        _mapping_changes(
            before_document["inputs"],
            after_document["inputs"],
            path=("inputs",),
            added=WorkflowDiffKind.WORKFLOW_INPUT_ADDED,
            removed=WorkflowDiffKind.WORKFLOW_INPUT_REMOVED,
            changed=WorkflowDiffKind.WORKFLOW_INPUT_CHANGED,
        )
    )
    changes.extend(
        _mapping_changes(
            before_document["outputs"],
            after_document["outputs"],
            path=("outputs",),
            added=WorkflowDiffKind.WORKFLOW_OUTPUT_ADDED,
            removed=WorkflowDiffKind.WORKFLOW_OUTPUT_REMOVED,
            changed=WorkflowDiffKind.WORKFLOW_OUTPUT_CHANGED,
        )
    )
    changes.extend(
        _mapping_changes(
            before_document["constants"],
            after_document["constants"],
            path=("constants",),
            added=WorkflowDiffKind.CONSTANT_ADDED,
            removed=WorkflowDiffKind.CONSTANT_REMOVED,
            changed=WorkflowDiffKind.CONSTANT_CHANGED,
        )
    )

    before_nodes = {node["id"]: node for node in before_document["nodes"]}
    after_nodes = {node["id"]: node for node in after_document["nodes"]}
    for node_id in sorted(set(before_nodes).union(after_nodes)):
        path = ("nodes", node_id)
        if node_id not in before_nodes:
            changes.append(
                WorkflowDiffChange(
                    kind=WorkflowDiffKind.NODE_ADDED,
                    path=path,
                    after=after_nodes[node_id],
                )
            )
            continue
        if node_id not in after_nodes:
            changes.append(
                WorkflowDiffChange(
                    kind=WorkflowDiffKind.NODE_REMOVED,
                    path=path,
                    before=before_nodes[node_id],
                )
            )
            continue
        old = before_nodes[node_id]
        new = after_nodes[node_id]
        if (old["type"], old["type_version"]) != (new["type"], new["type_version"]):
            changes.append(
                WorkflowDiffChange(
                    kind=WorkflowDiffKind.NODE_CONTRACT_CHANGED,
                    path=(*path, "contract"),
                    before=_document({"type": old["type"], "type_version": old["type_version"]}),
                    after=_document({"type": new["type"], "type_version": new["type_version"]}),
                )
            )
        if old["config"] != new["config"]:
            changes.append(
                WorkflowDiffChange(
                    kind=WorkflowDiffKind.NODE_CONFIG_CHANGED,
                    path=(*path, "config"),
                    before=old["config"],
                    after=new["config"],
                )
            )
        if any(old[field] != new[field] for field in ("retry", "timeout")):
            changes.append(
                WorkflowDiffChange(
                    kind=WorkflowDiffKind.NODE_POLICY_CHANGED,
                    path=(*path, "policy"),
                    before=_document({field: old[field] for field in ("retry", "timeout")}),
                    after=_document({field: new[field] for field in ("retry", "timeout")}),
                )
            )
        if any(old[field] != new[field] for field in ("label", "metadata")):
            changes.append(
                WorkflowDiffChange(
                    kind=WorkflowDiffKind.NODE_METADATA_CHANGED,
                    path=(*path, "metadata"),
                    before=_document({field: old[field] for field in ("label", "metadata")}),
                    after=_document({field: new[field] for field in ("label", "metadata")}),
                )
            )

    before_connections = {
        _stable_json(connection): _document(connection)
        for connection in before_document["connections"]
    }
    after_connections = {
        _stable_json(connection): _document(connection)
        for connection in after_document["connections"]
    }
    for connection in sorted(set(before_connections).difference(after_connections)):
        changes.append(
            WorkflowDiffChange(
                kind=WorkflowDiffKind.CONNECTION_REMOVED,
                path=("connections",),
                before=before_connections[connection],
            )
        )
    for connection in sorted(set(after_connections).difference(before_connections)):
        changes.append(
            WorkflowDiffChange(
                kind=WorkflowDiffKind.CONNECTION_ADDED,
                path=("connections",),
                after=after_connections[connection],
            )
        )

    before_conditions = _condition_map(before_document["body"], ("body",))
    after_conditions = _condition_map(after_document["body"], ("body",))
    for path in sorted(set(before_conditions).union(after_conditions), key=str):
        if before_conditions.get(path) != after_conditions.get(path):
            changes.append(
                WorkflowDiffChange(
                    kind=WorkflowDiffKind.CONDITION_CHANGED,
                    path=path,
                    before=before_conditions.get(path),
                    after=after_conditions.get(path),
                )
            )
    if _without_conditions(before_document["body"]) != _without_conditions(after_document["body"]):
        changes.append(
            WorkflowDiffChange(
                kind=WorkflowDiffKind.CONTROL_FLOW_CHANGED,
                path=("body",),
                before=_without_conditions(before_document["body"]),
                after=_without_conditions(after_document["body"]),
            )
        )

    return WorkflowDiff(
        workflow_id=before.id if before.id == after.id else None,
        from_workflow_version=before.workflow_version,
        to_workflow_version=after.workflow_version,
        changes=tuple(changes),
    )
