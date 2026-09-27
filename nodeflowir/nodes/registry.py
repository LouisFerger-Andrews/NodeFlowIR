"""An explicit, in-memory registry of node contracts."""

from __future__ import annotations

import re
from collections.abc import Iterator

from nodeflowir.nodes.contract import NodeDefinition


class NodeRegistryError(LookupError):
    """Base error for node contract registry operations."""


class DuplicateNodeDefinitionError(NodeRegistryError):
    """Raised when a contract type/version pair is registered twice."""


class UnknownNodeDefinitionError(NodeRegistryError):
    """Raised when a requested contract is not registered."""


class NodeRegistry:
    """Store node definitions by their stable type and contract version.

    The registry is intentionally in-memory and application-owned.  Discovery,
    persistence, and dependency injection belong to the consuming application.
    """

    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], NodeDefinition] = {}

    def register(self, definition: NodeDefinition, *, replace: bool = False) -> NodeDefinition:
        key = (definition.type, definition.version)
        if key in self._definitions and not replace:
            raise DuplicateNodeDefinitionError(
                f"node definition '{definition.type}' version '{definition.version}' is registered"
            )
        self._definitions[key] = definition
        return definition

    def resolve(self, type_id: str, version: str) -> NodeDefinition:
        try:
            return self._definitions[(type_id, version)]
        except KeyError as error:
            raise UnknownNodeDefinitionError(
                f"node definition '{type_id}' version '{version}' is not registered"
            ) from error

    def get(self, type_id: str, version: str | None = None) -> NodeDefinition:
        """Look up one definition, using the latest registered version if omitted."""

        if version is not None:
            return self.resolve(type_id, version)
        matches = [
            definition
            for (registered_type, _), definition in self._definitions.items()
            if registered_type == type_id
        ]
        if not matches:
            raise UnknownNodeDefinitionError(f"node definition '{type_id}' is not registered")
        return max(matches, key=lambda definition: _version_key(definition.version))

    def versions(self, type_id: str) -> tuple[str, ...]:
        """Return the registered versions of one stable node type, newest first."""

        versions = [
            version for registered_type, version in self._definitions if registered_type == type_id
        ]
        return tuple(sorted(versions, key=_version_key, reverse=True))

    def node_types(self) -> tuple[str, ...]:
        """List stable node type identifiers in deterministic order."""

        return tuple(sorted({type_id for type_id, _ in self._definitions}))

    def metadata(self, type_id: str, version: str | None = None) -> dict[str, object]:
        """Retrieve a JSON-compatible API document for one registered definition."""

        return self.get(type_id, version).metadata_document()

    def list_metadata(self) -> tuple[dict[str, object], ...]:
        """Return serializable metadata for every definition in stable order."""

        definitions = sorted(
            self._definitions.values(),
            key=lambda definition: (definition.type, _version_key(definition.version)),
        )
        return tuple(definition.metadata_document() for definition in definitions)

    def __contains__(self, key: tuple[str, str]) -> bool:
        return key in self._definitions

    def __iter__(self) -> Iterator[NodeDefinition]:
        yield from self._definitions.values()


def _version_key(value: str) -> tuple[int, int, int, int, str]:
    """Order supported semantic versions without adding a packaging dependency."""

    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?(?:\+.*)?", value)
    if match is None:  # Pydantic has already validated versions; retain a safe fallback.
        return (0, 0, 0, 0, value)
    major, minor, patch, prerelease = match.groups()
    return (int(major), int(minor), int(patch or 0), int(prerelease is None), prerelease or "")
