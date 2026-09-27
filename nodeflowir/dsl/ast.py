"""Temporary syntax tree for NodeFlow DSL parsing.

These dataclasses deliberately model source syntax only.  They are not part of
the canonical workflow format; :mod:`nodeflowir.dsl.compiler` converts them to
NodeFlowIR Pydantic models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from pydantic import JsonValue

from nodeflowir.dsl.errors import SourceLocation


@dataclass(frozen=True)
class SyntaxNode:
    location: SourceLocation


@dataclass(frozen=True)
class FileSyntax(SyntaxNode):
    language_version: str
    workflow: WorkflowSyntax


@dataclass(frozen=True)
class ParameterSyntax(SyntaxNode):
    name: str
    type_name: str


@dataclass(frozen=True)
class WorkflowSyntax(SyntaxNode):
    name: str
    display_name: str | None
    version: int
    parameters: tuple[ParameterSyntax, ...]
    body: BlockSyntax


@dataclass(frozen=True)
class BlockSyntax(SyntaxNode):
    statements: tuple[StatementSyntax, ...]


@dataclass(frozen=True)
class LiteralSyntax(SyntaxNode):
    value: JsonValue
    duration_seconds: float | None = None


@dataclass(frozen=True)
class ReferenceSyntax(SyntaxNode):
    text: str


@dataclass(frozen=True)
class ListSyntax(SyntaxNode):
    items: tuple[ExpressionSyntax, ...]


@dataclass(frozen=True)
class ObjectSyntax(SyntaxNode):
    fields: tuple[tuple[str, ExpressionSyntax], ...]


@dataclass(frozen=True)
class CallSyntax(SyntaxNode):
    name: str
    arguments: tuple[ExpressionSyntax, ...]


@dataclass(frozen=True)
class UnarySyntax(SyntaxNode):
    operator: str
    operand: ExpressionSyntax


@dataclass(frozen=True)
class BinarySyntax(SyntaxNode):
    operator: str
    left: ExpressionSyntax
    right: ExpressionSyntax


ExpressionSyntax: TypeAlias = (
    LiteralSyntax
    | ReferenceSyntax
    | ListSyntax
    | ObjectSyntax
    | CallSyntax
    | UnarySyntax
    | BinarySyntax
)


@dataclass(frozen=True)
class AssignmentSyntax(SyntaxNode):
    name: str
    value: ExpressionSyntax


@dataclass(frozen=True)
class ConstantSyntax(SyntaxNode):
    name: str
    type_name: str
    value: ExpressionSyntax


@dataclass(frozen=True)
class RetrySyntax(SyntaxNode):
    attempts: int
    delay_seconds: float = 0
    backoff: str = "fixed"
    max_delay_seconds: float | None = None


@dataclass(frozen=True)
class ErrorSyntax(SyntaxNode):
    categories: tuple[str, ...]
    body: BlockSyntax


@dataclass(frozen=True)
class RunSyntax(SyntaxNode):
    alias: str | None
    type_id: str
    type_version: str | None
    assignments: tuple[AssignmentSyntax, ...] = ()
    retry: RetrySyntax | None = None
    timeout_seconds: float | None = None
    on_error: ErrorSyntax | None = None


@dataclass(frozen=True)
class IfSyntax(SyntaxNode):
    condition: ExpressionSyntax
    then: BlockSyntax
    else_if: tuple[tuple[ExpressionSyntax, BlockSyntax], ...] = ()
    else_body: BlockSyntax | None = None


@dataclass(frozen=True)
class MatchSyntax(SyntaxNode):
    subject: ExpressionSyntax
    cases: tuple[tuple[ExpressionSyntax, BlockSyntax], ...]
    default: BlockSyntax | None = None


@dataclass(frozen=True)
class ForeachSyntax(SyntaxNode):
    item_name: str
    collection: ExpressionSyntax
    body: BlockSyntax


@dataclass(frozen=True)
class RepeatSyntax(SyntaxNode):
    times: int
    body: BlockSyntax


@dataclass(frozen=True)
class ParallelSyntax(SyntaxNode):
    convergence: str
    body: BlockSyntax


@dataclass(frozen=True)
class BreakSyntax(SyntaxNode):
    pass


@dataclass(frozen=True)
class ContinueSyntax(SyntaxNode):
    pass


@dataclass(frozen=True)
class OutputSyntax(SyntaxNode):
    assignments: tuple[AssignmentSyntax, ...]


StatementSyntax: TypeAlias = (
    AssignmentSyntax
    | ConstantSyntax
    | RunSyntax
    | IfSyntax
    | MatchSyntax
    | ForeachSyntax
    | RepeatSyntax
    | ParallelSyntax
    | BreakSyntax
    | ContinueSyntax
    | OutputSyntax
)
