"""Ergonomic SDK helpers for declaring application-owned node contracts."""

from __future__ import annotations

import inspect
import types
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, ClassVar, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel, JsonValue

from nodeflowir.ir.types import TypeSpec, ValueKind
from nodeflowir.metadata import Deprecation
from nodeflowir.nodes.contract import NodeDefinition, PortDefinition
from nodeflowir.nodes.fields import ConfigField, ConfigurationField
from nodeflowir.nodes.registry import NodeRegistry

NodeTarget = Callable[..., Any] | type[Any]
PortSource = type[BaseModel] | Mapping[str, Any]


def _type_spec(annotation: Any) -> TypeSpec:
    """Translate common Python/Pydantic annotations to portable type specs."""

    if annotation is str:
        return TypeSpec(kind=ValueKind.STRING)
    if annotation is bool:
        return TypeSpec(kind=ValueKind.BOOLEAN)
    if annotation is int:
        return TypeSpec(kind=ValueKind.INTEGER)
    if annotation is float:
        return TypeSpec(kind=ValueKind.NUMBER)
    if annotation is date:
        return TypeSpec(kind=ValueKind.DATE)
    if annotation is datetime:
        return TypeSpec(kind=ValueKind.DATETIME)
    if annotation is timedelta:
        return TypeSpec(kind=ValueKind.DURATION)
    if annotation is type(None):
        return TypeSpec(kind=ValueKind.NULL)

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in {Union, types.UnionType}:
        non_null = [argument for argument in arguments if argument is not type(None)]
        if len(non_null) == 1 and len(non_null) != len(arguments):
            return _type_spec(non_null[0]).model_copy(update={"nullable": True})
        return TypeSpec(kind=ValueKind.ANY)
    if origin in {list, Sequence}:
        item_type = _type_spec(arguments[0]) if arguments else None
        return TypeSpec(kind=ValueKind.ARRAY, items=item_type)
    if origin in {dict, Mapping}:
        return TypeSpec(kind=ValueKind.OBJECT)
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return TypeSpec(
            kind=ValueKind.OBJECT,
            fields={
                name: _type_spec(field.annotation)
                for name, field in annotation.model_fields.items()
            },
        )
    return TypeSpec(kind=ValueKind.ANY)


def _ports_from_source(source: PortSource, *, inputs: bool) -> dict[str, PortDefinition]:
    if inspect.isclass(source) and issubclass(source, BaseModel):
        return {
            name: PortDefinition(
                type=_type_spec(field.annotation),
                required=field.is_required() if inputs else True,
                description=field.description,
            )
            for name, field in source.model_fields.items()
        }
    ports: dict[str, PortDefinition] = {}
    for name, annotation in source.items():
        ports[name] = (
            annotation
            if isinstance(annotation, PortDefinition)
            else PortDefinition(type=_type_spec(annotation))
        )
    return ports


def _outputs_from_annotation(annotation: Any) -> dict[str, PortDefinition]:
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return _ports_from_source(annotation, inputs=False)
    if isinstance(annotation, Mapping):
        return _ports_from_source(annotation, inputs=False)
    return {"result": PortDefinition(type=_type_spec(annotation))}


