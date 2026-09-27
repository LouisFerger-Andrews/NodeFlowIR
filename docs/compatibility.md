# Compatibility, deprecation, fingerprints, and revision comparison

NodeFlowIR keeps several version axes intentionally separate:

| Contract | Field | Meaning |
| --- | --- | --- |
| Canonical IR format | `Workflow.schema_version` | The serialized NodeFlowIR schema. |
| Workflow revision | `Workflow.workflow_version` | One immutable revision of a stable workflow ID. |
| Node contract | `NodeDefinition.version` / `NodeInstance.type_version` | The exact registered application capability required by an instance. |
| Catalog protocol | `WorkflowCatalog.catalog_version` | The frontend/authoring discovery contract version. |
| Library package | package version | Python API and distribution compatibility. |

`WorkflowCatalog.schema_version` remains in the serialized catalog for
compatibility with earlier catalog consumers. New consumers should use the
explicit `catalog_version` field. Both are `"1.0"` in this release.

## Compatibility preflight

`NodeFlow.check_compatibility` is a small, read-only discovery check. It is
useful before normal loading when a client needs to know whether this installed
library can attempt to process a document:

```python
result = flow.check_compatibility(
    workflow_payload,
    catalog_version="1.0",  # Optional frontend/consumer protocol value.
)

if not result.is_compatible:
    payload = result.model_dump(mode="json")
```

It reports serializable issues with `code`, `message`, `path`, `expected`, and
`received` fields for malformed documents, unsupported IR schema versions,
unregistered node type/version pairs, and unsupported catalog protocol
versions. An explicitly registered schema migration counts as supported.

This preflight is deliberately **not** a second validator. It does not prove a
workflow is semantically valid; normal parsing and `validate_workflow` still
check configuration, references, types, control flow, and expressions.

## Safe deprecation

A node definition can remain registered and loadable while being marked for
new-authoring guidance:

```python
from nodeflowir import Deprecation, node


@node(
    id="qa.legacy-suite",
    version="1.0",
    deprecation=Deprecation(
        message="Use qa.test-suite@2.0.",
        replacement="node:qa.test-suite@2.0",
    ),
)
class LegacySuite: ...
```

The deprecation metadata is exposed unchanged in the unified catalog.
`catalog.palette_items()` intentionally omits deprecated canvas items, while
the complete catalog still contains them so a frontend can display an existing
workflow and migration guidance. NodeFlowIR does not rewrite an existing
workflow, remove the node contract, or infer a replacement automatically.

## Canonical semantic fingerprints

Use `workflow_fingerprint(workflow)` or `flow.workflow_fingerprint(workflow)`
for a stable SHA-256 digest of canonical workflow behavior:

```python
fingerprint = flow.workflow_fingerprint(workflow)
```

The fingerprint uses sorted, whitespace-free JSON and excludes stable document
identity, `workflow_version`, display name/description, node labels, and opaque
metadata. It includes schema version, inputs/constants, node type/version and
configuration, data connections, control flow, retry/timeout policies, and
outputs. It never includes current provider labels, provider options, handler
implementations, or any live external state.

This makes it suitable for semantic comparison, caching, and as an additional
concurrency signal. It is not a cryptographic authorization token.

## Structured revision diff

`workflow_diff(before, after)` and `flow.diff_workflows(before, after)` return
a deterministic `WorkflowDiff` rather than a presentation-oriented text diff.

```python
diff = flow.diff_workflows(revision_7, revision_8)
for change in diff.changes:
    print(change.kind, change.path)
```

Current change kinds cover workflow schema/revision/display metadata, inputs,
outputs, constants, node additions/removals/contracts/configuration/policies,
data connections, branch/match condition values, and control-flow shape. This
is sufficient for an application-owned revision-history UI or audit trail.
It does not persist revisions, merge concurrent edits, or resolve conflicts.

## Import, export, and compatibility policy

`flow.export_workflow(workflow)` returns the canonical JSON-compatible mapping.
`flow.import_workflow(payload)` is an explicit alias for the normal
schema-aware `load_workflow` path, including registered migrations and
canonical validation. JSON helpers remain available in
`nodeflowir.serialization`.

The library follows a deliberate compatibility policy:

- **Patch releases** fix defects without changing canonical IR, DSL, catalog,
  or supported public APIs.
- **Minor releases** may add backward-compatible optional fields, capabilities,
  node metadata, or DSL syntax with an explicit format/version contract.
- **Major releases** are required for breaking changes to canonical JSON/IR,
  public Python APIs, DSL syntax, catalog protocol, or established semantics.

Schema migrations are explicit. Node definition deprecation gives applications
time to migrate historical workflows rather than making valid saved documents
disappear abruptly.
