"""Portable ownership, revision, and resource-access contracts.

These models intentionally describe *intent* only.  They do not look up a
principal, resolve a resource, or decide whether an action is permitted.
Those decisions belong to the consuming application.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from nodeflowir._model import NodeFlowModel
from nodeflowir.ir.types import Identifier, NodeTypeId, PortName, SemanticVersion

OpaqueIdentifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=500,
        description="An opaque, stable identifier interpreted by the consuming application.",
    ),
]
ResourceType = Annotated[
    str,
    Field(
        min_length=1,
        max_length=200,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
        description="A stable, application-defined external resource type identifier.",
    ),
]
ProviderIdentifier = Annotated[
    str,
    Field(
        min_length=3,
        max_length=200,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
        description="A stable application-owned dynamic provider reference.",
    ),
]


class SubjectType(StrEnum):
    """Portable subject categories; applications own subject resolution."""

    USER = "user"
    GROUP = "group"
    PROJECT = "project"
    SERVICE = "service"


class SubjectReference(NodeFlowModel):
    """A portable reference to an application-owned authorization subject."""

    type: SubjectType
    id: OpaqueIdentifier


class WorkflowVisibility(StrEnum):
    """High-level sharing intent, not an access-control decision."""

    PRIVATE = "private"
    RESTRICTED = "restricted"
    PROJECT = "project"


class WorkflowAccessRole(StrEnum):
    """Portable workflow-definition roles an application may interpret."""

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
    EXECUTOR = "executor"
    SHARER = "sharer"


class AccessGrant(NodeFlowModel):
    """One subject/role sharing grant for a workflow definition."""

    subject: SubjectReference
    role: WorkflowAccessRole


class WorkflowAccessPolicy(NodeFlowModel):
    """Portable workflow sharing and ownership intent.

    ``owner`` is deliberately explicit.  Grants may independently express
    definition viewing/editing, execution permission, and sharing intent;
    NodeFlowIR never infers one permission from another.
    """

    owner: SubjectReference
    visibility: WorkflowVisibility = WorkflowVisibility.RESTRICTED
    entries: tuple[AccessGrant, ...] = ()

    @model_validator(mode="after")
    def _check_entries(self) -> WorkflowAccessPolicy:
        keys = [(entry.subject.type, entry.subject.id, entry.role) for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("workflow access entries must be unique by subject and role")
        if any(entry.role is WorkflowAccessRole.OWNER for entry in self.entries):
            raise ValueError("the workflow owner must be declared through the owner field")
        return self


class ExecutionIdentityMode(StrEnum):
    """The intended authority under which a consumer may execute a workflow."""

    OWNER = "owner"
    CALLER = "caller"
    SERVICE = "service"
    SUBJECT = "subject"


class ExecutionIdentityPolicy(NodeFlowModel):
    """Execution-authority intent; it neither resolves nor impersonates a subject."""

    mode: ExecutionIdentityMode
    subject: SubjectReference | None = None

    @model_validator(mode="after")
    def _check_subject(self) -> ExecutionIdentityPolicy:
        if self.mode is ExecutionIdentityMode.SUBJECT and self.subject is None:
            raise ValueError("an explicit-subject execution policy requires subject")
        if self.mode is not ExecutionIdentityMode.SUBJECT and self.subject is not None:
            raise ValueError("subject is only valid for an explicit-subject execution policy")
        return self


class WorkflowIdentity(NodeFlowModel):
    """Stable workflow-document identity, independent of a semantic revision."""

    workflow_id: Identifier
    project_scope: SubjectReference | None = None

    @model_validator(mode="after")
    def _check_project_scope(self) -> WorkflowIdentity:
        if self.project_scope is not None and self.project_scope.type is not SubjectType.PROJECT:
            raise ValueError("project_scope must reference a project subject")
        return self


class WorkflowRevision(NodeFlowModel):
    """Identity and optional audit lineage for one immutable workflow revision."""

    workflow_id: Identifier
    schema_version: str = Field(min_length=1, max_length=50)
    workflow_version: int = Field(ge=1)
    based_on_version: int | None = Field(default=None, ge=1)
    created_by: SubjectReference | None = None

    @model_validator(mode="after")
    def _check_lineage(self) -> WorkflowRevision:
        if self.based_on_version is not None and self.based_on_version >= self.workflow_version:
            raise ValueError("based_on_version must precede workflow_version")
        return self


class RevisionPrecondition(NodeFlowModel):
    """The optimistic-concurrency expectation supplied by a saving client.

    A consumer compares ``expected_version`` to its currently stored revision
    and decides whether to create a new immutable revision or report a
    conflict.  NodeFlowIR intentionally has no persistence or save method.
    """

    workflow_id: Identifier
    expected_version: int = Field(ge=1)


class ResourceFieldContract(NodeFlowModel):
    """Marks a node configuration field as an external resource reference."""

    resource_type: ResourceType
    provider_id: ProviderIdentifier | None = None
    requires_authorization: bool = True


class ResourceReference(NodeFlowModel):
    """A stable, opaque reference to an external application resource."""

    resource_type: ResourceType
    resource_id: OpaqueIdentifier
    provider_id: ProviderIdentifier | None = None


class ResourceDependency(NodeFlowModel):
    """A protected external resource declared by one configured node instance."""

    node_id: Identifier
    node_type: NodeTypeId
    node_version: SemanticVersion
    config_field: PortName
    resource: ResourceReference
    requires_authorization: bool = True
