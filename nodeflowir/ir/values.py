"""Explicit values, references, and deterministic expression trees."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from nodeflowir._model import NodeFlowModel
from nodeflowir.ir.types import Identifier, PortName, TypeSpec

FieldPath = tuple[str | int, ...]


class LiteralValue(NodeFlowModel):
    """A JSON literal, optionally annotated when its type is not inferable."""

    kind: Literal["literal"] = "literal"
    value: JsonValue
    type: TypeSpec | None = None


class WorkflowInputReference(NodeFlowModel):
    """Reference a declared workflow input and, optionally, a nested field."""

    kind: Literal["workflow_input"] = "workflow_input"
    name: PortName
    path: FieldPath = ()


class NodeOutputReference(NodeFlowModel):
    """Reference an output port of a preceding node instance."""

    kind: Literal["node_output"] = "node_output"
    node_id: Identifier
    output: PortName
    path: FieldPath = ()


class LoopItemReference(NodeFlowModel):
    """Reference the current item within a named ``foreach`` scope."""

    kind: Literal["loop_item"] = "loop_item"
    loop_id: Identifier
    path: FieldPath = ()


class ConstantReference(NodeFlowModel):
    """Reference a workflow-level typed constant."""

    kind: Literal["constant"] = "constant"
    name: Identifier
    path: FieldPath = ()


class ObjectValue(NodeFlowModel):
    """Construct a JSON object structurally from nested values."""

    kind: Literal["object"] = "object"
    fields: dict[str, Value] = Field(default_factory=dict, max_length=1_000)


class ArrayValue(NodeFlowModel):
    """Construct a JSON array structurally from nested values."""

    kind: Literal["array"] = "array"
    items: list[Value] = Field(default_factory=list, max_length=10_000)


class UnaryOperator(StrEnum):
    NOT = "not"
    EXISTS = "exists"
    MISSING = "missing"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"
    LOWER = "lower"
    UPPER = "upper"
    TRIM = "trim"
    LENGTH = "length"
    EMPTY = "empty"
    NOT_EMPTY = "not_empty"
    FIRST = "first"
    LAST = "last"


class UnaryExpression(NodeFlowModel):
    """A deterministic operation over exactly one nested value."""

    kind: Literal["unary"] = "unary"
    operator: UnaryOperator
    operand: Value


class BinaryOperator(StrEnum):
    EQUAL = "eq"
    NOT_EQUAL = "ne"
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN_OR_EQUAL = "lte"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    MATCHES = "matches"
    IN = "in"
    NOT_IN = "not_in"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    MODULO = "modulo"
    BEFORE = "before"
    AFTER = "after"
    ADD_DURATION = "add_duration"
    SUBTRACT_DURATION = "subtract_duration"


class BinaryExpression(NodeFlowModel):
    """A deterministic operation over two nested values."""

    kind: Literal["binary"] = "binary"
    operator: BinaryOperator
    left: Value
    right: Value


class LogicalOperator(StrEnum):
    AND = "and"
    OR = "or"


class LogicalExpression(NodeFlowModel):
    """A nested boolean conjunction or disjunction."""

    kind: Literal["logical"] = "logical"
    operator: LogicalOperator
    operands: list[Value] = Field(min_length=2)


class BetweenExpression(NodeFlowModel):
    """An inclusive range check for comparable values, dates, or datetimes."""

    kind: Literal["between"] = "between"
    value: Value
    lower: Value
    upper: Value


class CollectionOperator(StrEnum):
    ANY = "any"
    ALL = "all"
    NONE = "none"
    COUNT = "count"
    FILTER = "filter"
    MAP = "map"
    SELECT = "select"
    PICK = "pick"
    OMIT = "omit"
    RENAME = "rename"
    DISTINCT = "distinct"
    UNIQUE = "unique"
    FIRST = "first"
    LAST = "last"
    LENGTH = "length"
    EMPTY = "empty"
    NOT_EMPTY = "not_empty"
    FLATTEN = "flatten"
    ZIP = "zip"
    SORT_BY = "sort_by"
    GROUP_BY = "group_by"


class SortDirection(StrEnum):
    ASCENDING = "ascending"
    DESCENDING = "descending"


class CollectionExpression(NodeFlowModel):
    """A bounded transformation or query over one collection value.

    ``item_scope`` binds a current item for ``predicate`` and ``mapper``.
    It is explicit so a serialized workflow never relies on an implicit local
    variable name.
    """

    kind: Literal["collection"] = "collection"
    operator: CollectionOperator
    collection: Value
    item_scope: Identifier | None = None
    predicate: Value | None = None
    mapper: Value | None = None
    fields: tuple[str, ...] = ()
    rename: dict[str, str] = Field(default_factory=dict)
    other: Value | None = None
    direction: SortDirection = SortDirection.ASCENDING

    @model_validator(mode="after")
    def _check_operator_arguments(self) -> CollectionExpression:
        predicate_operations = {
            CollectionOperator.ANY,
            CollectionOperator.ALL,
            CollectionOperator.NONE,
            CollectionOperator.FILTER,
        }
        if self.operator in predicate_operations and (
            self.item_scope is None or self.predicate is None
        ):
            raise ValueError(f"'{self.operator}' requires item_scope and predicate")
        if self.operator is CollectionOperator.MAP and (
            self.item_scope is None or self.mapper is None
        ):
            raise ValueError("'map' requires item_scope and mapper")
        if self.operator in {
            CollectionOperator.SELECT,
            CollectionOperator.PICK,
            CollectionOperator.OMIT,
        }:
            if not self.fields:
                raise ValueError(f"'{self.operator}' requires fields")
        if self.operator is CollectionOperator.RENAME and not self.rename:
            raise ValueError("'rename' requires a rename mapping")
        if self.operator in {CollectionOperator.SORT_BY, CollectionOperator.GROUP_BY} and (
            self.item_scope is None or self.mapper is None
        ):
            raise ValueError(f"'{self.operator}' requires item_scope and mapper")
        if self.operator is CollectionOperator.ZIP and self.other is None:
            raise ValueError("'zip' requires other")
        if self.predicate is not None and self.operator not in {
            *predicate_operations,
            CollectionOperator.COUNT,
        }:
            raise ValueError(f"'{self.operator}' does not accept a predicate")
        if self.mapper is not None and self.operator not in {
            CollectionOperator.MAP,
            CollectionOperator.SORT_BY,
            CollectionOperator.GROUP_BY,
        }:
            raise ValueError(f"'{self.operator}' does not accept a mapper")
        if self.fields and self.operator not in {
            CollectionOperator.SELECT,
            CollectionOperator.PICK,
            CollectionOperator.OMIT,
        }:
            raise ValueError(f"'{self.operator}' does not accept fields")
        if self.rename and self.operator is not CollectionOperator.RENAME:
            raise ValueError(f"'{self.operator}' does not accept a rename mapping")
        if self.other is not None and self.operator is not CollectionOperator.ZIP:
            raise ValueError(f"'{self.operator}' does not accept other")
        return self


class AggregationOperator(StrEnum):
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    DISTINCT = "distinct"


class AggregationExpression(NodeFlowModel):
    """An aggregation over a collection, optionally after a typed predicate."""

    kind: Literal["aggregation"] = "aggregation"
    operator: AggregationOperator
    collection: Value
    item_scope: Identifier | None = None
    predicate: Value | None = None

    @model_validator(mode="after")
    def _check_predicate_scope(self) -> AggregationExpression:
        if (self.item_scope is None) != (self.predicate is None):
            raise ValueError("an aggregation predicate requires both item_scope and predicate")
        return self


class CompositionOperator(StrEnum):
    MERGE = "merge"
    CONCAT = "concat"
    APPEND = "append"
    PREPEND = "prepend"


class CompositionExpression(NodeFlowModel):
    """Compose objects or collections without executable user code."""

    kind: Literal["composition"] = "composition"
    operator: CompositionOperator
    values: list[Value] = Field(min_length=2)

    @model_validator(mode="after")
    def _check_arity(self) -> CompositionExpression:
        if (
            self.operator in {CompositionOperator.APPEND, CompositionOperator.PREPEND}
            and len(self.values) != 2
        ):
            raise ValueError(f"'{self.operator}' requires exactly a collection and one item")
        return self


class JoinExpression(NodeFlowModel):
    """A bounded equi/predicate join between two collection values."""

    kind: Literal["join"] = "join"
    left: Value
    right: Value
    left_scope: Identifier
    right_scope: Identifier
    predicate: Value


class FallbackOperator(StrEnum):
    COALESCE = "coalesce"
    DEFAULT = "default"


class FallbackExpression(NodeFlowModel):
    """Use the first non-null value or a single explicit default."""

    kind: Literal["fallback"] = "fallback"
    operator: FallbackOperator
    values: list[Value] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_default_arity(self) -> FallbackExpression:
        if self.operator is FallbackOperator.DEFAULT and len(self.values) != 2:
            raise ValueError("'default' requires exactly primary and fallback values")
        return self


class ConversionExpression(NodeFlowModel):
    """An explicit, never implicit, conversion to a portable type."""

    kind: Literal["convert"] = "convert"
    value: Value
    target_type: TypeSpec


Value = Annotated[
    LiteralValue
    | WorkflowInputReference
    | NodeOutputReference
    | LoopItemReference
    | ConstantReference
    | ObjectValue
    | ArrayValue
    | UnaryExpression
    | BinaryExpression
    | LogicalExpression
    | BetweenExpression
    | CollectionExpression
    | AggregationExpression
    | CompositionExpression
    | JoinExpression
    | FallbackExpression
    | ConversionExpression,
    Field(discriminator="kind"),
]

for _model in (
    ObjectValue,
    ArrayValue,
    UnaryExpression,
    BinaryExpression,
    LogicalExpression,
    BetweenExpression,
    CollectionExpression,
    AggregationExpression,
    CompositionExpression,
    JoinExpression,
    FallbackExpression,
    ConversionExpression,
):
    _model.model_rebuild()
