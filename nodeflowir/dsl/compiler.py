"""Compilation from the temporary NodeFlow DSL syntax tree to canonical IR."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from nodeflowir.dsl import ast
from nodeflowir.dsl.errors import DSLCompileError, DSLValidationError, SourceLocation
from nodeflowir.dsl.parser import parse
from nodeflowir.ir import (
    AggregationExpression,
    AggregationOperator,
    ArrayValue,
    BackoffStrategy,
    BinaryExpression,
    BinaryOperator,
    BreakStep,
    CollectionExpression,
    CollectionOperator,
    CompositionExpression,
    CompositionOperator,
    ConditionalBranch,
    ConstantReference,
    ContinueStep,
    ConvergenceStrategy,
    DataConnection,
    ErrorCategory,
    ErrorFlow,
    FallbackExpression,
    FallbackOperator,
    FlowBlock,
    ForeachStep,
    IfStep,
    JoinExpression,
    LiteralValue,
    LogicalExpression,
    LogicalOperator,
    LoopItemReference,
    MatchCase,
    MatchStep,
    NodeInstance,
    NodeOutputReference,
    NodeStep,
    ObjectValue,
    ParallelBranch,
    ParallelStep,
    PortAddress,
    RepeatStep,
    RetryPolicy,
    SortDirection,
    TimeoutPolicy,
    TypeSpec,
    UnaryExpression,
    UnaryOperator,
    Value,
    ValueKind,
    Workflow,
    WorkflowConstant,
    WorkflowInput,
    WorkflowInputReference,
)
from nodeflowir.nodes import NodeDefinition, NodeRegistry, UnknownNodeDefinitionError
from nodeflowir.validation import validate_workflow

_TYPE_NAMES: dict[str, ValueKind] = {
    "any": ValueKind.ANY,
    "null": ValueKind.NULL,
    "string": ValueKind.STRING,
    "integer": ValueKind.INTEGER,
    "number": ValueKind.NUMBER,
    "boolean": ValueKind.BOOLEAN,
    "array": ValueKind.ARRAY,
    "object": ValueKind.OBJECT,
    "date": ValueKind.DATE,
    "datetime": ValueKind.DATETIME,
    "duration": ValueKind.DURATION,
    "status": ValueKind.STATUS,
}

_BINARY_OPERATORS: dict[str, BinaryOperator] = {
    "==": BinaryOperator.EQUAL,
    "!=": BinaryOperator.NOT_EQUAL,
    ">": BinaryOperator.GREATER_THAN,
    "<": BinaryOperator.LESS_THAN,
    ">=": BinaryOperator.GREATER_THAN_OR_EQUAL,
    "<=": BinaryOperator.LESS_THAN_OR_EQUAL,
    "in": BinaryOperator.IN,
    "not in": BinaryOperator.NOT_IN,
    "+": BinaryOperator.ADD,
    "-": BinaryOperator.SUBTRACT,
    "*": BinaryOperator.MULTIPLY,
    "/": BinaryOperator.DIVIDE,
    "%": BinaryOperator.MODULO,
}

_BINARY_FUNCTIONS: dict[str, BinaryOperator] = {
    "contains": BinaryOperator.CONTAINS,
    "starts_with": BinaryOperator.STARTS_WITH,
    "ends_with": BinaryOperator.ENDS_WITH,
    "matches": BinaryOperator.MATCHES,
}

_UNARY_FUNCTIONS: dict[str, UnaryOperator] = {
    "exists": UnaryOperator.EXISTS,
    "missing": UnaryOperator.MISSING,
    "lower": UnaryOperator.LOWER,
    "upper": UnaryOperator.UPPER,
    "trim": UnaryOperator.TRIM,
    "length": UnaryOperator.LENGTH,
    "empty": UnaryOperator.EMPTY,
    "not_empty": UnaryOperator.NOT_EMPTY,
    "first": UnaryOperator.FIRST,
    "last": UnaryOperator.LAST,
}


@dataclass
class _Environment:
    values: dict[str, Value] = field(default_factory=dict)
    nodes: dict[str, str] = field(default_factory=dict)
    loops: dict[str, str] = field(default_factory=dict)
    constants: set[str] = field(default_factory=set)

    def child(self) -> _Environment:
        return _Environment(
            values=dict(self.values),
            nodes=dict(self.nodes),
            loops=dict(self.loops),
            constants=set(self.constants),
        )


class Compiler:
    """Compile valid DSL syntax using application-provided node contracts."""

    def __init__(self, registry: NodeRegistry) -> None:
        self.registry = registry
        self.nodes: list[NodeInstance] = []
        self.connections: list[DataConnection] = []
        self.constants: dict[str, WorkflowConstant] = {}
        self._node_ids: set[str] = set()
        self._counter = 0
        self._workflow_inputs: set[str] = set()
        self._workflow_outputs: dict[str, Value] = {}

    def compile(self, document: ast.FileSyntax) -> Workflow:
        if document.language_version != "1.0":
            self._error(
                document.location,
                f"unsupported NodeFlow DSL version '{document.language_version}'; expected '1.0'",
            )
        workflow = document.workflow
        parameter_names = [parameter.name for parameter in workflow.parameters]
        if len(parameter_names) != len(set(parameter_names)):
            duplicate = next(name for name in parameter_names if parameter_names.count(name) > 1)
            self._error(
                workflow.location, f"workflow input '{duplicate}' is declared more than once"
            )
        self._workflow_inputs = {parameter.name for parameter in workflow.parameters}
        inputs = {
            parameter.name: WorkflowInput(
                type=self._type_spec(parameter.type_name, parameter.location)
            )
            for parameter in workflow.parameters
        }
        environment = _Environment()
        try:
            body = self._compile_block(workflow.body, environment, top_level=True)
            return Workflow(
                schema_version=document.language_version,
                workflow_version=workflow.version,
                id=workflow.name,
                name=workflow.display_name or workflow.name,
                inputs=inputs,
                constants=self.constants,
                nodes=self.nodes,
                connections=self.connections,
                body=body,
                outputs=self._workflow_outputs,
            )
        except ValidationError as error:
            self._error(workflow.location, self._pydantic_message(error))

    def _compile_block(
        self,
        block: ast.BlockSyntax,
        environment: _Environment,
        *,
        top_level: bool = False,
    ) -> FlowBlock:
        steps = []
        for statement in block.statements:
            if isinstance(statement, ast.AssignmentSyntax):
                if statement.name in environment.values or statement.name in environment.nodes:
                    self._error(
                        statement.location, f"'{statement.name}' is already declared in this scope"
                    )
                environment.values[statement.name] = self._compile_expression(
                    statement.value, environment
                )
                continue
            if isinstance(statement, ast.ConstantSyntax):
                if not top_level:
                    self._error(statement.location, "constants are only valid at workflow scope")
                if statement.name in self.constants:
                    self._error(
                        statement.location, f"constant '{statement.name}' is already declared"
                    )
                value = self._static_value(statement.value, environment)
                value_type = self._type_spec(statement.type_name, statement.location)
                self.constants[statement.name] = WorkflowConstant(
                    type=value_type,
                    value=LiteralValue(value=value),
                )
                environment.constants.add(statement.name)
                continue
            if isinstance(statement, ast.RunSyntax):
                step, alias = self._compile_run(statement, environment)
                steps.append(step)
                if alias is not None:
                    environment.nodes[alias] = step.node_id
                continue
            if isinstance(statement, ast.IfSyntax):
                condition = self._compile_expression(statement.condition, environment)
                then = self._compile_block(statement.then, environment.child())
                else_if = [
                    ConditionalBranch(
                        condition=self._compile_expression(condition, environment),
                        body=self._compile_block(branch, environment.child()),
                    )
                    for condition, branch in statement.else_if
                ]
                else_body = (
                    self._compile_block(statement.else_body, environment.child())
                    if statement.else_body is not None
                    else None
                )
                steps.append(
                    IfStep(
                        condition=condition,
                        then=then,
                        else_if=else_if,
                        else_body=else_body,
                    )
                )
                continue
            if isinstance(statement, ast.MatchSyntax):
                steps.append(
                    MatchStep(
                        subject=self._compile_expression(statement.subject, environment),
                        cases=[
                            MatchCase(
                                value=self._compile_expression(value, environment),
                                body=self._compile_block(case, environment.child()),
                            )
                            for value, case in statement.cases
                        ],
                        default=(
                            self._compile_block(statement.default, environment.child())
                            if statement.default is not None
                            else None
                        ),
                    )
                )
                continue
            if isinstance(statement, ast.ForeachSyntax):
                loop_environment = environment.child()
                loop_environment.loops[statement.item_name] = statement.item_name
                steps.append(
                    ForeachStep(
                        id=statement.item_name,
                        collection=self._compile_expression(statement.collection, environment),
                        body=self._compile_block(statement.body, loop_environment),
                    )
                )
                continue
            if isinstance(statement, ast.RepeatSyntax):
                steps.append(
                    RepeatStep(
                        id=self._generated_id("repeat"),
                        times=statement.times,
                        body=self._compile_block(statement.body, environment.child()),
                    )
                )
                continue
            if isinstance(statement, ast.ParallelSyntax):
                steps.append(self._compile_parallel(statement, environment))
                continue
            if isinstance(statement, ast.BreakSyntax):
                steps.append(BreakStep())
                continue
            if isinstance(statement, ast.ContinueSyntax):
                steps.append(ContinueStep())
                continue
            if isinstance(statement, ast.OutputSyntax):
                if not top_level:
                    self._error(statement.location, "output is only valid at workflow scope")
                if self._workflow_outputs:
                    self._error(statement.location, "a workflow can contain only one output block")
                outputs: dict[str, Value] = {}
                for assignment in statement.assignments:
                    if assignment.name in outputs:
                        self._error(
                            assignment.location,
                            f"workflow output '{assignment.name}' is declared more than once",
                        )
                    outputs[assignment.name] = self._compile_expression(
                        assignment.value, environment
                    )
                self._workflow_outputs = outputs
                continue
            self._error(statement.location, "unsupported DSL statement")
        if not steps:
            self._error(block.location, "a control-flow block requires at least one flow statement")
        return FlowBlock(steps=steps)

    def _compile_parallel(
        self, statement: ast.ParallelSyntax, environment: _Environment
    ) -> ParallelStep:
        branches: list[ParallelBranch] = []
        for index, branch_statement in enumerate(statement.body.statements, start=1):
            branch_environment = environment.child()
            branch_block = ast.BlockSyntax(
                location=branch_statement.location,
                statements=(branch_statement,),
            )
            body = self._compile_block(branch_block, branch_environment)
            branch_id = (
                branch_statement.alias
                if isinstance(branch_statement, ast.RunSyntax)
                and branch_statement.alias is not None
                else self._generated_id(f"branch_{index}")
            )
            branches.append(ParallelBranch(id=branch_id, body=body))
        if len(branches) < 2:
            self._error(statement.location, "parallel requires at least two branches")
        return ParallelStep(
            id=self._generated_id("parallel"),
            convergence=ConvergenceStrategy(statement.convergence),
            branches=branches,
        )

    def _compile_run(
        self, statement: ast.RunSyntax, environment: _Environment
    ) -> tuple[NodeStep, str | None]:
        node_id = statement.alias or self._generated_id("node")
        if node_id in self._node_ids:
            self._error(statement.location, f"node id '{node_id}' is already used")
        definition = self._definition(statement)
        config_fields = {field.name: field for field in definition.config}
        input_names = set(definition.inputs)
        config: dict[str, Any] = {}
        bound_inputs: set[str] = set()
        for assignment in statement.assignments:
            is_config = assignment.name in config_fields
            is_input = assignment.name in input_names
            if is_config and is_input:
                self._error(
                    assignment.location,
                    (
                        f"'{assignment.name}' is both a configuration field and input "
                        f"on '{definition.type}'"
                    ),
                )
            if is_config:
                if assignment.name in config:
                    self._error(assignment.location, f"duplicate configuration '{assignment.name}'")
                config[assignment.name] = self._static_value(assignment.value, environment)
            elif is_input:
                if assignment.name in bound_inputs:
                    self._error(assignment.location, f"duplicate input '{assignment.name}'")
                bound_inputs.add(assignment.name)
                self.connections.append(
                    DataConnection(
                        target=PortAddress(node_id=node_id, port=assignment.name),
                        value=self._compile_expression(assignment.value, environment),
                    )
                )
            else:
                self._error(
                    assignment.location,
                    (
                        f"'{assignment.name}' is not a configuration field or input "
                        f"on '{definition.type}'"
                    ),
                )
        retry = None
        if statement.retry is not None:
            if statement.retry.backoff not in {strategy.value for strategy in BackoffStrategy}:
                self._error(
                    statement.retry.location,
                    "retry backoff must be fixed, linear, or exponential",
                )
            retry = RetryPolicy(
                max_attempts=statement.retry.attempts,
                delay_seconds=statement.retry.delay_seconds,
                backoff=BackoffStrategy(statement.retry.backoff),
                max_delay_seconds=statement.retry.max_delay_seconds,
            )
        timeout = (
            TimeoutPolicy(timeout_seconds=statement.timeout_seconds)
            if statement.timeout_seconds is not None
            else None
        )
        self.nodes.append(
            NodeInstance(
                id=node_id,
                type=definition.type,
                type_version=definition.version,
                config=config,
                retry=retry,
                timeout=timeout,
            )
        )
        self._node_ids.add(node_id)
        on_error = None
        if statement.on_error is not None:
            if len(statement.on_error.categories) != len(set(statement.on_error.categories)):
                self._error(statement.on_error.location, "error categories must be unique")
            categories = tuple(
                ErrorCategory(category) for category in statement.on_error.categories
            )
            on_error = ErrorFlow(
                categories=categories,
                body=self._compile_block(statement.on_error.body, environment.child()),
            )
        return NodeStep(node_id=node_id, on_error=on_error), statement.alias

    def _definition(self, statement: ast.RunSyntax) -> NodeDefinition:
        try:
            return (
                self.registry.resolve(statement.type_id, statement.type_version)
                if statement.type_version is not None
                else self.registry.get(statement.type_id)
            )
        except UnknownNodeDefinitionError as error:
            version = f"@{statement.type_version}" if statement.type_version else ""
            self._error(
                statement.location,
                f"unknown registered node definition '{statement.type_id}{version}'",
                error,
            )

    def _compile_expression(
        self,
        expression: ast.ExpressionSyntax,
        environment: _Environment,
        *,
        implicit_item_scope: str | None = None,
    ) -> Value:
        if isinstance(expression, ast.LiteralSyntax):
            if expression.duration_seconds is not None:
                return LiteralValue(
                    value=expression.duration_seconds,
                    type=TypeSpec(kind=ValueKind.DURATION),
                )
            return LiteralValue(value=expression.value)
        if isinstance(expression, ast.ListSyntax):
            return ArrayValue(
                items=[
                    self._compile_expression(
                        item, environment, implicit_item_scope=implicit_item_scope
                    )
                    for item in expression.items
                ]
            )
        if isinstance(expression, ast.ObjectSyntax):
            field_names = [name for name, _ in expression.fields]
            if len(field_names) != len(set(field_names)):
                duplicate = next(name for name in field_names if field_names.count(name) > 1)
                self._error(
                    expression.location, f"object field '{duplicate}' is declared more than once"
                )
            return ObjectValue(
                fields={
                    name: self._compile_expression(
                        value, environment, implicit_item_scope=implicit_item_scope
                    )
                    for name, value in expression.fields
                }
            )
        if isinstance(expression, ast.ReferenceSyntax):
            return self._compile_reference(expression, environment, implicit_item_scope)
        if isinstance(expression, ast.UnarySyntax):
            operator = {
                "not": UnaryOperator.NOT,
                "is_null": UnaryOperator.IS_NULL,
                "is_not_null": UnaryOperator.IS_NOT_NULL,
            }.get(expression.operator)
            if operator is None:
                self._error(
                    expression.location, f"unsupported unary operator '{expression.operator}'"
                )
            return UnaryExpression(
                operator=operator,
                operand=self._compile_expression(
                    expression.operand, environment, implicit_item_scope=implicit_item_scope
                ),
            )
        if isinstance(expression, ast.BinarySyntax):
            if expression.operator in {"and", "or"}:
                operator = (
                    LogicalOperator.AND if expression.operator == "and" else LogicalOperator.OR
                )
                left = self._compile_expression(
                    expression.left, environment, implicit_item_scope=implicit_item_scope
                )
                right = self._compile_expression(
                    expression.right, environment, implicit_item_scope=implicit_item_scope
                )
                operands = [left, right]
                if isinstance(left, LogicalExpression) and left.operator is operator:
                    operands = [*left.operands, right]
                return LogicalExpression(operator=operator, operands=operands)
            operator = _BINARY_OPERATORS.get(expression.operator)
            if operator is None:
                self._error(
                    expression.location, f"unsupported binary operator '{expression.operator}'"
                )
            return BinaryExpression(
                operator=operator,
                left=self._compile_expression(
                    expression.left, environment, implicit_item_scope=implicit_item_scope
                ),
                right=self._compile_expression(
                    expression.right, environment, implicit_item_scope=implicit_item_scope
                ),
            )
        if isinstance(expression, ast.CallSyntax):
            return self._compile_call(expression, environment, implicit_item_scope)
        self._error(expression.location, "unsupported expression")

    def _compile_reference(
        self,
        reference: ast.ReferenceSyntax,
        environment: _Environment,
        implicit_item_scope: str | None,
    ) -> Value:
        parts = reference.text.split(".")
        root, path = parts[0], tuple(parts[1:])
        if root == "input":
            if not path:
                self._error(reference.location, "input references require a declared input name")
            if path[0] not in self._workflow_inputs:
                self._error(reference.location, f"unknown workflow input '{path[0]}'")
            return WorkflowInputReference(name=path[0], path=path[1:])
        if root == "const":
            if not path:
                self._error(reference.location, "constant references require a declared name")
            if path[0] not in environment.constants:
                self._error(reference.location, f"unknown constant '{path[0]}'")
            return ConstantReference(name=path[0], path=path[1:])
        if root in environment.nodes:
            if not path or path[0] != "output":
                self._error(reference.location, "node references must use '.output' explicitly")
            if len(path) == 1:
                return NodeOutputReference(node_id=environment.nodes[root], output="output")
            return NodeOutputReference(
                node_id=environment.nodes[root], output=path[1], path=path[2:]
            )
        if root in environment.loops:
            return LoopItemReference(loop_id=environment.loops[root], path=path)
        if root in environment.values:
            if path:
                self._error(
                    reference.location,
                    "a deterministic assignment cannot be selected by path; "
                    "select before assigning",
                )
            return environment.values[root]
        if implicit_item_scope is not None:
            return LoopItemReference(loop_id=implicit_item_scope, path=parts)
        self._error(reference.location, f"unknown reference '{reference.text}'")

    def _compile_call(
        self,
        call: ast.CallSyntax,
        environment: _Environment,
        implicit_item_scope: str | None,
    ) -> Value:
        name = call.name
        if name in _UNARY_FUNCTIONS:
            self._arity(call, 1)
            return UnaryExpression(
                operator=_UNARY_FUNCTIONS[name],
                operand=self._compile_expression(
                    call.arguments[0], environment, implicit_item_scope=implicit_item_scope
                ),
            )
        if name in _BINARY_FUNCTIONS:
            self._arity(call, 2)
            return BinaryExpression(
                operator=_BINARY_FUNCTIONS[name],
                left=self._compile_expression(
                    call.arguments[0], environment, implicit_item_scope=implicit_item_scope
                ),
                right=self._compile_expression(
                    call.arguments[1], environment, implicit_item_scope=implicit_item_scope
                ),
            )
        if name in {"any", "all", "none", "filter"}:
            self._arity(call, 2)
            operator = CollectionOperator(name)
            scope = self._generated_id("item")
            return CollectionExpression(
                operator=operator,
                collection=self._compile_expression(call.arguments[0], environment),
                item_scope=scope,
                predicate=self._compile_expression(
                    call.arguments[1], environment, implicit_item_scope=scope
                ),
            )
        if name == "count":
            if len(call.arguments) not in {1, 2}:
                self._arity(call, 1, 2)
            scope = self._generated_id("item") if len(call.arguments) == 2 else None
            return AggregationExpression(
                operator=AggregationOperator.COUNT,
                collection=self._compile_expression(call.arguments[0], environment),
                item_scope=scope,
                predicate=(
                    self._compile_expression(
                        call.arguments[1], environment, implicit_item_scope=scope
                    )
                    if len(call.arguments) == 2 and scope is not None
                    else None
                ),
            )
        if name in {"sum", "avg", "min", "max"}:
            if len(call.arguments) not in {1, 2}:
                self._arity(call, 1, 2)
            collection = self._compile_expression(call.arguments[0], environment)
            if len(call.arguments) == 2:
                scope = self._generated_id("item")
                collection = CollectionExpression(
                    operator=CollectionOperator.MAP,
                    collection=collection,
                    item_scope=scope,
                    mapper=self._compile_expression(
                        call.arguments[1], environment, implicit_item_scope=scope
                    ),
                )
            return AggregationExpression(operator=AggregationOperator(name), collection=collection)
        if name == "distinct":
            self._arity(call, 1)
            return AggregationExpression(
                operator=AggregationOperator.DISTINCT,
                collection=self._compile_expression(call.arguments[0], environment),
            )
        if name == "unique":
            self._arity(call, 1)
            return CollectionExpression(
                operator=CollectionOperator.UNIQUE,
                collection=self._compile_expression(call.arguments[0], environment),
            )
        if name == "map":
            self._arity(call, 2)
            scope = self._generated_id("item")
            return CollectionExpression(
                operator=CollectionOperator.MAP,
                collection=self._compile_expression(call.arguments[0], environment),
                item_scope=scope,
                mapper=self._compile_expression(
                    call.arguments[1], environment, implicit_item_scope=scope
                ),
            )
        if name in {"select", "pick", "omit"}:
            if len(call.arguments) < 2:
                self._arity(call, 2)
            fields = tuple(self._field_name(argument) for argument in call.arguments[1:])
            return CollectionExpression(
                operator=CollectionOperator(name),
                collection=self._compile_expression(call.arguments[0], environment),
                fields=fields,
            )
        if name == "rename":
            if len(call.arguments) < 3 or len(call.arguments) % 2 == 0:
                self._error(
                    call.location, "rename requires a collection and old/new field-name pairs"
                )
            rename = {
                self._field_name(call.arguments[index]): self._field_name(call.arguments[index + 1])
                for index in range(1, len(call.arguments), 2)
            }
            return CollectionExpression(
                operator=CollectionOperator.RENAME,
                collection=self._compile_expression(call.arguments[0], environment),
                rename=rename,
            )
        if name in {"flatten"}:
            self._arity(call, 1)
            return CollectionExpression(
                operator=CollectionOperator.FLATTEN,
                collection=self._compile_expression(call.arguments[0], environment),
            )
        if name == "zip":
            self._arity(call, 2)
            return CollectionExpression(
                operator=CollectionOperator.ZIP,
                collection=self._compile_expression(call.arguments[0], environment),
                other=self._compile_expression(call.arguments[1], environment),
            )
        if name in {"sort_by", "group_by"}:
            if name == "sort_by" and len(call.arguments) not in {2, 3}:
                self._arity(call, 2, 3)
            if name == "group_by" and len(call.arguments) != 2:
                self._arity(call, 2)
            direction = SortDirection.ASCENDING
            if len(call.arguments) == 3:
                direction_name = self._direction(call.arguments[2])
                direction = (
                    SortDirection.DESCENDING
                    if direction_name == "desc"
                    else SortDirection.ASCENDING
                )
            scope = self._generated_id("item")
            return CollectionExpression(
                operator=CollectionOperator(name),
                collection=self._compile_expression(call.arguments[0], environment),
                item_scope=scope,
                mapper=self._compile_expression(
                    call.arguments[1], environment, implicit_item_scope=scope
                ),
                direction=direction,
            )
        if name in {"merge", "concat", "append", "prepend"}:
            minimum = 2
            if len(call.arguments) < minimum or (
                name in {"append", "prepend"} and len(call.arguments) != 2
            ):
                self._error(
                    call.location,
                    f"{name} requires "
                    f"{'exactly' if name in {'append', 'prepend'} else 'at least'} two arguments",
                )
            return CompositionExpression(
                operator=CompositionOperator(name),
                values=[
                    self._compile_expression(argument, environment) for argument in call.arguments
                ],
            )
        if name in {"coalesce", "default"}:
            if name == "default":
                self._arity(call, 2)
            elif not call.arguments:
                self._error(call.location, "coalesce requires at least one argument")
            return FallbackExpression(
                operator=FallbackOperator(name),
                values=[
                    self._compile_expression(argument, environment) for argument in call.arguments
                ],
            )
        if name == "join":
            self._arity(call, 3)
            left_scope = self._generated_id("left")
            right_scope = self._generated_id("right")
            join_environment = environment.child()
            join_environment.loops.update({"left": left_scope, "right": right_scope})
            return JoinExpression(
                left=self._compile_expression(call.arguments[0], environment),
                right=self._compile_expression(call.arguments[1], environment),
                left_scope=left_scope,
                right_scope=right_scope,
                predicate=self._compile_expression(call.arguments[2], join_environment),
            )
        self._error(call.location, f"unsupported deterministic operation '{name}'")

    def _static_value(self, expression: ast.ExpressionSyntax, environment: _Environment) -> Any:
        value = self._compile_expression(expression, environment)
        if isinstance(value, LiteralValue):
            return value.value
        if isinstance(value, ArrayValue):
            return [self._static_ir_value(item, expression.location) for item in value.items]
        if isinstance(value, ObjectValue):
            return {
                name: self._static_ir_value(item, expression.location)
                for name, item in value.fields.items()
            }
        self._error(
            expression.location,
            "configuration and constants must be JSON literals, lists, or objects",
        )

    def _static_ir_value(self, value: Value, location: SourceLocation) -> Any:
        if isinstance(value, LiteralValue):
            return value.value
        if isinstance(value, ArrayValue):
            return [self._static_ir_value(item, location) for item in value.items]
        if isinstance(value, ObjectValue):
            return {
                name: self._static_ir_value(item, location) for name, item in value.fields.items()
            }
        self._error(
            location, "configuration and constants must be JSON literals, lists, or objects"
        )

    def _type_spec(self, type_name: str, location: SourceLocation) -> TypeSpec:
        kind = _TYPE_NAMES.get(type_name.lower())
        if kind is None:
            self._error(location, f"unknown portable type '{type_name}'")
        return TypeSpec(kind=kind)

    def _field_name(self, expression: ast.ExpressionSyntax) -> str:
        if isinstance(expression, ast.ReferenceSyntax) and "." not in expression.text:
            return expression.text
        if isinstance(expression, ast.LiteralSyntax) and isinstance(expression.value, str):
            return expression.value
        self._error(expression.location, "expected a simple or quoted field name")

    def _direction(self, expression: ast.ExpressionSyntax) -> str:
        if isinstance(expression, ast.ReferenceSyntax) and expression.text in {"asc", "desc"}:
            return expression.text
        self._error(expression.location, "sort direction must be 'asc' or 'desc'")

    def _generated_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    def _arity(self, call: ast.CallSyntax, minimum: int, maximum: int | None = None) -> None:
        maximum = minimum if maximum is None else maximum
        if minimum <= len(call.arguments) <= maximum:
            return
        expected = str(minimum) if minimum == maximum else f"{minimum} to {maximum}"
        self._error(call.location, f"{call.name} expects {expected} argument(s)")

    def _error(
        self,
        location: SourceLocation,
        message: str,
        cause: Exception | None = None,
    ) -> None:
        error = DSLCompileError(message, location)
        if cause is not None:
            raise error from cause
        raise error

    @staticmethod
    def _pydantic_message(error: ValidationError) -> str:
        first = error.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first["loc"])
        return f"invalid IR model at {location}: {first['msg']}"


def compile_syntax(
    document: ast.FileSyntax,
    registry: NodeRegistry,
    *,
    validate: bool = True,
) -> Workflow:
    """Compile parsed DSL syntax, optionally running existing IR validation."""

    workflow = Compiler(registry).compile(document)
    if validate:
        result = validate_workflow(workflow, registry)
        if not result.is_valid:
            first = result.issues[0]
            location = ".".join(str(part) for part in first.location) or "workflow"
            raise DSLValidationError(f"IR validation failed at {location}: {first.message}", result)
    return workflow


def compile_dsl(source: str, registry: NodeRegistry, *, validate: bool = True) -> Workflow:
    """Parse and compile DSL text into the canonical :class:`Workflow` model."""

    return compile_syntax(parse(source), registry, validate=validate)


compile = compile_dsl
