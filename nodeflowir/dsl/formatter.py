"""Deterministic formatting of the supported canonical IR subset as DSL."""

from __future__ import annotations

import json
import re
from collections import defaultdict

from nodeflowir.dsl.errors import DSLFormatError
from nodeflowir.ir import (
    AggregationExpression,
    ArrayValue,
    BinaryExpression,
    BreakStep,
    CollectionExpression,
    CollectionOperator,
    CompositionExpression,
    ConstantReference,
    ContinueStep,
    ConversionExpression,
    FallbackExpression,
    FlowBlock,
    ForeachStep,
    IfStep,
    JoinExpression,
    LiteralValue,
    LogicalExpression,
    LoopItemReference,
    MatchStep,
    NodeOutputReference,
    NodeStep,
    ObjectValue,
    ParallelStep,
    RepeatStep,
    UnaryExpression,
    Value,
    ValueKind,
    Workflow,
    WorkflowInputReference,
)

_TYPE_NAMES = {
    ValueKind.ANY: "Any",
    ValueKind.NULL: "Null",
    ValueKind.STRING: "String",
    ValueKind.INTEGER: "Integer",
    ValueKind.NUMBER: "Number",
    ValueKind.BOOLEAN: "Boolean",
    ValueKind.ARRAY: "Array",
    ValueKind.OBJECT: "Object",
    ValueKind.DATE: "Date",
    ValueKind.DATETIME: "DateTime",
    ValueKind.DURATION: "Duration",
    ValueKind.STATUS: "Status",
}
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def format_workflow(workflow: Workflow) -> str:
    """Format a workflow using stable, braces-based NodeFlow DSL syntax.

    Formatting only handles DSL-expressible IR.  It raises :class:`DSLFormatError`
    instead of silently changing unsupported semantics.
    """

    if workflow.schema_version != "1.0":
        raise DSLFormatError(f"unsupported workflow schema '{workflow.schema_version}'")
    for workflow_input in workflow.inputs.values():
        if workflow_input.default is not None:
            raise DSLFormatError("workflow input defaults are not representable in DSL 1.0")
    formatter = _Formatter(workflow)
    return formatter.format()


