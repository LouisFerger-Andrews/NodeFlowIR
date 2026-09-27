"""JSON serialization entrypoints for canonical workflow documents."""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import JsonValue

from nodeflowir.ir import CURRENT_SCHEMA_VERSION, Workflow
from nodeflowir.serialization.migrations import MigrationError, MigrationRegistry


def workflow_to_json(workflow: Workflow, *, indent: int | None = 2) -> str:
    """Serialize a canonical Pydantic workflow model to JSON."""

    return workflow.model_dump_json(indent=indent)


def workflow_from_json(
    value: str | bytes | bytearray,
    *,
    migrations: MigrationRegistry | None = None,
) -> Workflow:
    """Load JSON, migrating an older schema only through an explicit registry."""

    document = json.loads(value)
    if not isinstance(document, Mapping):
        raise ValueError("a workflow JSON document must be an object")
    return workflow_from_document(document, migrations=migrations)


def workflow_from_document(
    document: Mapping[str, JsonValue],
    *,
    migrations: MigrationRegistry | None = None,
) -> Workflow:
    """Load a JSON-compatible document through the canonical schema path."""

    document = dict(document)
    schema_version = document.get("schema_version")
    if schema_version != CURRENT_SCHEMA_VERSION:
        if not isinstance(schema_version, str):
            raise MigrationError("workflow document has no string schema_version")
        if migrations is None:
            raise MigrationError(
                f"workflow schema '{schema_version}' requires an explicit migration to "
                f"'{CURRENT_SCHEMA_VERSION}'"
            )
        document = migrations.migrate(
            document, from_version=schema_version, to_version=CURRENT_SCHEMA_VERSION
        )
    return Workflow.model_validate(document)
