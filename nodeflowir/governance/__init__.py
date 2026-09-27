"""Portable ownership, revision, sharing, and resource-dependency contracts."""

from typing import TYPE_CHECKING

from nodeflowir.governance.models import (
    AccessGrant,
    ExecutionIdentityMode,
    ExecutionIdentityPolicy,
    ResourceDependency,
    ResourceFieldContract,
    ResourceReference,
    RevisionPrecondition,
    SubjectReference,
    SubjectType,
    WorkflowAccessPolicy,
    WorkflowAccessRole,
    WorkflowIdentity,
    WorkflowRevision,
    WorkflowVisibility,
)

if TYPE_CHECKING:
    from nodeflowir.ir.workflow import Workflow
    from nodeflowir.nodes.registry import NodeRegistry


def collect_resource_dependencies(
    workflow: "Workflow", registry: "NodeRegistry"
) -> tuple[ResourceDependency, ...]:
    """Inspect declared external resources without resolving or authorizing them."""

    from nodeflowir.governance.dependencies import collect_resource_dependencies as _collect

    return _collect(workflow, registry)


__all__ = [
    "AccessGrant",
    "ExecutionIdentityMode",
    "ExecutionIdentityPolicy",
    "ResourceDependency",
    "ResourceFieldContract",
    "ResourceReference",
    "RevisionPrecondition",
    "SubjectReference",
    "SubjectType",
    "WorkflowAccessPolicy",
    "WorkflowAccessRole",
    "WorkflowIdentity",
    "WorkflowRevision",
    "WorkflowVisibility",
    "collect_resource_dependencies",
]
