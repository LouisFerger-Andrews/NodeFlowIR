"""Build and validate framework-neutral structured-workflow authoring contexts."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TypeAlias, cast

from pydantic import JsonValue

from nodeflowir.authoring.models import AuthoringContext, AuthoringProviderValues
from nodeflowir.catalog import WorkflowCatalog
from nodeflowir.ir import Workflow
from nodeflowir.nodes import NodeRegistry, ProviderOption, WidgetKind
from nodeflowir.validation import IssueCode, ValidationIssue, ValidationResult, validate_workflow

ProviderValuesInput: TypeAlias = Mapping[str, Sequence[ProviderOption | Mapping[str, JsonValue]]]


def workflow_json_schema() -> dict[str, JsonValue]:
    """Return the canonical ``Workflow`` validation schema for structured output.

    This is the normal Pydantic schema of the canonical IR model, not an
    AI-specific shadow schema.  It includes the existing discriminators for
    value and control-flow unions.
    """

    return cast(dict[str, JsonValue], Workflow.model_json_schema(mode="validation"))


def build_authoring_context(
    *,
    catalog: WorkflowCatalog,
    provider_values: ProviderValuesInput | None = None,
    categories: Collection[str] | None = None,
    item_ids: Collection[str] | None = None,
) -> AuthoringContext:
    """Build a serializable context from the shared catalog and supplied options.

    Provider values are intentionally supplied by the consuming application;
    this function does not resolve providers.  Optional filters reduce context
    size without changing the source of truth for available capabilities.
    """

    filtered_catalog = _filter_catalog(catalog, categories=categories, item_ids=item_ids)
    known_provider_ids = _catalog_provider_ids(filtered_catalog)
    normalized_values = _normalize_provider_values(provider_values)
    unknown_provider_ids = set(normalized_values).difference(known_provider_ids)
    if unknown_provider_ids:
        names = ", ".join(sorted(unknown_provider_ids))
        raise ValueError(f"provider values are not referenced by this catalog: {names}")
    return AuthoringContext(
        workflow_schema=workflow_json_schema(),
        catalog=filtered_catalog,
        provider_values=tuple(normalized_values[key] for key in sorted(normalized_values)),
    )


def validate_authored_workflow(
    workflow: Workflow,
    *,
    registry: NodeRegistry,
    context: AuthoringContext | None = None,
    provider_values: ProviderValuesInput | None = None,
) -> ValidationResult:
    """Run canonical validation with optional supplied dynamic-provider checks.

    The static result always comes from :func:`validate_workflow`.  When live
    values are explicitly supplied, this helper additionally checks configured
    select values against those values.  It never resolves a provider or makes
    workflow loading depend on external systems.
    """

    if context is not None and provider_values is not None:
        raise ValueError("pass either context or provider_values, not both")
    result = validate_workflow(workflow, registry)
    dynamic_values = (
        {entry.provider: entry.options for entry in context.provider_values}
        if context is not None
        else {
            provider: entry.options
            for provider, entry in _normalize_provider_values(provider_values).items()
        }
    )
    if not dynamic_values:
        return result

    issues = list(result.issues)
    for node_index, node in enumerate(workflow.nodes):
        try:
            definition = registry.resolve(node.type, node.type_version)
        except LookupError:
            continue
        for config_field in definition.config:
            ui = config_field.ui
            provider_id = ui.provider if ui is not None else None
            if provider_id is None or provider_id not in dynamic_values:
                continue
            configured_value = node.config.get(config_field.name)
            if configured_value is None:
                continue
            if ui.widget is WidgetKind.SELECT and isinstance(configured_value, str):
                selected_values = (configured_value,)
            elif (
                ui.widget is WidgetKind.MULTI_SELECT
                and isinstance(configured_value, list)
                and all(isinstance(value, str) for value in configured_value)
            ):
                selected_values = tuple(configured_value)
            else:
                # The canonical static validator reports malformed field types.
                continue
            allowed_values = {option.value for option in dynamic_values[provider_id]}
            for selected_value in selected_values:
                if selected_value not in allowed_values:
                    issues.append(
                        ValidationIssue(
                            code=IssueCode.INVALID_DYNAMIC_PROVIDER_VALUE,
                            message=(
                                f"configuration '{node.id}.{config_field.name}' must use a current "
                                f"stable value from provider '{provider_id}'"
                            ),
                            path=("nodes", node_index, "config", config_field.name),
                            expected=f"a stable value from provider '{provider_id}'",
                            received=selected_value,
                        )
                    )
    return ValidationResult(issues=tuple(issues))


def _filter_catalog(
    catalog: WorkflowCatalog,
    *,
    categories: Collection[str] | None,
    item_ids: Collection[str] | None,
) -> WorkflowCatalog:
    category_filter = set(categories) if categories is not None else None
    item_id_filter = set(item_ids) if item_ids is not None else None
    if item_id_filter is not None:
        known_ids = {item.id for item in catalog.items}
        unknown_ids = item_id_filter.difference(known_ids)
        if unknown_ids:
            names = ", ".join(sorted(unknown_ids))
            raise ValueError(f"catalog item ids are not available: {names}")
    items = tuple(
        item
        for item in catalog.items
        if (category_filter is None or item.category in category_filter)
        and (item_id_filter is None or item.id in item_id_filter)
    )
    return catalog.model_copy(update={"items": items})


def _catalog_provider_ids(catalog: WorkflowCatalog) -> set[str]:
    provider_ids: set[str] = set()
    for item in catalog.items:
        fields = (*item.configuration_schema.values(),)
        if item.branch_definition is not None:
            fields = (*fields, *item.branch_definition.branch_config_schema.values())
        for field in fields:
            if field.provider is not None:
                provider_ids.add(field.provider)
    return provider_ids


def _normalize_provider_values(
    provider_values: ProviderValuesInput | None,
) -> dict[str, AuthoringProviderValues]:
    if provider_values is None:
        return {}
    return {
        provider_id: AuthoringProviderValues(provider=provider_id, options=tuple(options))
        for provider_id, options in provider_values.items()
    }
