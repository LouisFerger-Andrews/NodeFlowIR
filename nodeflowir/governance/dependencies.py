"""Pure inspection helpers for declared external workflow resource dependencies."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import JsonValue, ValidationError

from nodeflowir.governance.models import (
    ResourceDependency,
    ResourceFieldContract,
    ResourceReference,
)
from nodeflowir.ir.workflow import Workflow
from nodeflowir.nodes.registry import NodeRegistry, UnknownNodeDefinitionError


def _references_for_value(
    value: JsonValue,
    contract: ResourceFieldContract,
    *,
    provider_id: str | None,
) -> tuple[ResourceReference, ...]:
    """Convert a configured stable ID (or explicit resource object) to references.

    Invalid configuration values are intentionally ignored here: normal
    workflow validation reports their contract/type problems.  This helper is
    an inspection aid, not a second validator or a remote resource resolver.
    """

    values = value if isinstance(value, list) else [value]
    references: list[ResourceReference] = []
    for candidate in values:
        if isinstance(candidate, str):
            references.append(
                ResourceReference(
                    resource_type=contract.resource_type,
                    resource_id=candidate,
                    provider_id=contract.provider_id or provider_id,
                )
            )
            continue
        if not isinstance(candidate, Mapping):
            continue
        try:
            reference = ResourceReference.model_validate(candidate)
        except ValidationError:
            continue
        if reference.resource_type != contract.resource_type:
            continue
        if contract.provider_id is not None and reference.provider_id not in {
            None,
            contract.provider_id,
        }:
            continue
        references.append(
            reference.model_copy(
                update={"provider_id": reference.provider_id or contract.provider_id or provider_id}
            )
        )
    return tuple(references)


def collect_resource_dependencies(
    workflow: Workflow,
    registry: NodeRegistry,
) -> tuple[ResourceDependency, ...]:
    """Return declared resource dependencies without I/O, authorization, or execution.

    Only exact, registered node definitions can describe a protected
    configuration field.  Unknown node definitions are left to the canonical
    workflow validator and contribute no inferred dependency here.
    """

    dependencies: list[ResourceDependency] = []
    for node in workflow.nodes:
        try:
            definition = registry.resolve(node.type, node.type_version)
        except UnknownNodeDefinitionError:
            continue
        for field in definition.config:
            contract = field.resource
            if contract is None or field.name not in node.config:
                continue
            provider_id = field.ui.provider if field.ui is not None else None
            for reference in _references_for_value(
                node.config[field.name], contract, provider_id=provider_id
            ):
                dependencies.append(
                    ResourceDependency(
                        node_id=node.id,
                        node_type=node.type,
                        node_version=node.type_version,
                        config_field=field.name,
                        resource=reference,
                        requires_authorization=contract.requires_authorization,
                    )
                )
    return tuple(dependencies)
