# Visual builder catalog contract

## Purpose and authority

`WorkflowCatalog` is the serializable, frontend-neutral discovery contract for a visual workflow builder. It is assembled from two semantic sources:

```text
NodeFlowIR built-in IR constructs ─┐
                                  ├─> WorkflowCatalog ─> consuming backend API ─> frontend
registered application nodes ─────┘
```

The catalog is not another workflow representation and it does not make built-in logic into application nodes. It describes what can be authored; a saved workflow is still a canonical `Workflow` document and `validate_workflow` remains the semantic authority.

> **NodeFlowIR defines semantics and structural contracts; the frontend defines presentation and interaction.**

Consequently, catalog entries deliberately contain no colors, icons, coordinates, dimensions, layout algorithm, animation, or frontend-framework concepts.

## Building and serializing a catalog

An application composes its registered node definitions, then serializes the catalog through its own API boundary:

```python
from nodeflowir import build_workflow_catalog

catalog = build_workflow_catalog(node_registry=node_registry)
payload = catalog.model_dump(mode="json")
```

`build_workflow_catalog` is deterministic. Built-in entries come first, and custom node entries are ordered by type and version. It never invokes an execution handler or a dynamic option provider.

Each entry has a globally unique catalog `id`, a semantic `kind`, stable `type`, optional definition `version`, display metadata, a `configuration_schema`, input/output `ports`, and optional branch metadata. The current catalog kinds are `node`, `control_flow`, `expression`, `collection_operation`, `transformation`, `aggregation`, `value`, and `execution_policy`.

Every custom-node entry also has the reserved `$control.in` and `$control.out` ports. They describe the generic `NodeStep` placement available to all executable nodes; declared node input/output ports remain data ports. The `$` prefix prevents a collision with application node port names, which use the portable IR port-name grammar. A visual editor can use those structural ports for sequence and branching while mapping the result back into `FlowBlock` / `NodeStep` models rather than inventing graph-edge semantics.

For example, an `if` entry has structural, rather than visual, branch metadata:

```json
{
  "id": "control_flow:if",
  "kind": "control_flow",
  "type": "if",
  "display_name": "If / Else",
  "category": "Logic",
  "configuration_schema": {
    "condition": {
      "type": "expression",
      "required": true,
      "data_type": {"kind": "any"},
      "capabilities": {
        "allowed_references": true,
        "context_aware": true
      }
    }
  },
  "input_ports": [{"id": "in", "kind": "control", "direction": "input"}],
  "output_ports": [
    {"id": "true", "label": "True", "kind": "control", "direction": "output"},
    {"id": "false", "label": "False", "kind": "control", "direction": "output"}
  ]
}
```

The frontend may draw that item as a diamond, a card, or any other interaction pattern. The catalog only states that the construct has one incoming control path, two named outgoing paths, and a required condition.

## Configuration schemas and references

`CatalogConfigurationField.type` identifies the semantic editor a frontend should offer. In addition to primitive editors, the catalog currently uses `literal`, `enum`, `expression`, `reference`, `node_output_reference`, `collection_reference`, `field_reference`, `dynamic_select`, `multi_select`, `object`, `list`, `duration`, and `type_spec`.

The accompanying portable `data_type`, constraints, allowed values, UI hint, and capabilities refine that editor. For example, a `filter` entry marks its collection source as a `collection_reference`, requires an explicit item-scope identifier, and marks its predicate as being evaluated in that collection-item scope. A frontend can offer a structured selector such as “Test Suite → Results → status” rather than a free-form expression string. It must persist the corresponding typed value/reference tree in the IR.

`earlier_nodes_only` is advisory discovery metadata for source pickers. The backend still validates lexical visibility, field paths, types, and control-flow scope after the frontend submits a workflow. `ports_are_compatible(source, target)` offers a lightweight local check for port direction, control/data family, and `TypeSpec` assignability; it does not replace full workflow validation.

## Ports and branches

Ports contain only structural connection information:

| Field | Meaning |
| --- | --- |
| `id` / `label` | Stable port name and optional human label. |
| `kind` | `control` or `data`. |
| `direction` | `input` or `output`. |
| `cardinality` | Whether one or many connections are meaningful. |
| `required` | Whether an input must receive a binding for the construct or node contract to be valid. |
| `data_type` | Required for data ports; a portable `TypeSpec`. |
| `dynamic` | An output port whose branches are user-configurable. |

Control-flow items retain their distinct IR semantics:

- `foreach` exposes `in`, `each`, and `completed`, and configures a collection plus an item scope.
- `parallel` has a dynamic `branch` control output, a `completed` output, and `minimum_branches: 2`.
- `match` has dynamic `case` outputs, a `default` output, and a case-branch schema requiring `case_value`.
- `retry` and `timeout` are execution-policy entries that attach to a node instance; they are not executable frontend components.

The catalog therefore lets an editor add and remove parallel or match branches without pretending that a fixed visual port count is part of the semantics.

Configuration field names use the corresponding canonical model names when they map directly to IR data. For example, `RetryPolicy` exposes `max_attempts`, `delay_seconds`, `backoff`, and `max_delay_seconds`; `TimeoutPolicy` exposes `timeout_seconds`. No DSL field-name translation is required for visual authoring.

## Dynamic provider values

A custom node entry carries a provider *reference*, not the provider's changing options:

```json
{
  "id": "node:qa.test-suite@1.0",
  "kind": "node",
  "type": "qa.test-suite",
  "version": "1.0",
  "configuration_schema": {
    "suite_id": {
      "type": "dynamic_select",
      "provider": "test_management.suites",
      "required": true
    }
  }
}
```

The application backend resolves `test_management.suites` when the user opens or edits the node and returns current `{value, label}` options through an application-owned API. A workflow instance stores only a selected stable value such as `"suite_123"`. Adding a Test Management suite changes provider results, not this definition or existing workflow documents.

The same boundary applies to execution: a node definition may name the opaque handler reference `test_management.run_suite`, but the application owns registration, invocation, authorization, and business implementation. The frontend has no need to invoke or understand it.

## Frontend authoring sequence

The intended API-neutral sequence is:

1. The frontend requests the workflow catalog from its backend.
2. The backend serializes `WorkflowCatalog`.
3. The frontend groups catalog items into its “add workflow element” menu.
4. The user selects a built-in construct or registered custom node.
5. The frontend reads that item's configuration schema.
6. It renders structured configuration controls and, when requested, asks the backend for dynamic provider options.
7. It reads the item's port and branch definitions.
8. It creates its own visual element and interaction state.
9. The user configures fields and connects compatible control/data paths.
10. The frontend creates canonical NodeFlowIR models directly.
11. The backend runs NodeFlowIR validation and returns structured diagnostics.

A visual workflow such as `Test Suite → If / Else → Ticket / Report` is therefore discoverable without business-node hard-coding: the Test Suite catalog entry publishes `passed` and `results` data output contracts; `if` publishes a required expression and `true`/`false` control paths; Ticket and Report publish their typed input contracts. The visual edges are an editor projection, while the persisted data bindings and control-flow blocks are IR.

## Relationship to the DSL

The visual builder does not generate DSL. It creates IR directly, alongside the other authoring paths:

```text
Visual Builder ───────────────┐
                              │
NodeFlow DSL → Parser ────────┼──> NodeFlowIR ──> Validation ──> Runtime / Consumer
                              │
AI / structured generation ───┘
```

The DSL is optional textual input/output for the same semantics. Neither catalog metadata nor frontend visual state is a second source of truth.
