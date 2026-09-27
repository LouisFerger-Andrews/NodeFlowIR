"""Build a unified frontend-facing catalog from built-ins and registered nodes."""

from __future__ import annotations

from nodeflowir.catalog.builtins import builtin_catalog_items
from nodeflowir.catalog.models import (
    CatalogBehavior,
    CatalogConfigurationField,
    CatalogFieldType,
    CatalogItemKind,
    CatalogPort,
    CatalogPortKind,
    CatalogPortRole,
    CatalogPresentation,
    PortCardinality,
    PortDirection,
    RendererKind,
    VisualMode,
    WorkflowCatalog,
    WorkflowCatalogItem,
    catalog_type_for_value_kind,
)
from nodeflowir.nodes import NodeDefinition, NodeRegistry, WidgetKind


def _node_item_id(definition: NodeDefinition) -> str:
    return f"node:{definition.type}@{definition.version}"


def _config_field_type(definition_field) -> CatalogFieldType:
    ui = definition_field.ui
    if ui is not None and ui.widget is WidgetKind.SELECT and ui.provider is not None:
        return CatalogFieldType.DYNAMIC_SELECT
    if ui is not None and ui.widget is WidgetKind.MULTI_SELECT and ui.provider is not None:
        return CatalogFieldType.MULTI_SELECT
    if definition_field.type.enum_values is not None:
        return CatalogFieldType.ENUM
    return catalog_type_for_value_kind(definition_field.type.kind)


def _node_config_field(definition_field) -> CatalogConfigurationField:
    return CatalogConfigurationField(
        type=_config_field_type(definition_field),
        required=definition_field.required,
        description=definition_field.description,
        data_type=definition_field.type,
        default=definition_field.default,
        has_default=definition_field.has_default,
        enum_values=definition_field.type.enum_values,
        provider=definition_field.ui.provider if definition_field.ui is not None else None,
        constraints=definition_field.constraints,
        ui=definition_field.ui,
        resource=definition_field.resource,
    )


def _node_port(name: str, port, direction: PortDirection) -> CatalogPort:
    return CatalogPort(
        id=name,
        label=name,
        kind=CatalogPortKind.DATA,
        direction=direction,
        cardinality=(
            PortCardinality.ONE if direction is PortDirection.INPUT else PortCardinality.MANY
        ),
        required=port.required if direction is PortDirection.INPUT else False,
        data_type=port.type,
        description=port.description,
        ui=port.ui,
    )


def _node_control_port(direction: PortDirection) -> CatalogPort:
    """Expose the generic :class:`NodeStep` control path for every node."""

    return CatalogPort(
        id="$control.in" if direction is PortDirection.INPUT else "$control.out",
        label="In" if direction is PortDirection.INPUT else "Next",
        kind=CatalogPortKind.CONTROL,
        direction=direction,
        cardinality=(
            PortCardinality.ONE if direction is PortDirection.INPUT else PortCardinality.MANY
        ),
        required=direction is PortDirection.INPUT,
        role=(
            CatalogPortRole.ENTRY if direction is PortDirection.INPUT else CatalogPortRole.DEFAULT
        ),
        description="Structured NodeStep placement; not a node data contract.",
    )


def node_catalog_item(definition: NodeDefinition) -> WorkflowCatalogItem:
    """Translate one registered application node definition to catalog metadata."""

    return WorkflowCatalogItem(
        id=_node_item_id(definition),
        kind=CatalogItemKind.NODE,
        type=definition.type,
        version=definition.version,
        display_name=definition.display_name or definition.type,
        description=definition.description,
        category=definition.category or "General",
        visual_mode=VisualMode.CANVAS,
        presentation=CatalogPresentation(
            name=definition.display_name or definition.type,
            category=definition.category or "General",
            description=definition.description,
            renderer=RendererKind.STANDARD,
            icon=definition.icon,
            search_terms=definition.search_terms,
        ),
        behavior=CatalogBehavior(
            supports_retry=True,
            supports_timeout=True,
            supports_error_path=True,
        ),
        deprecation=definition.deprecation,
        configuration_schema={field.name: _node_config_field(field) for field in definition.config},
        input_ports=(
            _node_control_port(PortDirection.INPUT),
            *(
                _node_port(name, port, PortDirection.INPUT)
                for name, port in definition.inputs.items()
            ),
        ),
        output_ports=(
            _node_control_port(PortDirection.OUTPUT),
            *(
                _node_port(name, port, PortDirection.OUTPUT)
                for name, port in definition.outputs.items()
            ),
        ),
        capabilities={
            "handler_reference": definition.handler is not None,
            "versioned": True,
            "structured_control_step": True,
        },
        metadata=definition.metadata,
    )


def build_workflow_catalog(*, node_registry: NodeRegistry) -> WorkflowCatalog:
    """Build a deterministic catalog suitable for an application-owned API.

    Provider identifiers remain declarative references: catalog construction
    never resolves dynamic options or invokes an execution handler.
    """

    node_items = sorted(
        (node_catalog_item(definition) for definition in node_registry),
        key=lambda item: (item.type, item.version or ""),
    )
    return WorkflowCatalog(items=(*builtin_catalog_items(), *node_items))
