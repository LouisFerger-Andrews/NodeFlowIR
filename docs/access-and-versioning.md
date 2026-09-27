# Access, ownership, resource dependencies, and versioning

NodeFlowIR provides portable contracts for workflow identity, revision lineage,
sharing intent, external resource dependencies, and intended execution
authority. It does not identify a person, persist a workflow, decide whether a
request is allowed, or execute a workflow.

> **NodeFlowIR can describe ownership, revision identity, sharing intent, resource dependencies, and execution authorization requirements; the consuming application owns identity, persistence, authorization decisions, and enforcement.**

This guide deliberately separates three concerns that are often accidentally
combined:

1. **Workflow access** — who may view, edit, share, or be granted execution access to a workflow definition.
2. **Resource access** — whether a principal may use a referenced external resource such as a test suite, agent, dataset, secret, or deployment target.
3. **Execution identity** — the authority a consuming runtime will use when it evaluates resource access for an invocation.

Sharing a workflow definition does not grant resource access and does not
delegate the owner's authority.

## Identity and immutable revisions

The schema-1.0 `Workflow.id` field is the stable workflow-document identifier;
its `workflow_id` property provides the more explicit name for code that works
with governance contracts. `schema_version` identifies the NodeFlowIR format,
and `workflow_version` is the positive immutable revision number of that
document.

```text
workflow ID:       wf_123        stable document identity
schema version:    1.0           NodeFlowIR format
workflow version:  8             one immutable semantic revision
```

`WorkflowRevision` is a portable record for a stored revision and optional
lineage/audit hints. A consumer persists the actual revision history.

```python
from nodeflowir import RevisionPrecondition, WorkflowRevision

revision = WorkflowRevision(
    workflow_id="wf_123",
    schema_version="1.0",
    workflow_version=8,
    based_on_version=7,
)

# A client sending an edit based on revision 7 supplies this to its own API.
precondition = RevisionPrecondition(workflow_id="wf_123", expected_version=7)
```

The consumer compares `expected_version` with its currently stored revision.
It creates revision 8 only when that comparison succeeds; otherwise it reports
its own conflict response. NodeFlowIR has no save API and never mutates a
historical revision.

`WorkflowAccessPolicy` and `ExecutionIdentityPolicy` are intentionally outside
the canonical semantic `Workflow` document. A consumer can change sharing
state, for example, without manufacturing a new workflow-logic revision.

## Opaque subjects and sharing intent

Subjects are stable opaque references. NodeFlowIR understands only their
generic category (`user`, `group`, `project`, or `service`), never whether they
exist or who belongs to them.

```python
from nodeflowir import (
    AccessGrant,
    SubjectReference,
    SubjectType,
    WorkflowAccessPolicy,
    WorkflowAccessRole,
    WorkflowIdentity,
)

alice = SubjectReference(type=SubjectType.USER, id="user_alice")
quality_project = SubjectReference(type=SubjectType.PROJECT, id="project_quality")
bob = SubjectReference(type=SubjectType.USER, id="user_bob")

identity = WorkflowIdentity(workflow_id="wf_123", project_scope=quality_project)
policy = WorkflowAccessPolicy(
    owner=alice,
    entries=(
        AccessGrant(subject=quality_project, role=WorkflowAccessRole.EDITOR),
        AccessGrant(subject=bob, role=WorkflowAccessRole.VIEWER),
        AccessGrant(subject=bob, role=WorkflowAccessRole.EXECUTOR),
    ),
)
```

The portable roles are `owner`, `editor`, `viewer`, `executor`, and `sharer`.
They are intent labels, not a permission engine. In particular, a consumer may
choose different meanings for an editor, and may keep `execute` separate from
view/edit access. `private`, `restricted`, and `project` visibility are also
high-level intent; a project visibility setting never implicitly grants every
project member the same capability.

## Protected resource fields and dependency inspection

A node contract can mark a configuration field as an application-owned
external resource. This is metadata; the value remains the stable ID selected
by a user or authoring system.

```python
from nodeflowir import ConfigField, ResourceFieldContract, Select, node


@node(id="qa.test-suite", version="1.0", handler="test_management.run_suite")
class TestSuiteNode:
    suite_id: str = ConfigField(
        ui=Select(provider="test_management.suites"),
        resource=ResourceFieldContract(
            resource_type="test_suite",
            provider_id="test_management.suites",
            requires_authorization=True,
        ),
    )
    output = bool
```

The resource annotation is included in catalog configuration metadata. It
allows a backend to discover the protected dependencies of a validated
workflow, with no provider call or external lookup:

```python
dependencies = flow.collect_resource_dependencies(workflow)

# ResourceDependency(
#   node_id="nightly_tests",
#   config_field="suite_id",
#   resource=ResourceReference(
#       resource_type="test_suite",
#       resource_id="suite_123",
#       provider_id="test_management.suites",
#   ),
#   requires_authorization=True,
# )
```

This inspection is useful before saving or activating a workflow, for schedule
activation checks, audit displays, and runtime preflight. It does **not**
answer whether the resource exists or whether a subject may use it. A deleted
or revoked resource reference remains structurally valid IR so an application
can report the correct runtime condition instead of corrupting its history.

Provider filtering can improve the configuration UI, but it is never the only
security check. A consumer must re-check required resource access at the point
its security model requires, especially when a scheduled workflow runs after
access has changed.

## Execution identity is separate from sharing

`ExecutionIdentityPolicy` records intended authority; it never resolves,
impersonates, or authenticates that authority.

```python
from nodeflowir import ExecutionIdentityMode, ExecutionIdentityPolicy

run_as_owner = ExecutionIdentityPolicy(mode=ExecutionIdentityMode.OWNER)
run_as_caller = ExecutionIdentityPolicy(mode=ExecutionIdentityMode.CALLER)
run_as_configured_service = ExecutionIdentityPolicy(mode=ExecutionIdentityMode.SERVICE)
```

An explicit subject is also possible when the policy is intentionally
configured that way:

```python
ExecutionIdentityPolicy(
    mode=ExecutionIdentityMode.SUBJECT,
    subject=SubjectReference(type=SubjectType.SERVICE, id="nightly_scheduler"),
)
```

There is no default execution policy in these contracts. This makes scheduled
workflows explicit: when no interactive caller exists, the consuming
application must select and authorize the identity it will use.

Consider this workflow:

```text
Alice owns Workflow W and Test Suite T.
W references T and is shared with Bob as editor.
```

With `owner` execution identity, a consumer may resolve Alice and confirm that
Alice still has access to T when W runs. With `caller`, Bob must independently
have access to T when Bob triggers W. With `service`, the consumer evaluates
the configured service identity. None of these outcomes is decided by
NodeFlowIR. Sharing W with Bob does not automatically authorize Bob to use T
or impersonate Alice.

## Runtime authorization boundary

```text
NodeFlowIR
    ↓ validated workflow + declared resource dependencies + execution policy
Consuming application
    ↓ resolves principal and resource state
Authorization preflight / runtime checks
    ↓ allowed or denied
Application runtime
    ↓ actual handler invocation
```

> **A workflow that is structurally valid is not necessarily authorized to execute.**

NodeFlowIR validation answers whether the workflow is well-formed against its
registered node contracts. The consuming application answers whether a real
principal may access each current external resource and whether execution is
allowed. This distinction remains true when a resource has been deleted, an
owner has lost access, or a workflow is launched by a scheduler.
