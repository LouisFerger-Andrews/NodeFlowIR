"""Structured, deterministic workflow control-flow models."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from nodeflowir._model import NodeFlowModel
from nodeflowir.ir.types import Identifier
from nodeflowir.ir.values import Value


class FlowBlock(NodeFlowModel):
    """An ordered sequence of control-flow steps."""

    steps: list[FlowStep] = Field(min_length=1)


class NodeStep(NodeFlowModel):
    """Place one configured node instance at this point in the flow."""

    kind: Literal["node"] = "node"
    node_id: Identifier
    on_error: ErrorFlow | None = None


class ConditionalBranch(NodeFlowModel):
    """One explicit ``else if`` branch."""

    condition: Value
    body: FlowBlock


class IfStep(NodeFlowModel):
    """A deterministic if / else-if / else branch."""

    kind: Literal["if"] = "if"
    condition: Value
    then: FlowBlock
    else_if: list[ConditionalBranch] = Field(default_factory=list)
    else_body: FlowBlock | None = None


class MatchCase(NodeFlowModel):
    """One value-matching branch in a ``match`` step."""

    value: Value
    body: FlowBlock


class MatchStep(NodeFlowModel):
    """A multi-branch equality match with an optional default branch."""

    kind: Literal["match"] = "match"
    subject: Value
    cases: list[MatchCase] = Field(min_length=1)
    default: FlowBlock | None = None


class ForeachStep(NodeFlowModel):
    """A bounded iteration over a collection with a named current-item scope."""

    kind: Literal["foreach"] = "foreach"
    id: Identifier
    collection: Value
    body: FlowBlock


class RepeatStep(NodeFlowModel):
    """A statically bounded repetition block."""

    kind: Literal["repeat"] = "repeat"
    id: Identifier
    times: int = Field(ge=1, le=100_000)
    body: FlowBlock


class ConvergenceStrategy(StrEnum):
    ALL = "all"
    ANY = "any"


class ParallelBranch(NodeFlowModel):
    """One named branch in a declarative fan-out/fan-in block."""

    id: Identifier
    body: FlowBlock


class ParallelStep(NodeFlowModel):
    """A declarative parallel fan-out with an explicit convergence policy."""

    kind: Literal["parallel"] = "parallel"
    id: Identifier
    branches: list[ParallelBranch] = Field(min_length=2)
    convergence: ConvergenceStrategy = ConvergenceStrategy.ALL


class BreakStep(NodeFlowModel):
    """Exit the innermost bounded iteration block."""

    kind: Literal["break"] = "break"


class ContinueStep(NodeFlowModel):
    """Continue the next iteration of the innermost iteration block."""

    kind: Literal["continue"] = "continue"


class ErrorCategory(StrEnum):
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ErrorFlow(NodeFlowModel):
    """A workflow-oriented error path for the enclosing node invocation."""

    categories: tuple[ErrorCategory, ...] = ()
    body: FlowBlock


FlowStep = Annotated[
    NodeStep
    | IfStep
    | MatchStep
    | ForeachStep
    | RepeatStep
    | ParallelStep
    | BreakStep
    | ContinueStep,
    Field(discriminator="kind"),
]

for _model in (
    FlowBlock,
    NodeStep,
    ConditionalBranch,
    IfStep,
    MatchCase,
    MatchStep,
    ForeachStep,
    RepeatStep,
    ParallelBranch,
    ParallelStep,
    ErrorFlow,
):
    _model.model_rebuild()
