"""JSON serialization and explicit IR schema migration support."""

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
]
