"""Small, portable metadata contracts shared by definitions and discovery."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from nodeflowir._model import NodeFlowModel

ReplacementIdentifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=300,
        description="A stable application or catalog replacement identifier.",
    ),
]


class Deprecation(NodeFlowModel):
    """Guidance for a still-loadable capability that should not be newly selected.

    This is discovery metadata only.  It does not invalidate historical
    workflows or apply a migration automatically.
    """

    deprecated: Literal[True] = True
    message: str | None = Field(default=None, min_length=1, max_length=1_000)
    replacement: ReplacementIdentifier | None = None
