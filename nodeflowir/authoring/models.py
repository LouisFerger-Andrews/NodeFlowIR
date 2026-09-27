"""Pydantic contracts shared by visual, DSL, and AI workflow authoring."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from nodeflowir._model import NodeFlowModel
from nodeflowir.catalog import WorkflowCatalog
from nodeflowir.ir.workflow import CURRENT_SCHEMA_VERSION
from nodeflowir.nodes import ProviderOption
from nodeflowir.nodes.fields import BindingId


class AuthoringProviderValues(NodeFlowModel):
    """Current application-provided options for one catalog provider reference."""

    provider: BindingId
    options: tuple[ProviderOption, ...]

    @model_validator(mode="after")
    def _check_unique_values(self) -> AuthoringProviderValues:
        values = [option.value for option in self.options]
        if len(values) != len(set(values)):
            raise ValueError("provider options must have unique stable values")
        return self


class AuthoringConstraints(NodeFlowModel):
    """Machine-readable rules already enforced by the canonical validator."""

    only_registered_node_types: Literal[True] = True
    only_supported_builtin_constructs: Literal[True] = True
    node_versions_must_exist: Literal[True] = True
    required_configuration_must_be_provided: Literal[True] = True
    references_must_be_structured: Literal[True] = True
    references_must_be_valid: Literal[True] = True
    port_types_must_be_compatible: Literal[True] = True
    dynamic_options_use_stable_ids: Literal[True] = True
    arbitrary_code_prohibited: Literal[True] = True
    unknown_node_types_prohibited: Literal[True] = True
    static_validation: Literal["validate_workflow"] = "validate_workflow"


class AuthoringContext(NodeFlowModel):
    """The framework-neutral context supplied to a structured workflow author."""

    context_version: Literal["1.0"] = "1.0"
    ir_schema_version: Literal["1.0"] = CURRENT_SCHEMA_VERSION
    workflow_schema: dict[str, JsonValue]
    catalog: WorkflowCatalog
    provider_values: tuple[AuthoringProviderValues, ...] = ()
    authoring_constraints: AuthoringConstraints = Field(default_factory=AuthoringConstraints)

    @model_validator(mode="after")
    def _check_provider_ids(self) -> AuthoringContext:
        providers = [entry.provider for entry in self.provider_values]
        if len(providers) != len(set(providers)):
            raise ValueError("authoring context provider references must be unique")
        catalog_providers = {
            field.provider
            for item in self.catalog.items
            for field in (
                *item.configuration_schema.values(),
                *(
                    item.branch_definition.branch_config_schema.values()
                    if item.branch_definition is not None
                    else ()
                ),
            )
            if field.provider is not None
        }
        unknown_providers = set(providers).difference(catalog_providers)
        if unknown_providers:
            names = ", ".join(sorted(unknown_providers))
            raise ValueError(f"provider values are not referenced by this catalog: {names}")
        return self
