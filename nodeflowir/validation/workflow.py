"""Semantic validation for NodeFlowIR's declarative workflow contract."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from nodeflowir.ir.control_flow import (
    BreakStep,
    ContinueStep,
    ErrorFlow,
    FlowBlock,
    ForeachStep,
    IfStep,
    MatchStep,
    NodeStep,
    ParallelStep,
    RepeatStep,
)
from nodeflowir.ir.edge import DataConnection
from nodeflowir.ir.types import TypeSpec, ValueKind
from nodeflowir.ir.values import (
    AggregationExpression,
    AggregationOperator,
    ArrayValue,
    BetweenExpression,
    BinaryExpression,
    BinaryOperator,
    CollectionExpression,
    CollectionOperator,
    CompositionExpression,
    CompositionOperator,
    ConstantReference,
    ConversionExpression,
    FallbackExpression,
    JoinExpression,
    LiteralValue,
    LogicalExpression,
    LoopItemReference,
    NodeOutputReference,
    ObjectValue,
    UnaryExpression,
    UnaryOperator,
    Value,
    WorkflowInputReference,
)
from nodeflowir.ir.workflow import Workflow
from nodeflowir.nodes import NodeDefinition, NodeRegistry, UnknownNodeDefinitionError
from nodeflowir.validation.issues import IssueCode, ValidationIssue, ValidationResult


def _type(kind: ValueKind, **kwargs: object) -> TypeSpec:
    return TypeSpec(kind=kind, **kwargs)


ANY = _type(ValueKind.ANY)
BOOLEAN = _type(ValueKind.BOOLEAN)
INTEGER = _type(ValueKind.INTEGER)
NUMBER = _type(ValueKind.NUMBER)
STRING = _type(ValueKind.STRING)
NULL = _type(ValueKind.NULL)


@dataclass
class _Context:
    workflow: Workflow
    definitions: dict[str, NodeDefinition]
    connections: dict[str, list[tuple[int, DataConnection]]]
    issues: list[ValidationIssue]
    visible_nodes: set[str] = field(default_factory=set)
    loop_items: dict[str, TypeSpec] = field(default_factory=dict)
    seen_node_steps: set[str] = field(default_factory=set)
    checked_connections: set[int] = field(default_factory=set)

    def scoped(
        self,
        *,
        visible_nodes: set[str] | None = None,
        loop_items: dict[str, TypeSpec] | None = None,
    ) -> _Context:
        return _Context(
            workflow=self.workflow,
            definitions=self.definitions,
            connections=self.connections,
            issues=self.issues,
            visible_nodes=set(self.visible_nodes if visible_nodes is None else visible_nodes),
            loop_items=dict(self.loop_items if loop_items is None else loop_items),
            seen_node_steps=self.seen_node_steps,
            checked_connections=self.checked_connections,
        )

    def issue(self, code: IssueCode, message: str, location: tuple[str | int, ...]) -> None:
        self.issues.append(ValidationIssue(code=code, message=message, location=location))


def _literal_type(value: object) -> TypeSpec:
    if value is None:
        return NULL
    if isinstance(value, bool):
        return _type(ValueKind.BOOLEAN, enum_values=(value,))
    if isinstance(value, int):
        return _type(ValueKind.INTEGER, enum_values=(value,))
    if isinstance(value, float):
        return _type(ValueKind.NUMBER, enum_values=(value,))
    if isinstance(value, str):
        return _type(ValueKind.STRING, enum_values=(value,))
    if isinstance(value, list):
        items = [_literal_type(item) for item in value]
        return _type(ValueKind.ARRAY, items=_common_type(items))
    if isinstance(value, dict):
        return _type(
            ValueKind.OBJECT,
            fields={name: _literal_type(item) for name, item in value.items()},
        )
    return ANY


def _common_type(types: list[TypeSpec]) -> TypeSpec:
    if not types:
        return ANY
    candidate = types[0]
    if all(value_type.is_assignable_to(candidate) for value_type in types):
        return candidate
    if all(value_type.kind in {ValueKind.INTEGER, ValueKind.NUMBER} for value_type in types):
        return NUMBER
    return ANY


def _resolve_path(
    value_type: TypeSpec,
    path: tuple[str | int, ...],
    context: _Context,
    location: tuple[str | int, ...],
) -> TypeSpec:
    current = value_type
    for segment in path:
        if current.kind is ValueKind.ANY:
            return ANY
        if current.kind is ValueKind.OBJECT:
            if not isinstance(segment, str):
                context.issue(
                    IssueCode.INVALID_REFERENCE_PATH,
                    "an object reference path requires a field name",
                    location,
                )
                return ANY
            if not current.fields:
                return ANY
            if segment not in current.fields:
                context.issue(
                    IssueCode.INVALID_REFERENCE_PATH,
                    f"object type has no field '{segment}'",
                    location,
                )
                return ANY
            current = current.fields[segment]
            continue
        if current.kind is ValueKind.ARRAY:
            if not isinstance(segment, int):
                context.issue(
                    IssueCode.INVALID_REFERENCE_PATH,
                    "an array reference path requires a numeric index",
                    location,
                )
                return ANY
            current = current.items or ANY
            continue
        context.issue(
            IssueCode.INVALID_REFERENCE_PATH,
            f"cannot select '{segment}' from {current.kind}",
            location,
        )
        return ANY
    return current


def _require(
    actual: TypeSpec,
    expected: TypeSpec,
    context: _Context,
    location: tuple[str | int, ...],
    message: str,
    *,
    code: IssueCode = IssueCode.INCOMPATIBLE_VALUE_TYPE,
) -> None:
    if not actual.is_assignable_to(expected):
        context.issue(code, message, location)


def _is_boolean(value_type: TypeSpec) -> bool:
    return value_type.kind in {ValueKind.BOOLEAN, ValueKind.ANY}


def _is_numeric(value_type: TypeSpec) -> bool:
    return value_type.kind in {ValueKind.INTEGER, ValueKind.NUMBER, ValueKind.ANY}


def _is_collection(value_type: TypeSpec) -> bool:
    return value_type.kind in {ValueKind.ARRAY, ValueKind.ANY}


def _is_orderable(value_type: TypeSpec) -> bool:
    return value_type.kind in {
        ValueKind.INTEGER,
        ValueKind.NUMBER,
        ValueKind.STRING,
        ValueKind.DATE,
        ValueKind.DATETIME,
        ValueKind.DURATION,
        ValueKind.ANY,
    }


def _same_or_dynamic(left: TypeSpec, right: TypeSpec) -> bool:
    return left.is_assignable_to(right) or right.is_assignable_to(left)


def _expression_issue(
    context: _Context,
    operator: str,
    message: str,
    location: tuple[str | int, ...],
) -> None:
    context.issue(
        IssueCode.INVALID_EXPRESSION_OPERATOR,
        f"operator '{operator}' {message}",
        location,
    )


def _infer_value(
    value: Value,
    context: _Context,
    location: tuple[str | int, ...],
) -> TypeSpec:
    if isinstance(value, LiteralValue):
        literal_type = value.type or _literal_type(value.value)
        if value.type is not None and not value.type.accepts(value.value):
            context.issue(
                IssueCode.INVALID_LITERAL_TYPE,
                "typed literal does not conform to its declared type",
                location,
            )
        return literal_type

    if isinstance(value, WorkflowInputReference):
        workflow_input = context.workflow.inputs.get(value.name)
        if workflow_input is None:
            context.issue(
                IssueCode.UNKNOWN_WORKFLOW_INPUT,
                f"workflow input '{value.name}' does not exist",
                location,
            )
            return ANY
        return _resolve_path(workflow_input.type, value.path, context, location)

    if isinstance(value, ConstantReference):
        constant = context.workflow.constants.get(value.name)
        if constant is None:
            context.issue(
                IssueCode.UNKNOWN_CONSTANT,
                f"workflow constant '{value.name}' does not exist",
                location,
            )
            return ANY
        return _resolve_path(constant.type, value.path, context, location)

    if isinstance(value, LoopItemReference):
        item_type = context.loop_items.get(value.loop_id)
        if item_type is None:
            context.issue(
                IssueCode.UNKNOWN_LOOP_SCOPE,
                f"loop item scope '{value.loop_id}' is not active",
                location,
            )
            return ANY
        return _resolve_path(item_type, value.path, context, location)

    if isinstance(value, NodeOutputReference):
        if value.node_id not in {node.id for node in context.workflow.nodes}:
            context.issue(
                IssueCode.UNKNOWN_NODE,
                f"node '{value.node_id}' does not exist",
                location,
            )
            return ANY
        if value.node_id not in context.visible_nodes:
            context.issue(
                IssueCode.UNAVAILABLE_NODE_OUTPUT,
                f"output from node '{value.node_id}' is not available at this point in the flow",
                location,
            )
            return ANY
        definition = context.definitions.get(value.node_id)
        if definition is None:
            return ANY
        output = definition.outputs.get(value.output)
        if output is None:
            context.issue(
                IssueCode.UNKNOWN_NODE_OUTPUT,
                f"node '{value.node_id}' has no output port '{value.output}'",
                location,
            )
            return ANY
        return _resolve_path(output.type, value.path, context, location)

    if isinstance(value, ObjectValue):
        return _type(
            ValueKind.OBJECT,
            fields={
                name: _infer_value(field_value, context, (*location, "fields", name))
                for name, field_value in value.fields.items()
            },
        )

    if isinstance(value, ArrayValue):
        return _type(
            ValueKind.ARRAY,
            items=_common_type(
                [
                    _infer_value(item, context, (*location, "items", index))
                    for index, item in enumerate(value.items)
                ]
            ),
        )

    if isinstance(value, UnaryExpression):
        operand = _infer_value(value.operand, context, (*location, "operand"))
        if value.operator is UnaryOperator.NOT:
            if not _is_boolean(operand):
                _expression_issue(context, value.operator, "requires a boolean operand", location)
            return BOOLEAN
        if value.operator in {
            UnaryOperator.EXISTS,
            UnaryOperator.MISSING,
            UnaryOperator.IS_NULL,
            UnaryOperator.IS_NOT_NULL,
            UnaryOperator.EMPTY,
            UnaryOperator.NOT_EMPTY,
        }:
            if value.operator in {
                UnaryOperator.EMPTY,
                UnaryOperator.NOT_EMPTY,
            } and operand.kind not in {
                ValueKind.ARRAY,
                ValueKind.STRING,
                ValueKind.OBJECT,
                ValueKind.ANY,
            }:
                _expression_issue(
                    context, value.operator, "requires a collection, string, or object", location
                )
            return BOOLEAN
        if value.operator in {UnaryOperator.LOWER, UnaryOperator.UPPER, UnaryOperator.TRIM}:
            if operand.kind not in {ValueKind.STRING, ValueKind.ANY}:
                _expression_issue(context, value.operator, "requires a string operand", location)
            return STRING
        if value.operator is UnaryOperator.LENGTH:
            if operand.kind not in {
                ValueKind.ARRAY,
                ValueKind.STRING,
                ValueKind.OBJECT,
                ValueKind.ANY,
            }:
                _expression_issue(
                    context, value.operator, "requires a collection, string, or object", location
                )
            return INTEGER
        if value.operator in {UnaryOperator.FIRST, UnaryOperator.LAST}:
            if not _is_collection(operand):
                _expression_issue(context, value.operator, "requires an array operand", location)
                return ANY
            return (operand.items or ANY).model_copy(update={"nullable": True})

    if isinstance(value, BinaryExpression):
        left = _infer_value(value.left, context, (*location, "left"))
        right = _infer_value(value.right, context, (*location, "right"))
        comparison_operators = {BinaryOperator.EQUAL, BinaryOperator.NOT_EQUAL}
        ordering_operators = {
            BinaryOperator.GREATER_THAN,
            BinaryOperator.LESS_THAN,
            BinaryOperator.GREATER_THAN_OR_EQUAL,
            BinaryOperator.LESS_THAN_OR_EQUAL,
            BinaryOperator.BEFORE,
            BinaryOperator.AFTER,
        }
        arithmetic_operators = {
            BinaryOperator.ADD,
            BinaryOperator.SUBTRACT,
            BinaryOperator.MULTIPLY,
            BinaryOperator.DIVIDE,
            BinaryOperator.MODULO,
        }
        if value.operator in comparison_operators:
            if not _same_or_dynamic(left, right):
                _expression_issue(context, value.operator, "requires compatible operands", location)
            return BOOLEAN
        if value.operator in ordering_operators:
            if not (_is_orderable(left) and _same_or_dynamic(left, right)):
                _expression_issue(
                    context, value.operator, "requires compatible orderable operands", location
                )
            return BOOLEAN
        if value.operator in {
            BinaryOperator.CONTAINS,
            BinaryOperator.STARTS_WITH,
            BinaryOperator.ENDS_WITH,
            BinaryOperator.MATCHES,
        }:
            if value.operator is BinaryOperator.CONTAINS and left.kind is ValueKind.ARRAY:
                if left.items is not None and not right.is_assignable_to(left.items):
                    _expression_issue(
                        context,
                        value.operator,
                        "requires an item compatible with the array",
                        location,
                    )
            elif left.kind not in {ValueKind.STRING, ValueKind.ANY} or right.kind not in {
                ValueKind.STRING,
                ValueKind.ANY,
            }:
                _expression_issue(context, value.operator, "requires string operands", location)
            return BOOLEAN
        if value.operator in {BinaryOperator.IN, BinaryOperator.NOT_IN}:
            if not _is_collection(right):
                _expression_issue(
                    context, value.operator, "requires an array as its right operand", location
                )
            elif right.items is not None and not left.is_assignable_to(right.items):
                _expression_issue(
                    context, value.operator, "requires a value compatible with the array", location
                )
            return BOOLEAN
        if value.operator in arithmetic_operators:
            if not (_is_numeric(left) and _is_numeric(right)):
                _expression_issue(context, value.operator, "requires numeric operands", location)
                return ANY
            if value.operator is BinaryOperator.DIVIDE:
                return NUMBER
            return NUMBER if ValueKind.NUMBER in {left.kind, right.kind} else INTEGER
        if value.operator in {BinaryOperator.ADD_DURATION, BinaryOperator.SUBTRACT_DURATION}:
            if left.kind not in {
                ValueKind.DATE,
                ValueKind.DATETIME,
                ValueKind.ANY,
            } or right.kind not in {
                ValueKind.DURATION,
                ValueKind.ANY,
            }:
                _expression_issue(
                    context, value.operator, "requires a date/datetime and a duration", location
                )
                return ANY
            return left

    if isinstance(value, LogicalExpression):
        for index, operand in enumerate(value.operands):
            operand_type = _infer_value(operand, context, (*location, "operands", index))
            if not _is_boolean(operand_type):
                _expression_issue(context, value.operator, "requires boolean operands", location)
        return BOOLEAN

    if isinstance(value, BetweenExpression):
        types = [
            _infer_value(value.value, context, (*location, "value")),
            _infer_value(value.lower, context, (*location, "lower")),
            _infer_value(value.upper, context, (*location, "upper")),
        ]
        if not _is_orderable(types[0]) or not all(
            _same_or_dynamic(types[0], item) for item in types[1:]
        ):
            _expression_issue(context, "between", "requires compatible orderable values", location)
        return BOOLEAN

    if isinstance(value, CollectionExpression):
        return _infer_collection(value, context, location)
    if isinstance(value, AggregationExpression):
        return _infer_aggregation(value, context, location)
    if isinstance(value, CompositionExpression):
        return _infer_composition(value, context, location)
    if isinstance(value, JoinExpression):
        left = _infer_value(value.left, context, (*location, "left"))
        right = _infer_value(value.right, context, (*location, "right"))
        if not (_is_collection(left) and _is_collection(right)):
            context.issue(
                IssueCode.INVALID_COLLECTION_OPERATION, "join requires two collections", location
            )
            return _type(ValueKind.ARRAY, items=ANY)
        scoped = context.scoped(
            loop_items={
                **context.loop_items,
                value.left_scope: left.items or ANY,
                value.right_scope: right.items or ANY,
            }
        )
        predicate = _infer_value(value.predicate, scoped, (*location, "predicate"))
        if not _is_boolean(predicate):
            context.issue(
                IssueCode.INVALID_CONDITION_TYPE, "join predicate must be boolean", location
            )
        return _type(ValueKind.ARRAY, items=ANY)
    if isinstance(value, FallbackExpression):
        values = [
            _infer_value(item, context, (*location, "values", index))
            for index, item in enumerate(value.values)
        ]
        result = _common_type(values)
        if result.kind is ValueKind.ANY and not any(item.kind is ValueKind.ANY for item in values):
            _expression_issue(
                context, value.operator, "requires compatible fallback values", location
            )
        return result.model_copy(update={"nullable": False})
    if isinstance(value, ConversionExpression):
        source = _infer_value(value.value, context, (*location, "value"))
        _validate_conversion(source, value.target_type, context, location)
        return value.target_type
    return ANY


def _scoped_predicate(
    collection: CollectionExpression | AggregationExpression,
    item_type: TypeSpec,
    context: _Context,
    location: tuple[str | int, ...],
) -> None:
    if collection.predicate is None:
        return
    if collection.item_scope is None:
        context.issue(
            IssueCode.INVALID_COLLECTION_OPERATION,
            "collection predicate has no item scope",
            location,
        )
        return
    scoped = context.scoped(loop_items={**context.loop_items, collection.item_scope: item_type})
    predicate_type = _infer_value(collection.predicate, scoped, (*location, "predicate"))
    if not _is_boolean(predicate_type):
        context.issue(
            IssueCode.INVALID_CONDITION_TYPE, "collection predicate must be boolean", location
        )


def _infer_collection(
    value: CollectionExpression,
    context: _Context,
    location: tuple[str | int, ...],
) -> TypeSpec:
    collection_type = _infer_value(value.collection, context, (*location, "collection"))
    if not _is_collection(collection_type):
        context.issue(
            IssueCode.INVALID_COLLECTION_OPERATION,
            f"'{value.operator}' requires a collection value",
            location,
        )
        return ANY
    item_type = collection_type.items or ANY
    if value.predicate is not None:
        _scoped_predicate(value, item_type, context, location)
    if value.operator in {CollectionOperator.ANY, CollectionOperator.ALL, CollectionOperator.NONE}:
        return BOOLEAN
    if value.operator in {CollectionOperator.COUNT, CollectionOperator.LENGTH}:
        return INTEGER
    if value.operator in {CollectionOperator.EMPTY, CollectionOperator.NOT_EMPTY}:
        return BOOLEAN
    if value.operator is CollectionOperator.FILTER:
        return _type(ValueKind.ARRAY, items=item_type)
    if value.operator is CollectionOperator.MAP:
        if value.item_scope is None or value.mapper is None:
            return _type(ValueKind.ARRAY, items=ANY)
        scoped = context.scoped(loop_items={**context.loop_items, value.item_scope: item_type})
        return _type(
            ValueKind.ARRAY, items=_infer_value(value.mapper, scoped, (*location, "mapper"))
        )
    if value.operator in {
        CollectionOperator.SELECT,
        CollectionOperator.PICK,
        CollectionOperator.OMIT,
        CollectionOperator.RENAME,
    }:
        if item_type.kind not in {ValueKind.OBJECT, ValueKind.ANY}:
            context.issue(
                IssueCode.INVALID_COLLECTION_OPERATION,
                f"'{value.operator}' requires object collection items",
                location,
            )
            return _type(ValueKind.ARRAY, items=ANY)
        if item_type.kind is ValueKind.ANY or not item_type.fields:
            return _type(ValueKind.ARRAY, items=ANY)
        fields = dict(item_type.fields)
        if value.operator in {CollectionOperator.SELECT, CollectionOperator.PICK}:
            missing = set(value.fields) - set(fields)
            if missing:
                context.issue(
                    IssueCode.INVALID_COLLECTION_OPERATION,
                    f"'{value.operator}' selects unknown fields: {', '.join(sorted(missing))}",
                    location,
                )
            fields = {name: fields[name] for name in value.fields if name in fields}
        elif value.operator is CollectionOperator.OMIT:
            fields = {name: item for name, item in fields.items() if name not in set(value.fields)}
        else:
            fields = {value.rename.get(name, name): item for name, item in fields.items()}
        return _type(ValueKind.ARRAY, items=_type(ValueKind.OBJECT, fields=fields))
    if value.operator in {
        CollectionOperator.DISTINCT,
        CollectionOperator.UNIQUE,
        CollectionOperator.SORT_BY,
    }:
        if value.operator is CollectionOperator.SORT_BY and value.mapper is not None:
            if value.item_scope is None:
                return _type(ValueKind.ARRAY, items=item_type)
            scoped = context.scoped(loop_items={**context.loop_items, value.item_scope: item_type})
            key_type = _infer_value(value.mapper, scoped, (*location, "mapper"))
            if not _is_orderable(key_type):
                context.issue(
                    IssueCode.INVALID_COLLECTION_OPERATION,
                    "sort_by mapper must return an orderable value",
                    location,
                )
        return _type(ValueKind.ARRAY, items=item_type)
    if value.operator in {CollectionOperator.FIRST, CollectionOperator.LAST}:
        return item_type.model_copy(update={"nullable": True})
    if value.operator is CollectionOperator.FLATTEN:
        if item_type.kind not in {ValueKind.ARRAY, ValueKind.ANY}:
            context.issue(
                IssueCode.INVALID_COLLECTION_OPERATION,
                "flatten requires a collection of collections",
                location,
            )
            return _type(ValueKind.ARRAY, items=ANY)
        return _type(ValueKind.ARRAY, items=item_type.items or ANY)
    if value.operator is CollectionOperator.ZIP:
        other_type = (
            _infer_value(value.other, context, (*location, "other")) if value.other else ANY
        )
        if not _is_collection(other_type):
            context.issue(
                IssueCode.INVALID_COLLECTION_OPERATION, "zip requires another collection", location
            )
        return _type(
            ValueKind.ARRAY,
            items=_type(ValueKind.ARRAY, items=_common_type([item_type, other_type.items or ANY])),
        )
    if value.operator is CollectionOperator.GROUP_BY:
        if value.item_scope is None or value.mapper is None:
            return _type(ValueKind.OBJECT)
        scoped = context.scoped(loop_items={**context.loop_items, value.item_scope: item_type})
        key_type = _infer_value(value.mapper, scoped, (*location, "mapper"))
        if key_type.kind not in {
            ValueKind.STRING,
            ValueKind.INTEGER,
            ValueKind.NUMBER,
            ValueKind.ANY,
        }:
            context.issue(
                IssueCode.INVALID_COLLECTION_OPERATION,
                "group_by mapper must return a scalar key",
                location,
            )
        return _type(ValueKind.OBJECT)
    return ANY


def _infer_aggregation(
    value: AggregationExpression,
    context: _Context,
    location: tuple[str | int, ...],
) -> TypeSpec:
    collection_type = _infer_value(value.collection, context, (*location, "collection"))
    if not _is_collection(collection_type):
        context.issue(
            IssueCode.INVALID_COLLECTION_OPERATION,
            f"'{value.operator}' requires a collection value",
            location,
        )
        return ANY
    item_type = collection_type.items or ANY
    _scoped_predicate(value, item_type, context, location)
    if value.operator in {AggregationOperator.SUM, AggregationOperator.AVG}:
        if not _is_numeric(item_type):
            context.issue(
                IssueCode.INVALID_COLLECTION_OPERATION,
                f"'{value.operator}' requires numeric collection items",
                location,
            )
        return NUMBER if value.operator is AggregationOperator.AVG else item_type
    if value.operator in {AggregationOperator.MIN, AggregationOperator.MAX}:
        if not _is_orderable(item_type):
            context.issue(
                IssueCode.INVALID_COLLECTION_OPERATION,
                f"'{value.operator}' requires orderable collection items",
                location,
            )
        return item_type.model_copy(update={"nullable": True})
    if value.operator is AggregationOperator.COUNT:
        return INTEGER
    if value.operator is AggregationOperator.DISTINCT:
        return _type(ValueKind.ARRAY, items=item_type)
    return ANY


def _infer_composition(
    value: CompositionExpression,
    context: _Context,
    location: tuple[str | int, ...],
) -> TypeSpec:
    types = [
        _infer_value(item, context, (*location, "values", index))
        for index, item in enumerate(value.values)
    ]
    if value.operator is CompositionOperator.MERGE:
        if not all(item.kind in {ValueKind.OBJECT, ValueKind.ANY} for item in types):
            _expression_issue(context, value.operator, "requires object operands", location)
            return ANY
        fields: dict[str, TypeSpec] = {}
        for item in types:
            fields.update(item.fields)
        return _type(ValueKind.OBJECT, fields=fields)
    if value.operator is CompositionOperator.CONCAT:
        if not all(_is_collection(item) for item in types):
            _expression_issue(context, value.operator, "requires collection operands", location)
            return ANY
        return _type(ValueKind.ARRAY, items=_common_type([item.items or ANY for item in types]))
    first, second = types[0], types[1]
    if not _is_collection(first):
        _expression_issue(
            context, value.operator, "requires a collection as its first operand", location
        )
        return ANY
    if first.items is not None and not second.is_assignable_to(first.items):
        _expression_issue(
            context, value.operator, "requires an item compatible with the collection", location
        )
    return _type(ValueKind.ARRAY, items=first.items or ANY)


def _validate_conversion(
    source: TypeSpec,
    target: TypeSpec,
    context: _Context,
    location: tuple[str | int, ...],
) -> None:
    if source.kind is ValueKind.ANY or target.kind is ValueKind.ANY:
        return
    allowed_sources: dict[ValueKind, set[ValueKind]] = {
        ValueKind.STRING: {
            ValueKind.STRING,
            ValueKind.INTEGER,
            ValueKind.NUMBER,
            ValueKind.BOOLEAN,
            ValueKind.DATE,
            ValueKind.DATETIME,
            ValueKind.DURATION,
            ValueKind.STATUS,
        },
        ValueKind.INTEGER: {
            ValueKind.STRING,
            ValueKind.INTEGER,
            ValueKind.NUMBER,
            ValueKind.BOOLEAN,
        },
        ValueKind.NUMBER: {ValueKind.STRING, ValueKind.INTEGER, ValueKind.NUMBER},
        ValueKind.BOOLEAN: {ValueKind.STRING, ValueKind.BOOLEAN},
        ValueKind.DATE: {ValueKind.STRING, ValueKind.DATE, ValueKind.DATETIME},
        ValueKind.DATETIME: {ValueKind.STRING, ValueKind.DATETIME},
        ValueKind.DURATION: {ValueKind.STRING, ValueKind.DURATION, ValueKind.NUMBER},
        ValueKind.STATUS: {ValueKind.STRING, ValueKind.STATUS},
    }
    if target.kind not in allowed_sources.get(source.kind, set()):
        context.issue(
            IssueCode.INVALID_CONVERSION,
            f"cannot explicitly convert {source.kind} to {target.kind}",
            location,
        )


def _validate_connection(
    connection_index: int,
    connection: DataConnection,
    context: _Context,
) -> None:
    if connection_index in context.checked_connections:
        return
    context.checked_connections.add(connection_index)
    definition = context.definitions.get(connection.target.node_id)
    if definition is None:
        return
    port = definition.inputs.get(connection.target.port)
    if port is None:
        return
    value_type = _infer_value(connection.value, context, ("connections", connection_index, "value"))
    _require(
        value_type,
        port.type,
        context,
        ("connections", connection_index, "value"),
        (
            f"binding for '{connection.target.node_id}.{connection.target.port}' does not match "
            "the node input type"
        ),
    )


def _validate_node_configuration(
    node_index: int,
    node_id: str,
    config: dict[str, object],
    definition: NodeDefinition,
    issues: list[ValidationIssue],
) -> None:
    fields = {field.name: field for field in definition.config}
    for name in config:
        if name not in fields:
            issues.append(
                ValidationIssue(
                    code=IssueCode.UNKNOWN_CONFIGURATION_FIELD,
                    message=f"node '{node_id}' has no configuration field '{name}'",
                    location=("nodes", node_index, "config", name),
                )
            )
    for name, config_field in fields.items():
        if config_field.required and name not in config:
            issues.append(
                ValidationIssue(
                    code=IssueCode.MISSING_REQUIRED_CONFIGURATION,
                    message=f"required configuration '{name}' is missing on node '{node_id}'",
                    location=("nodes", node_index, "config", name),
                )
            )
        elif name in config:
            for error in config_field.value_errors(config[name]):
                issues.append(
                    ValidationIssue(
                        code=IssueCode.INVALID_CONFIGURATION_VALUE,
                        message=f"configuration '{node_id}.{name}' {error}",
                        location=("nodes", node_index, "config", name),
                    )
                )


def _validate_node_step(node_id: str, context: _Context, location: tuple[str | int, ...]) -> None:
    if node_id in context.seen_node_steps:
        context.issue(
            IssueCode.DUPLICATE_NODE_STEP,
            f"node '{node_id}' appears more than once in workflow control flow",
            location,
        )
        return
    context.seen_node_steps.add(node_id)
    definition = context.definitions.get(node_id)
    if definition is None:
        return
    bindings = context.connections.get(node_id, [])
    bound_ports = {connection.target.port for _, connection in bindings}
    for connection_index, connection in bindings:
        _validate_connection(connection_index, connection, context)
    for name, port in definition.inputs.items():
        if port.required and name not in bound_ports:
            context.issue(
                IssueCode.MISSING_REQUIRED_INPUT,
                f"required input '{name}' is not bound on node '{node_id}'",
                (*location, "inputs", name),
            )


def _walk_error_flow(
    error_flow: ErrorFlow,
    context: _Context,
    location: tuple[str | int, ...],
    in_loop: bool,
) -> None:
    if len(set(error_flow.categories)) != len(error_flow.categories):
        context.issue(
            IssueCode.INVALID_ERROR_FLOW,
            "error-flow categories must be unique",
            location,
        )
    _walk_block(error_flow.body, context.scoped(), (*location, "body"), in_loop=in_loop)


def _walk_block(
    block: FlowBlock,
    context: _Context,
    location: tuple[str | int, ...],
    *,
    in_loop: bool,
) -> set[str]:
    visible = set(context.visible_nodes)
    for index, step in enumerate(block.steps):
        step_location = (*location, "steps", index)
        step_context = context.scoped(visible_nodes=visible)
        if isinstance(step, NodeStep):
            if step.node_id not in {node.id for node in context.workflow.nodes}:
                context.issue(
                    IssueCode.UNKNOWN_NODE,
                    f"node step references unknown node '{step.node_id}'",
                    step_location,
                )
            else:
                _validate_node_step(step.node_id, step_context, step_location)
                visible.add(step.node_id)
            if step.on_error is not None:
                _walk_error_flow(step.on_error, step_context, (*step_location, "on_error"), in_loop)
            continue
        if isinstance(step, IfStep):
            condition = _infer_value(step.condition, step_context, (*step_location, "condition"))
            if not _is_boolean(condition):
                context.issue(
                    IssueCode.INVALID_CONDITION_TYPE, "if condition must be boolean", step_location
                )
            _walk_block(step.then, step_context.scoped(), (*step_location, "then"), in_loop=in_loop)
            for branch_index, branch in enumerate(step.else_if):
                branch_context = step_context.scoped()
                branch_type = _infer_value(
                    branch.condition,
                    branch_context,
                    (*step_location, "else_if", branch_index, "condition"),
                )
                if not _is_boolean(branch_type):
                    context.issue(
                        IssueCode.INVALID_CONDITION_TYPE,
                        "else-if condition must be boolean",
                        (*step_location, "else_if", branch_index),
                    )
                _walk_block(
                    branch.body,
                    branch_context,
                    (*step_location, "else_if", branch_index, "body"),
                    in_loop=in_loop,
                )
            if step.else_body is not None:
                _walk_block(
                    step.else_body,
                    step_context.scoped(),
                    (*step_location, "else_body"),
                    in_loop=in_loop,
                )
            continue
        if isinstance(step, MatchStep):
            subject = _infer_value(step.subject, step_context, (*step_location, "subject"))
            for case_index, case in enumerate(step.cases):
                case_type = _infer_value(
                    case.value, step_context, (*step_location, "cases", case_index, "value")
                )
                if not _same_or_dynamic(subject, case_type):
                    context.issue(
                        IssueCode.INVALID_MATCH_CASE,
                        "match case value is incompatible with match subject",
                        (*step_location, "cases", case_index, "value"),
                    )
                _walk_block(
                    case.body,
                    step_context.scoped(),
                    (*step_location, "cases", case_index, "body"),
                    in_loop=in_loop,
                )
            if step.default is not None:
                _walk_block(
                    step.default,
                    step_context.scoped(),
                    (*step_location, "default"),
                    in_loop=in_loop,
                )
            continue
        if isinstance(step, ForeachStep):
            collection = _infer_value(step.collection, step_context, (*step_location, "collection"))
            if not _is_collection(collection):
                context.issue(
                    IssueCode.INVALID_LOOP_COLLECTION,
                    "foreach collection must be an array",
                    (*step_location, "collection"),
                )
            loop_context = step_context.scoped(
                loop_items={**step_context.loop_items, step.id: collection.items or ANY}
            )
            _walk_block(step.body, loop_context, (*step_location, "body"), in_loop=True)
            continue
        if isinstance(step, RepeatStep):
            _walk_block(step.body, step_context.scoped(), (*step_location, "body"), in_loop=True)
            continue
        if isinstance(step, ParallelStep):
            branch_ids = [branch.id for branch in step.branches]
            if len(branch_ids) != len(set(branch_ids)):
                context.issue(
                    IssueCode.INVALID_PARALLEL_BRANCH,
                    "parallel branch ids must be unique",
                    step_location,
                )
            for branch_index, branch in enumerate(step.branches):
                _walk_block(
                    branch.body,
                    step_context.scoped(),
                    (*step_location, "branches", branch_index, "body"),
                    in_loop=in_loop,
                )
            continue
        if isinstance(step, (BreakStep, ContinueStep)) and not in_loop:
            context.issue(
                IssueCode.INVALID_LOOP_CONTROL,
                f"'{step.kind}' is only valid inside foreach or repeat",
                step_location,
            )
    return visible


def validate_workflow(workflow: Workflow, registry: NodeRegistry) -> ValidationResult:
    """Validate contracts, values, references, and structured control flow.

    Validation is intentionally non-executing: it establishes that an IR
    document is meaningful for a conforming runtime without calling a node or
    interpreting application-specific configuration.
    """

    issues: list[ValidationIssue] = []
    definitions: dict[str, NodeDefinition] = {}
    node_ids = {node.id for node in workflow.nodes}
    for node_index, node in enumerate(workflow.nodes):
        try:
            definition = registry.resolve(node.type, node.type_version)
            definitions[node.id] = definition
            _validate_node_configuration(node_index, node.id, node.config, definition, issues)
        except UnknownNodeDefinitionError:
            issues.append(
                ValidationIssue(
                    code=IssueCode.UNKNOWN_NODE_DEFINITION,
                    message=(
                        f"node '{node.id}' requires unregistered contract "
                        f"'{node.type}' version '{node.type_version}'"
                    ),
                    location=("nodes", node_index),
                )
            )

    connections: dict[str, list[tuple[int, DataConnection]]] = defaultdict(list)
    bound_inputs: set[tuple[str, str]] = set()
    for index, connection in enumerate(workflow.connections):
        target = (connection.target.node_id, connection.target.port)
        if connection.target.node_id not in node_ids:
            issues.append(
                ValidationIssue(
                    code=IssueCode.UNKNOWN_NODE,
                    message=f"connection target node '{connection.target.node_id}' does not exist",
                    location=("connections", index, "target", "node_id"),
                )
            )
            continue
        if target in bound_inputs:
            issues.append(
                ValidationIssue(
                    code=IssueCode.DUPLICATE_INPUT_BINDING,
                    message=(
                        f"multiple connections bind input '{connection.target.port}' "
                        f"on node '{connection.target.node_id}'"
                    ),
                    location=("connections", index, "target"),
                )
            )
        bound_inputs.add(target)
        definition = definitions.get(connection.target.node_id)
        if definition is not None and connection.target.port not in definition.inputs:
            issues.append(
                ValidationIssue(
                    code=IssueCode.UNKNOWN_TARGET_PORT,
                    message=(
                        f"node '{connection.target.node_id}' has no input port "
                        f"'{connection.target.port}'"
                    ),
                    location=("connections", index, "target", "port"),
                )
            )
        connections[connection.target.node_id].append((index, connection))

    context = _Context(workflow, definitions, connections, issues)
    visible = _walk_block(workflow.body, context, ("body",), in_loop=False)
    context.visible_nodes = visible
    for name, value in workflow.outputs.items():
        _infer_value(value, context, ("outputs", name))

    for node in workflow.nodes:
        if node.id not in context.seen_node_steps:
            context.issue(
                IssueCode.UNUSED_NODE,
                f"node '{node.id}' is not placed in the workflow control flow",
                ("nodes", node.id),
            )
    return ValidationResult(issues=tuple(issues))