def definition_from_callable(
    function: Callable[..., Any],
    *,
    type_id: str,
    version: str,
    display_name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    icon: str | None = None,
    search_terms: tuple[str, ...] = (),
    deprecation: Deprecation | None = None,
    handler: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> NodeDefinition:
    """Build a node contract from a fully annotated function signature."""

    signature = inspect.signature(function)
    hints = get_type_hints(function)
    inputs: dict[str, PortDefinition] = {}
    for parameter in signature.parameters.values():
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            raise TypeError("node functions cannot use *args or **kwargs")
        if parameter.name not in hints:
            raise TypeError(f"node input '{parameter.name}' must have a type annotation")
        inputs[parameter.name] = PortDefinition(
            type=_type_spec(hints[parameter.name]),
            required=parameter.default is inspect.Parameter.empty,
        )
    if "return" not in hints:
        raise TypeError("node functions must have a return type annotation")
    return NodeDefinition(
        type=type_id,
        version=version,
        display_name=display_name or function.__name__.replace("_", " ").title(),
        description=description or inspect.getdoc(function),
        category=category,
        icon=icon,
        search_terms=search_terms,
        deprecation=deprecation,
        handler=handler,
        inputs=inputs,
        outputs=_outputs_from_annotation(hints["return"]),
        metadata=metadata or {},
    )


def definition_from_class(
    target: type[Any],
    *,
    type_id: str,
    version: str,
    display_name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    icon: str | None = None,
    search_terms: tuple[str, ...] = (),
    deprecation: Deprecation | None = None,
    handler: str | None = None,
    input_model: PortSource | None = None,
    output_model: PortSource | Any | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> NodeDefinition:
    """Build a node contract from a concise class declaration.

    Class attributes assigned with :class:`ConfigField` become node
    configuration.  The optional ``output`` class attribute, or ``output_model``
    decorator argument, supplies typed output ports.
    """

    hints = get_type_hints(target, include_extras=True)
    config: list[ConfigurationField] = []
    for name, marker in target.__dict__.items():
        if not isinstance(marker, ConfigField):
            continue
        annotation = hints.get(name)
        if annotation is None or get_origin(annotation) is ClassVar:
            raise TypeError(f"configuration field '{name}' must have a value type annotation")
        config.append(marker.to_definition(name, _type_spec(annotation)))

    explicit_inputs = input_model if input_model is not None else getattr(target, "inputs", None)
    inputs = _ports_from_source(explicit_inputs, inputs=True) if explicit_inputs is not None else {}
    explicit_outputs = output_model if output_model is not None else getattr(target, "output", None)
    outputs = _outputs_from_annotation(explicit_outputs) if explicit_outputs is not None else {}
    return NodeDefinition(
        type=type_id,
        version=version,
        display_name=display_name or target.__name__.replace("_", " ").title(),
        description=description or inspect.getdoc(target),
        category=category,
        icon=icon,
        search_terms=search_terms,
        deprecation=deprecation,
        handler=handler,
        config=tuple(config),
        inputs=inputs,
        outputs=outputs,
        metadata=metadata or {},
    )


def node(
    type_id: str | None = None,
    *,
    id: str | None = None,
    version: str = "1.0.0",
    registry: NodeRegistry | None = None,
    display_name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    icon: str | None = None,
    search_terms: tuple[str, ...] = (),
    deprecation: Deprecation | None = None,
    handler: str | None = None,
    input_model: PortSource | None = None,
    output_model: PortSource | Any | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> Callable[[NodeTarget], NodeTarget]:
    """Attach and optionally register a typed contract for a class or function.

    ``type_id`` is positional for compact function declarations; ``id`` is an
    explicit alias for class-style declarations.  The decorated target is never
    executed by NodeFlowIR.
    """

    if type_id is None and id is None:
        raise TypeError("node requires type_id or id")
    if type_id is not None and id is not None and type_id != id:
        raise TypeError("type_id and id must match when both are supplied")
    resolved_type_id = type_id or id
    assert resolved_type_id is not None

    def decorate(target: NodeTarget) -> NodeTarget:
        if inspect.isclass(target):
            definition = definition_from_class(
                target,
                type_id=resolved_type_id,
                version=version,
                display_name=display_name,
                description=description,
                category=category,
                icon=icon,
                search_terms=search_terms,
                deprecation=deprecation,
                handler=handler,
                input_model=input_model,
                output_model=output_model,
                metadata=metadata,
            )
        else:
            if input_model is not None or output_model is not None:
                raise TypeError(
                    "input_model and output_model are only valid for class node declarations"
                )
            definition = definition_from_callable(
                target,
                type_id=resolved_type_id,
                version=version,
                display_name=display_name,
                description=description,
                category=category,
                icon=icon,
                search_terms=search_terms,
                deprecation=deprecation,
                handler=handler,
                metadata=metadata,
            )
        if registry is not None:
            registry.register(definition)
        target.__nodeflowir_definition__ = definition
        return target

    return decorate
