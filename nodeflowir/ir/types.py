"""Portable type descriptors used by node contracts and validation."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, JsonValue, model_validator

from nodeflowir._model import NodeFlowModel

Identifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
        description="A stable identifier used by an IR document.",
    ),
]
NodeTypeId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=200,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
        description="A stable, namespaced node type identifier.",
    ),
]
PortName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
        description="The name of a node input or output port.",
    ),
]
SemanticVersion = Annotated[
    str,
    Field(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
        description="A semantic version string.",
    ),
]


class ValueKind(StrEnum):
    """Portable types understood by the canonical IR."""

    ANY = "any"
    NULL = "null"
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    DATE = "date"
    DATETIME = "datetime"
    DURATION = "duration"
    STATUS = "status"


class TypeSpec(NodeFlowModel):
    """A serializable description of a value carried through a node port.

    ``object`` fields and ``array`` item types are optional so a contract can
    intentionally declare an opaque object or array.  This keeps the base IR
    portable while still allowing a consuming application to publish useful
    structural detail.
    """

    kind: ValueKind
    nullable: bool = False
    items: TypeSpec | None = None
    fields: dict[PortName, TypeSpec] = Field(default_factory=dict)
    enum_values: tuple[JsonValue, ...] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _check_structure(self) -> TypeSpec:
        if self.kind is not ValueKind.ARRAY and self.items is not None:
            raise ValueError("'items' is only valid for an array type")
        if self.kind is not ValueKind.OBJECT and self.fields:
            raise ValueError("'fields' is only valid for an object type")
        if self.enum_values is not None and self.kind in {
            ValueKind.ANY,
            ValueKind.ARRAY,
            ValueKind.OBJECT,
        }:
            raise ValueError("'enum_values' is only valid for scalar types")
        if self.enum_values is not None:
            unbounded = self.model_copy(update={"enum_values": None})
            if any(not unbounded.accepts(value) for value in self.enum_values):
                raise ValueError("each enum value must match the declared scalar type")
        if self.kind is ValueKind.NULL and self.nullable:
            raise ValueError("a null type cannot also be nullable")
        return self

    def accepts(self, value: Any) -> bool:
        """Return whether a JSON-compatible literal conforms to this type."""

        if value is None:
            return self.nullable or self.kind in {ValueKind.NULL, ValueKind.ANY}
        if self.kind is ValueKind.ANY:
            return True
        if self.kind is ValueKind.NULL:
            return False
        if self.kind is ValueKind.STRING:
            accepted = isinstance(value, str)
            return accepted and self._accepts_enum(value)
        if self.kind is ValueKind.BOOLEAN:
            accepted = isinstance(value, bool)
            return accepted and self._accepts_enum(value)
        if self.kind is ValueKind.INTEGER:
            accepted = isinstance(value, int) and not isinstance(value, bool)
            return accepted and self._accepts_enum(value)
        if self.kind is ValueKind.NUMBER:
            accepted = isinstance(value, (int, float)) and not isinstance(value, bool)
            return accepted and self._accepts_enum(value)
        if self.kind is ValueKind.ARRAY:
            return isinstance(value, list) and (
                self.items is None or all(self.items.accepts(item) for item in value)
            )
        if self.kind is ValueKind.OBJECT:
            if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
                return False
            return all(
                name in value and field_type.accepts(value[name])
                for name, field_type in self.fields.items()
            )
        if self.kind is ValueKind.DATE:
            if not isinstance(value, str):
                return False
            try:
                date.fromisoformat(value)
            except ValueError:
                return False
            return self._accepts_enum(value)
        if self.kind is ValueKind.DATETIME:
            if not isinstance(value, str):
                return False
            try:
                datetime.fromisoformat(value)
            except ValueError:
                return False
            return self._accepts_enum(value)
        if self.kind is ValueKind.DURATION:
            accepted = (
                isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
            )
            return accepted and self._accepts_enum(value)
        if self.kind is ValueKind.STATUS:
            accepted = value in {"success", "failed", "completed", "cancelled"}
            return accepted and self._accepts_enum(value)
        return False

    def _accepts_enum(self, value: Any) -> bool:
        return self.enum_values is None or value in self.enum_values

    def is_assignable_to(self, target: TypeSpec) -> bool:
        """Return whether this output type can be connected to ``target``."""

        if target.kind is ValueKind.ANY or self.kind is ValueKind.ANY:
            return True
        if self.kind is ValueKind.NULL:
            return target.kind is ValueKind.NULL or target.nullable
        if self.kind is not target.kind:
            return self.kind is ValueKind.INTEGER and target.kind is ValueKind.NUMBER
        if self.nullable and not target.nullable:
            return False
        if target.enum_values is not None:
            if self.enum_values is None:
                return False
            if not all(value in target.enum_values for value in self.enum_values):
                return False
        if self.kind is ValueKind.ARRAY:
            if target.items is None:
                return True
            return self.items is not None and self.items.is_assignable_to(target.items)
        if self.kind is ValueKind.OBJECT and target.fields:
            return all(
                (source_field := self.fields.get(name)) is not None
                and source_field.is_assignable_to(target_field)
                for name, target_field in target.fields.items()
            )
        return True
