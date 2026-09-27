"""Typed configuration fields and frontend-neutral UI metadata for nodes."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, JsonValue, model_validator

from nodeflowir._model import NodeFlowModel
from nodeflowir.governance.models import ResourceFieldContract
from nodeflowir.ir.types import PortName, TypeSpec, ValueKind

BindingId = Annotated[
    str,
    Field(
        min_length=3,
        max_length=200,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
        description="A stable application-owned provider or handler reference.",
    ),
]


class WidgetKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    SECRET = "secret"
    TEXTAREA = "textarea"
    CODE = "code"


class FieldUI(NodeFlowModel):
    """A frontend-neutral hint for rendering one configuration field."""

    widget: WidgetKind
    provider: BindingId | None = None
    placeholder: str | None = None
    help_text: str | None = None

    @model_validator(mode="after")
    def _check_provider_widget(self) -> FieldUI:
        if self.provider is not None and self.widget not in {
            WidgetKind.SELECT,
            WidgetKind.MULTI_SELECT,
        }:
            raise ValueError("a dynamic provider is only valid for select or multi_select widgets")
        return self


class FieldConstraints(NodeFlowModel):
    """Portable, deterministic constraints for configuration literals."""

    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    pattern: str | None = None
    min_items: int | None = Field(default=None, ge=0)
    max_items: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_ranges(self) -> FieldConstraints:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError("min_length cannot exceed max_length")
        if (
            self.min_items is not None
            and self.max_items is not None
            and self.min_items > self.max_items
        ):
            raise ValueError("min_items cannot exceed max_items")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as error:
                raise ValueError(f"invalid regular expression: {error}") from error
        return self


class ConfigurationField(NodeFlowModel):
    """One static node configuration value, distinct from workflow inputs."""

    name: PortName
    type: TypeSpec
    required: bool = True
    default: JsonValue | None = None
    has_default: bool = False
    description: str | None = None
    constraints: FieldConstraints | None = None
    ui: FieldUI | None = None
    resource: ResourceFieldContract | None = None

    @model_validator(mode="after")
    def _check_definition(self) -> ConfigurationField:
        if self.has_default:
            if self.required:
                raise ValueError("a configuration field with a default must not be required")
            default_errors = self.value_errors(self.default)
            if default_errors:
                raise ValueError("configuration default is invalid: " + "; ".join(default_errors))
        elif self.default is not None:
            raise ValueError("default requires has_default=True")
        if self.ui is not None:
            if self.ui.widget is WidgetKind.SELECT and self.type.kind not in {
                ValueKind.STRING,
                ValueKind.ANY,
            }:
                raise ValueError("a select configuration field must have string-compatible values")
            if self.ui.widget is WidgetKind.MULTI_SELECT and self.type.kind not in {
                ValueKind.ARRAY,
                ValueKind.ANY,
            }:
                raise ValueError(
                    "a multi_select configuration field must have array-compatible values"
                )
        if (
            self.resource is not None
            and self.resource.provider_id is not None
            and self.ui is not None
            and self.ui.provider is not None
            and self.resource.provider_id != self.ui.provider
        ):
            raise ValueError("resource provider_id must match the configuration UI provider")
        return self

    def value_errors(self, value: JsonValue) -> tuple[str, ...]:
        """Return static type/constraint errors for a supplied configuration value."""

        errors: list[str] = []
        if not self.type.accepts(value):
            errors.append("does not match the declared type")
            return tuple(errors)
        if self.constraints is None:
            return ()
        constraints = self.constraints
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if constraints.minimum is not None and value < constraints.minimum:
                errors.append(f"must be at least {constraints.minimum}")
            if constraints.maximum is not None and value > constraints.maximum:
                errors.append(f"must be at most {constraints.maximum}")
        if isinstance(value, str):
            if constraints.min_length is not None and len(value) < constraints.min_length:
                errors.append(f"must contain at least {constraints.min_length} characters")
            if constraints.max_length is not None and len(value) > constraints.max_length:
                errors.append(f"must contain at most {constraints.max_length} characters")
            if constraints.pattern is not None and re.fullmatch(constraints.pattern, value) is None:
                errors.append("does not match the required pattern")
        if isinstance(value, list):
            if constraints.min_items is not None and len(value) < constraints.min_items:
                errors.append(f"must contain at least {constraints.min_items} items")
            if constraints.max_items is not None and len(value) > constraints.max_items:
                errors.append(f"must contain at most {constraints.max_items} items")
        return tuple(errors)


_UNSET = object()


class ConfigField:
    """Class-declaration marker consumed by :func:`nodeflowir.nodes.node`.

    The decorator takes the Python annotation as the portable configuration
    type.  ``resource`` can mark a stable configuration value as an external
    resource dependency for application-owned authorization preflight.  The
    marker is intentionally neither a descriptor nor a UI widget.
    """

    def __init__(
        self,
        *,
        required: bool | None = None,
        default: JsonValue | object = _UNSET,
        description: str | None = None,
        constraints: FieldConstraints | None = None,
        ui: FieldUI | None = None,
        resource: ResourceFieldContract | None = None,
    ) -> None:
        self.required = required
        self.default = default
        self.description = description
        self.constraints = constraints
        self.ui = ui
        self.resource = resource

    def to_definition(self, name: str, type_spec: TypeSpec) -> ConfigurationField:
        has_default = self.default is not _UNSET
        required = self.required if self.required is not None else not has_default
        default: Any = None if not has_default else self.default
        return ConfigurationField(
            name=name,
            type=type_spec,
            required=required,
            default=default,
            has_default=has_default,
            description=self.description,
            constraints=self.constraints,
            ui=self.ui,
            resource=self.resource,
        )


def Select(*, provider: BindingId, placeholder: str | None = None) -> FieldUI:
    """Return a select hint whose current options come from a backend provider."""

    return FieldUI(widget=WidgetKind.SELECT, provider=provider, placeholder=placeholder)


def MultiSelect(*, provider: BindingId, placeholder: str | None = None) -> FieldUI:
    """Return a multi-select hint whose current options come from a provider."""

    return FieldUI(widget=WidgetKind.MULTI_SELECT, provider=provider, placeholder=placeholder)
