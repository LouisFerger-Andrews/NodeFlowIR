"""Deterministic semantic fingerprints for canonical workflow definitions."""

from __future__ import annotations

import hashlib
import json

from pydantic import JsonValue

from nodeflowir.ir.workflow import Workflow


def workflow_semantic_document(workflow: Workflow) -> dict[str, JsonValue]:
    """Return the behavior-bearing, canonical JSON document used for comparison.

    Identity, revision/audit, display, and opaque metadata fields are omitted:
    they are not runtime workflow semantics.  Node type/version, configuration,
    bindings, deterministic values, policies, flow, inputs, constants, and
    outputs are retained.
    """

    document = workflow.model_dump(mode="json")
    document.pop("id", None)
    document.pop("workflow_version", None)
    document.pop("name", None)
    document.pop("description", None)
    document.pop("metadata", None)
    for node in document["nodes"]:
        node.pop("label", None)
        node.pop("metadata", None)
    return document


def canonical_workflow_json(workflow: Workflow) -> str:
    """Serialize semantic workflow data deterministically without presentation whitespace."""

    return json.dumps(
        workflow_semantic_document(workflow),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def workflow_fingerprint(workflow: Workflow) -> str:
    """Return a SHA-256 fingerprint of canonical workflow semantics.

    The result is suitable for comparison, optimistic-concurrency assistance,
    and caching.  It includes no live provider values or external state.
    """

    return hashlib.sha256(canonical_workflow_json(workflow).encode("utf-8")).hexdigest()
