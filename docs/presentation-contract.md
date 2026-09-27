# Frontend presentation contract

## Purpose

The `WorkflowCatalog` is both a semantic discovery contract and a compact presentation contract for a consuming visual builder. It lets a frontend hard-code a small set of reusable renderer primitives instead of individual workflow type IDs.

> **Workflow types must not be hard-coded into the frontend. NodeFlowIR provides semantic and presentation metadata; the frontend implements a small reusable vocabulary of generic renderers.**

> **The frontend should hard-code renderer primitives, not workflow types.**

NodeFlowIR provides structural meaning, a `visual_mode`, presentation metadata, ports, branch rules, configuration contracts, and behavior flags. The frontend decides the shape, colors, icons-library mapping, dimensions, layout, interactions, and animations.

```text
NodeFlowIR
    ↓
Unified Workflow Catalog
    ↓
Presentation Contract
    ↓
Consuming Backend API
    ↓
Frontend Generic Renderer Registry
```

## Presentation metadata and visual mode

Every visible catalog item has a `presentation` object:

```json
{
  "name": "If / Else",
  "category": "Logic",
  "description": null,
  "renderer": "branch",
  "icon": "git-branch",
  "search_terms": ["condition", "branch", "decision"]
}
```

`renderer` is required only for items whose `visual_mode` is `canvas`. The supported canvas renderer vocabulary is intentionally small:

| Renderer | Current use |
| --- | --- |
| `standard` | Registered executable node definitions. |
| `branch` | Two-way `if` / `else`. |
| `switch` | Dynamic-case `match`. |
| `loop` | `foreach` and bounded `repeat`. |
| `parallel` | Declarative fan-out/fan-in. |
| `terminal` | `break` and `continue` inside a loop. |

`visual_mode` classifies where a capability is authored:

| Mode | Meaning |
| --- | --- |
| `canvas` | A palette item rendered with `presentation.renderer`. |
| `configuration` | A discoverable capability for a generic expression, value, policy, or nested-flow editor—not an independent persisted canvas node. |
| `hidden` | Reserved for a future capability that must be serialized but not offered to a visual author. |

This distinction follows the canonical IR. Control-flow steps and node instances have independent workflow structure, so they are canvas elements. Operators, values, aggregations, transformations, retry, timeout, and attached error flow are expression/configuration structures in the IR, so they are exposed to generic editors rather than incorrectly modeled as independent graph nodes.

Icon identifiers such as `git-branch`, `flask-conical`, and `repeat-2` are semantic strings. A frontend maps them to its chosen icon library and falls back to the renderer's default icon when an optional icon is absent. NodeFlowIR never supplies SVG, image assets, CSS, or framework components.

## Generic renderer flow

A frontend can build its palette and element controls without workflow-type conditionals:

```text
GET workflow catalog
        ↓
Filter visual_mode = canvas
        ↓
Group by presentation.category
        ↓
Display presentation.name + presentation.icon
        ↓
User adds an item
        ↓
Select presentation.renderer
        ↓
Generate handles from port metadata
        ↓
Generate configuration from configuration_schema
```

The renderer registry can therefore be as small as:

```text
standard, branch, switch, loop, parallel, terminal
```

For example, the catalog says that `if` uses `branch` and exposes `true` / `false` control roles. The frontend can decide that branch renderers are diamond-shaped and where those handles appear; it never needs a condition such as `item.type === "if"`.

## Ports, branches, and behavior

Ports remain semantic. A `CatalogPort` describes `id`, `label`, control/data kind, direction, cardinality, portable data type, requiredness, and whether an output is dynamic. It does not contain visual coordinates.

Control ports additionally provide a semantic `role`:

| Role | Example |
| --- | --- |
| `entry` | An incoming control path. |
| `true` / `false` | The two fixed `if` outputs. |
| `case` / `default_case` | Dynamic and default `match` outputs. |
| `each` / `completed` | Loop body and completion paths. |
| `branch` | A dynamic `parallel` fan-out path. |
| `error` | The nested handler path of attached error flow. |
| `default` | A normal continuation path. |

`BranchDefinition` describes dynamic control paths without type-specific frontend logic. It includes whether branches are dynamic, minimum/maximum counts, optional per-branch configuration, default-branch support, a human label template, and a deterministic `branch_id_template` such as `case_{index}` or `branch_{index}`.

The actual created identifiers are persisted in canonical IR, not inferred from layout order:

- `ParallelStep.branches` contains `ParallelBranch(id=...)` records.
- `MatchStep.cases` contains `MatchCase(id=...)` records; the default branch is structurally named `default` by the catalog.
- The DSL compiler deterministically creates local `case_1`, `case_2`, and `branch_1`, `branch_2` identifiers when text does not otherwise declare a stable branch identity.

Canonical JSON preserves those IDs exactly. DSL is a semantic text interface rather than a visual-layout format, so formatting an independently authored workflow may normalize branch identities to the deterministic DSL IDs; visual applications preserve their exact branch identity by storing canonical IR.

`behavior` contains generic flags used by renderers and editors: `supports_retry`, `supports_timeout`, `supports_error_path`, `supports_dynamic_branches`, `supports_nested_content`, `supports_multiple_control_inputs`, and `terminal`. These are presentation/interaction aids only; validation still determines workflow validity.

## Configuration and policies

`configuration_schema` remains the source of generic form controls. It distinguishes literals, expressions, references, node-output and collection references, dynamic selects, lists, objects, durations, and portable type specifications. Provider identifiers remain declarative; the frontend asks its backend for fresh options when it opens a dynamic select.

All normal executable custom nodes advertise `supports_retry`, `supports_timeout`, and `supports_error_path`. A frontend can therefore expose generic Retry, Timeout, and Error Path configuration sections from behavior flags. `retry`, `timeout`, and `error_flow` remain configuration capabilities because they attach to an existing node invocation rather than creating independent executable nodes.

## Custom nodes

Registered node definitions automatically become `canvas` items using the `standard` renderer. Their category defaults to `General`, their display name defaults to the stable type ID when absent, and their icon is optional. A consuming application can add concise presentation discovery hints through the Node SDK:

```python
@node(
    id="qa.test-suite",
    version="1.0",
    display_name="Test Suite",
    category="Testing",
    icon="flask-conical",
    search_terms=("quality", "regression"),
    handler="test_management.run_suite",
)
class TestSuiteNode: ...
```

No React component is needed for this normal custom node. Existing generic `standard` rendering, configuration-schema controls, and typed port handling are sufficient.

Deprecated canvas items remain fully described for existing workflows, but
`catalog.palette_items()` excludes them from a new-item palette. This lets a
frontend display migration guidance from `item.deprecation` without hard-coding
type IDs or abruptly hiding historical workflow elements.

## Boundary with other authoring paths

Presentation metadata is not part of `Workflow` and does not affect validation, DSL compilation, or structured AI authoring. The same catalog remains the shared capability source, but presentation serves only visual consumers.

```text
                     Workflow Catalog
                    /                \
                   /                  \
        Presentation metadata       Semantic contracts
                 ↓                        ↓
           Visual builder       Visual, DSL, and AI authors
```

The visual builder creates canonical NodeFlowIR directly. It does not generate DSL, persist presentation state in workflows, or execute handlers.
