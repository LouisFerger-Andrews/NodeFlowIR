"""Opt-in schema migration plumbing for JSON workflow documents."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from pydantic import JsonValue

WorkflowDocument = dict[str, JsonValue]
Migration = Callable[[WorkflowDocument], WorkflowDocument]


class MigrationError(ValueError):
    """Raised when no migration path exists or a migration is malformed."""


class MigrationRegistry:
    """Store explicit, pure transformations between IR schema versions.

    NodeFlowIR ships no historical migrations in its first release.  The
    registry exists so migrations can be introduced without changing the
    canonical model or silently accepting an incompatible document.
    """

    def __init__(self) -> None:
        self._migrations: dict[tuple[str, str], Migration] = {}

    def register(self, from_version: str, to_version: str, migration: Migration) -> None:
        key = (from_version, to_version)
        if key in self._migrations:
            raise MigrationError(f"migration from '{from_version}' to '{to_version}' is registered")
        self._migrations[key] = migration

    def migrate(
        self, document: WorkflowDocument, *, from_version: str, to_version: str
    ) -> WorkflowDocument:
        path = self._find_path(from_version, to_version)
        if path is None:
            raise MigrationError(f"no migration path from '{from_version}' to '{to_version}'")
        result = document
        for source, target in path:
            result = self._migrations[(source, target)](result)
            if result.get("schema_version") != target:
                raise MigrationError(
                    f"migration from '{source}' to '{target}' did not set "
                    f"schema_version to '{target}'"
                )
        return result

    def can_migrate(self, from_version: str, to_version: str) -> bool:
        """Return whether an explicit migration path has been registered."""

        return self._find_path(from_version, to_version) is not None

    def _find_path(self, from_version: str, to_version: str) -> list[tuple[str, str]] | None:
        if from_version == to_version:
            return []
        queue: deque[tuple[str, list[tuple[str, str]]]] = deque([(from_version, [])])
        seen = {from_version}
        path: list[tuple[str, str]] | None = None
        while queue:
            current, current_path = queue.popleft()
            for source, target in self._migrations:
                if source != current or target in seen:
                    continue
                candidate = [*current_path, (source, target)]
                if target == to_version:
                    path = candidate
                    queue.clear()
                    break
                seen.add(target)
                queue.append((target, candidate))
        if path is None:
            return None
        return path
