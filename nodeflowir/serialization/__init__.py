"""JSON serialization and explicit IR schema migration support."""

from nodeflowir.serialization.diff import (
    WorkflowDiff,
    WorkflowDiffChange,
    WorkflowDiffKind,
    workflow_diff,
)
from nodeflowir.serialization.fingerprint import (
    canonical_workflow_json,
    workflow_fingerprint,
    workflow_semantic_document,
)
from nodeflowir.serialization.json import (
    workflow_from_document,
    workflow_from_json,
    workflow_to_json,
)
from nodeflowir.serialization.migrations import MigrationError, MigrationRegistry

__all__ = [
    "MigrationError",
    "MigrationRegistry",
    "workflow_from_document",
    "workflow_from_json",
    "workflow_to_json",
    "WorkflowDiff",
    "WorkflowDiffChange",
    "WorkflowDiffKind",
    "canonical_workflow_json",
    "workflow_diff",
    "workflow_fingerprint",
    "workflow_semantic_document",
]
