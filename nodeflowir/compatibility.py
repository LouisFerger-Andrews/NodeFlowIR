"""Read-only compatibility discovery for workflow and catalog contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum

from pydantic import Field, JsonValue

from nodeflowir._model import NodeFlowModel
from nodeflowir.catalog import CATALOG_VERSION
from nodeflowir.ir.workflow import CURRENT_SCHEMA_VERSION, Workflow
from nodeflowir.nodes import NodeRegistry, UnknownNodeDefinitionError
from nodeflowir.serialization.migrations import MigrationError, MigrationRegistry


class CompatibilityCode(StrEnum):
    """Non-semantic preflight outcomes for installed NodeFlowIR capabilities."""

    MALFORMED_DOCUMENT = "malformed_document"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    UNSUPPORTED_NODE_DEFINITION = "unsupported_node_definition"
    UNSUPPORTED_CATALOG_VERSION = "unsupported_catalog_version"


class CompatibilityIssue(NodeFlowModel):
    """One serializable compatibility issue found before normal validation."""

    code: CompatibilityCode
    message: str
    path: tuple[str | int, ...] = Field(default_factory=tuple)
    expected: JsonValue | None = None
    received: JsonValue | None = None


class CompatibilityResult(NodeFlowModel):
    """Read-only discovery result; semantic validation remains separate."""

    issues: tuple[CompatibilityIssue, ...] = ()

    @property
    def is_compatible(self) -> bool:
        return not self.issues


def _document(
    value: Workflow | str | bytes | bytearray | Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    if isinstance(value, Workflow):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    loaded = json.loads(value)
    if not isinstance(loaded, Mapping):
        raise ValueError("a workflow document must be an object")
    return dict(loaded)


def check_workflow_compatibility(
    value: Workflow | str | bytes | bytearray | Mapping[str, JsonValue],
    *,
    registry: NodeRegistry,
    migrations: MigrationRegistry | None = None,
    catalog_version: str | None = None,
) -> CompatibilityResult:
    """Check installed schema/node/catalog support without semantic validation.

    This preflight intentionally does not replace parsing or
    :func:`validate_workflow`: it answers only whether this installation has
    the declared schema migration, node contract versions, and optional catalog
    protocol version needed to attempt normal processing.
    """

    issues: list[CompatibilityIssue] = []
    try:
        document = _document(value)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        return CompatibilityResult(
            issues=(
                CompatibilityIssue(
                    code=CompatibilityCode.MALFORMED_DOCUMENT,
                    message="workflow compatibility requires a JSON object document",
                    received=str(error),
                ),
            )
        )

    if catalog_version is not None and catalog_version != CATALOG_VERSION:
        issues.append(
            CompatibilityIssue(
                code=CompatibilityCode.UNSUPPORTED_CATALOG_VERSION,
                message=(
                    f"catalog version '{catalog_version}' is not supported; expected "
                    f"'{CATALOG_VERSION}'"
                ),
                path=("catalog_version",),
                expected=CATALOG_VERSION,
                received=catalog_version,
            )
        )

    schema_version = document.get("schema_version")
    if not isinstance(schema_version, str):
        issues.append(
            CompatibilityIssue(
                code=CompatibilityCode.UNSUPPORTED_SCHEMA_VERSION,
                message="workflow document has no string schema_version",
                path=("schema_version",),
                expected=CURRENT_SCHEMA_VERSION,
                received=schema_version,
            )
        )
        return CompatibilityResult(issues=tuple(issues))
    if schema_version != CURRENT_SCHEMA_VERSION:
        if migrations is None or not migrations.can_migrate(schema_version, CURRENT_SCHEMA_VERSION):
            issues.append(
                CompatibilityIssue(
                    code=CompatibilityCode.UNSUPPORTED_SCHEMA_VERSION,
                    message=(
                        f"workflow schema '{schema_version}' has no explicit migration to "
                        f"'{CURRENT_SCHEMA_VERSION}'"
                    ),
                    path=("schema_version",),
                    expected=CURRENT_SCHEMA_VERSION,
                    received=schema_version,
                )
            )
            return CompatibilityResult(issues=tuple(issues))
        try:
            document = migrations.migrate(
                document, from_version=schema_version, to_version=CURRENT_SCHEMA_VERSION
            )
        except MigrationError as error:
            issues.append(
                CompatibilityIssue(
                    code=CompatibilityCode.UNSUPPORTED_SCHEMA_VERSION,
                    message=str(error),
                    path=("schema_version",),
                    expected=CURRENT_SCHEMA_VERSION,
                    received=schema_version,
                )
            )
            return CompatibilityResult(issues=tuple(issues))

    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        return CompatibilityResult(issues=tuple(issues))
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            continue
        type_id = node.get("type")
        version = node.get("type_version")
        if not isinstance(type_id, str) or not isinstance(version, str):
            continue
        try:
            registry.resolve(type_id, version)
        except UnknownNodeDefinitionError:
            issues.append(
                CompatibilityIssue(
                    code=CompatibilityCode.UNSUPPORTED_NODE_DEFINITION,
                    message=f"node definition '{type_id}' version '{version}' is not registered",
                    path=("nodes", index),
                    expected={"registered": True},
                    received={"type": type_id, "type_version": version},
                )
            )
    return CompatibilityResult(issues=tuple(issues))