class _Formatter:
    def __init__(self, workflow: Workflow) -> None:
        self.workflow = workflow
        self.instances = {node.id: node for node in workflow.nodes}
        self.connections: dict[str, list] = defaultdict(list)
        for connection in workflow.connections:
            self.connections[connection.target.node_id].append(connection)

    def format(self) -> str:
        parameters = ", ".join(
            f"{name}: {self._format_type(value.type)}"
            for name, value in self.workflow.inputs.items()
        )
        workflow_name = self.workflow.id
        named = (
            ""
            if self.workflow.name == workflow_name
            else f" named {json.dumps(self.workflow.name, ensure_ascii=False)}"
        )
        parameter_text = f" ({parameters})" if parameters else ""
        header = (
            f"workflow {workflow_name}{named} version {self.workflow.workflow_version}"
            f"{parameter_text} {{"
        )
        lines = ["nodeflow 1.0", "", header]
        for name, constant in self.workflow.constants.items():
            lines.append(
                f"    const {name}: {self._format_type(constant.type)} = "
                f"{self._format_value(constant.value)}"
            )
        if self.workflow.constants:
            lines.append("")
        lines.extend(self._format_block(self.workflow.body, 1))
        if self.workflow.outputs:
            lines.append("")
            lines.append("    output {")
            for name, value in self.workflow.outputs.items():
                lines.append(f"        {name} = {self._format_value(value)}")
            lines.append("    }")
        lines.append("}")
        return "\n".join(lines) + "\n"

    def _format_block(self, block: FlowBlock, depth: int) -> list[str]:
        lines: list[str] = []
        for step in block.steps:
            lines.extend(self._format_step(step, depth))
        return lines

    def _format_step(self, step, depth: int) -> list[str]:
        indent = "    " * depth
        if isinstance(step, NodeStep):
            return self._format_node(step, depth)
        if isinstance(step, IfStep):
            lines = [f"{indent}if {self._format_value(step.condition)} {{"]
            lines.extend(self._format_block(step.then, depth + 1))
            lines.append(f"{indent}}}")
            for branch in step.else_if:
                lines[-1] += f" else if {self._format_value(branch.condition)} {{"
                lines.extend(self._format_block(branch.body, depth + 1))
                lines.append(f"{indent}}}")
            if step.else_body is not None:
                lines[-1] += " else {"
                lines.extend(self._format_block(step.else_body, depth + 1))
                lines.append(f"{indent}}}")
            return lines
        if isinstance(step, MatchStep):
            lines = [f"{indent}match {self._format_value(step.subject)} {{"]
            for case in step.cases:
                lines.append(f"{indent}    case {self._format_value(case.value)} {{")
                lines.extend(self._format_block(case.body, depth + 2))
                lines.append(f"{indent}    }}")
            if step.default is not None:
                lines.append(f"{indent}    default {{")
                lines.extend(self._format_block(step.default, depth + 2))
                lines.append(f"{indent}    }}")
            lines.append(f"{indent}}}")
            return lines
        if isinstance(step, ForeachStep):
            lines = [f"{indent}foreach {step.id} in {self._format_value(step.collection)} {{"]
            lines.extend(self._format_block(step.body, depth + 1))
            lines.append(f"{indent}}}")
            return lines
        if isinstance(step, RepeatStep):
            lines = [f"{indent}repeat {step.times} {{"]
            lines.extend(self._format_block(step.body, depth + 1))
            lines.append(f"{indent}}}")
            return lines
        if isinstance(step, ParallelStep):
            convergence = "" if step.convergence.value == "all" else " any"
            lines = [f"{indent}parallel{convergence} {{"]
            for branch in step.branches:
                lines.extend(self._format_block(branch.body, depth + 1))
            lines.append(f"{indent}}}")
            return lines
        if isinstance(step, BreakStep):
            return [f"{indent}break"]
        if isinstance(step, ContinueStep):
            return [f"{indent}continue"]
        raise DSLFormatError(f"unsupported flow step '{type(step).__name__}'")

    def _format_node(self, step: NodeStep, depth: int) -> list[str]:
        instance = self.instances.get(step.node_id)
        if instance is None:
            raise DSLFormatError(f"node step references missing node instance '{step.node_id}'")
        indent = "    " * depth
        lines = [f"{indent}{instance.id} = run {instance.type}@{instance.type_version}"]
        assignments = [
            (name, self._format_json(value)) for name, value in instance.config.items()
        ] + [
            (connection.target.port, self._format_value(connection.value))
            for connection in self.connections[instance.id]
        ]
        if assignments:
            lines[-1] += " with {"
            for name, value in assignments:
                lines.append(f"{indent}    {name} = {value}")
            lines.append(f"{indent}}}")
        if instance.retry is not None:
            retry = instance.retry
            if (
                retry.delay_seconds == 0
                and retry.backoff.value == "fixed"
                and retry.max_delay_seconds is None
            ):
                lines.append(f"{indent}retry {retry.max_attempts}")
            else:
                lines.append(f"{indent}retry {{")
                lines.append(f"{indent}    attempts = {retry.max_attempts}")
                lines.append(f"{indent}    delay = {self._format_duration(retry.delay_seconds)}")
                lines.append(f"{indent}    backoff = {retry.backoff.value}")
                if retry.max_delay_seconds is not None:
                    lines.append(
                        f"{indent}    max_delay = {self._format_duration(retry.max_delay_seconds)}"
                    )
                lines.append(f"{indent}}}")
        if instance.timeout is not None:
            lines.append(
                f"{indent}timeout {self._format_duration(instance.timeout.timeout_seconds)}"
            )
        if step.on_error is not None:
            categories = " ".join(category.value for category in step.on_error.categories)
            suffix = f" {categories}" if categories else ""
            lines.append(f"{indent}on error{suffix} {{")
            lines.extend(self._format_block(step.on_error.body, depth + 1))
            lines.append(f"{indent}}}")
        return lines

    def _format_value(
        self,
        value: Value,
        *,
        implicit_item_scope: str | None = None,
        scope_names: dict[str, str] | None = None,
    ) -> str:
        scope_names = scope_names or {}
        if isinstance(value, LiteralValue):
            if value.type is not None and value.type.kind is ValueKind.DURATION:
                return self._format_duration(value.value)
            if value.type is not None:
                raise DSLFormatError(
                    f"typed literal '{value.type.kind}' is not representable in DSL 1.0"
                )
            return self._format_json(value.value)
        if isinstance(value, WorkflowInputReference):
            return self._format_path(("input", value.name, *value.path))
        if isinstance(value, ConstantReference):
            return self._format_path(("const", value.name, *value.path))
        if isinstance(value, NodeOutputReference):
            if value.output == "output" and not value.path:
                return self._format_path((value.node_id, "output"))
            return self._format_path((value.node_id, "output", value.output, *value.path))
        if isinstance(value, LoopItemReference):
            if value.loop_id == implicit_item_scope and value.path:
                return self._format_path(value.path)
            root = scope_names.get(value.loop_id, value.loop_id)
            return self._format_path((root, *value.path))
        if isinstance(value, ArrayValue):
            return (
                "["
                + ", ".join(
                    self._format_value(
                        item, implicit_item_scope=implicit_item_scope, scope_names=scope_names
                    )
                    for item in value.items
                )
                + "]"
            )
        if isinstance(value, ObjectValue):
            parts = []
            for name, item in value.fields.items():
                rendered = self._format_value(
                    item,
                    implicit_item_scope=implicit_item_scope,
                    scope_names=scope_names,
                )
                parts.append(f"{self._format_field(name)} = {rendered}")
            return "object { " + ", ".join(parts) + " }"
        if isinstance(value, UnaryExpression):
            operand = self._format_value(
                value.operand, implicit_item_scope=implicit_item_scope, scope_names=scope_names
            )
            if value.operator.value == "not":
                return f"not ({operand})"
            if value.operator.value == "is_null":
                return f"({operand} is null)"
            if value.operator.value == "is_not_null":
                return f"({operand} is not null)"
            return f"{value.operator.value}({operand})"
        if isinstance(value, BinaryExpression):
            operator = {
                "eq": "==",
                "ne": "!=",
                "gt": ">",
                "lt": "<",
                "gte": ">=",
                "lte": "<=",
                "add": "+",
                "subtract": "-",
                "multiply": "*",
                "divide": "/",
                "modulo": "%",
                "in": "in",
                "not_in": "not in",
            }.get(value.operator.value)
            left = self._format_value(
                value.left, implicit_item_scope=implicit_item_scope, scope_names=scope_names
            )
            right = self._format_value(
                value.right, implicit_item_scope=implicit_item_scope, scope_names=scope_names
            )
            if operator is not None:
                return f"({left} {operator} {right})"
            if value.operator.value in {"contains", "starts_with", "ends_with", "matches"}:
                return f"{value.operator.value}({left}, {right})"
            raise DSLFormatError(
                f"binary operator '{value.operator.value}' is not representable in DSL 1.0"
            )
        if isinstance(value, LogicalExpression):
            return (
                "("
                + f" {value.operator.value} ".join(
                    self._format_value(
                        item, implicit_item_scope=implicit_item_scope, scope_names=scope_names
                    )
                    for item in value.operands
                )
                + ")"
            )
        if isinstance(value, CollectionExpression):
            return self._format_collection(value, scope_names)
        if isinstance(value, AggregationExpression):
            arguments = [self._format_value(value.collection, scope_names=scope_names)]
            if value.predicate is not None:
                arguments.append(
                    self._format_value(
                        value.predicate,
                        implicit_item_scope=value.item_scope,
                        scope_names=scope_names,
                    )
                )
            return f"{value.operator.value}(" + ", ".join(arguments) + ")"
        if isinstance(value, CompositionExpression):
            return (
                f"{value.operator.value}("
                + ", ".join(
                    self._format_value(item, scope_names=scope_names) for item in value.values
                )
                + ")"
            )
        if isinstance(value, FallbackExpression):
            return (
                f"{value.operator.value}("
                + ", ".join(
                    self._format_value(item, scope_names=scope_names) for item in value.values
                )
                + ")"
            )
        if isinstance(value, JoinExpression):
            names = {**scope_names, value.left_scope: "left", value.right_scope: "right"}
            return (
                "join("
                + ", ".join(
                    [
                        self._format_value(value.left, scope_names=scope_names),
                        self._format_value(value.right, scope_names=scope_names),
                        self._format_value(value.predicate, scope_names=names),
                    ]
                )
                + ")"
            )
        if isinstance(value, ConversionExpression):
            raise DSLFormatError("conversion expressions are not representable in DSL 1.0")
        raise DSLFormatError(f"unsupported value '{type(value).__name__}'")

    def _format_collection(self, value: CollectionExpression, scope_names: dict[str, str]) -> str:
        arguments = [self._format_value(value.collection, scope_names=scope_names)]
        if value.operator in {
            CollectionOperator.ANY,
            CollectionOperator.ALL,
            CollectionOperator.NONE,
            CollectionOperator.FILTER,
        }:
            assert value.predicate is not None
            arguments.append(
                self._format_value(
                    value.predicate,
                    implicit_item_scope=value.item_scope,
                    scope_names=scope_names,
                )
            )
        elif value.operator in {
            CollectionOperator.MAP,
            CollectionOperator.SORT_BY,
            CollectionOperator.GROUP_BY,
        }:
            assert value.mapper is not None
            arguments.append(
                self._format_value(
                    value.mapper,
                    implicit_item_scope=value.item_scope,
                    scope_names=scope_names,
                )
            )
            if (
                value.operator is CollectionOperator.SORT_BY
                and value.direction.value == "descending"
            ):
                arguments.append("desc")
        elif value.operator in {
            CollectionOperator.SELECT,
            CollectionOperator.PICK,
            CollectionOperator.OMIT,
        }:
            arguments.extend(json.dumps(field) for field in value.fields)
        elif value.operator is CollectionOperator.RENAME:
            for old, new in value.rename.items():
                arguments.extend([json.dumps(old), json.dumps(new)])
        elif value.operator is CollectionOperator.ZIP:
            assert value.other is not None
            arguments.append(self._format_value(value.other, scope_names=scope_names))
        name = "distinct" if value.operator is CollectionOperator.DISTINCT else value.operator.value
        return f"{name}(" + ", ".join(arguments) + ")"

    @staticmethod
    def _format_type(value_type) -> str:
        if (
            value_type.nullable
            or value_type.items is not None
            or value_type.fields
            or value_type.enum_values is not None
        ):
            raise DSLFormatError(
                "structured, nullable, or enumerated types are not representable in DSL 1.0"
            )
        try:
            return _TYPE_NAMES[value_type.kind]
        except KeyError as error:
            raise DSLFormatError(f"unsupported portable type '{value_type.kind}'") from error

    @staticmethod
    def _format_path(parts) -> str:
        return ".".join(str(part) for part in parts)

    @staticmethod
    def _format_field(name: str) -> str:
        return name if _IDENTIFIER.fullmatch(name) else json.dumps(name, ensure_ascii=False)

    @staticmethod
    def _format_json(value) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))

    @staticmethod
    def _format_duration(value) -> str:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise DSLFormatError("a DSL duration must be a non-negative number of seconds")
        number = int(value) if float(value).is_integer() else value
        return f"{number}s"


format_dsl = format_workflow
format = format_workflow
