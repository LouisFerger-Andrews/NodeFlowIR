# NodeFlowIR architecture

## Position in an application architecture

NodeFlowIR is the canonical semantic contract between workflow producers and a consuming runtime. A visual graph, a DSL program, and an AI-generated document are authoring adapters. Each must create the same Pydantic `Workflow` document.

```text
Authoring adapters                  Application-owned boundary
──────────────────                  ──────────────────────────
visual builder ─┐
DSL compiler ───┼─> NodeFlowIR ───> validate → application-owned plan / execute custom nodes
AI output ──────┘        │                         │
                          │                         └─ scheduling, state, integrations
                          └─ stable JSON for storage, APIs, and review
```

The governing rule is:

> **If workflow logic can be represented explicitly and deterministically, put it in the IR. If it requires arbitrary custom computation, make it a node.**

The first half prevents normal orchestration logic from being hidden in Python callbacks. The second half keeps the package out of application domains and prevents the IR from becoming a general-purpose language.

The complementary ownership rule is:

> **Node definitions describe capabilities and bindings; consuming applications own dynamic data and executable business logic.**

## Canonical document topology

| Model | Responsibility |
| --- | --- |
| `Workflow` | Versioned root document; inputs, constants, configured nodes, data connections, flow body, and outputs. |
| `NodeDefinition` | Reusable versioned capability contract: inputs, outputs, typed configuration, UI hints, opaque provider/handler references, and metadata. |
| `NodeInstance` | One workflow-local use of an exact node definition version, with static configuration and retry/timeout intent. |
| `DataConnection` | One binding from a tagged value/expression to a named node input. |
| `FlowBlock` | Ordered control-flow tree that places node instances, branches, loops, and parallel blocks. |
| `Value` | Tagged literal, reference, structural value, or deterministic expression tree. |

Input bindings live as `DataConnection` records instead of being duplicated in a node instance and an edge list. Their target identifies `node_id` and input port; their value can be a literal, workflow input, prior node output, loop item, or an arbitrarily nested bounded transformation. Consequently, a node-to-node connection remains explicit even when an expression transforms the output before passing it on.

Node definitions and node instances are intentionally separate. Definitions are reusable contracts; instances are workflow-specific configuration. A definition may name an execution handler, but it stores no callable implementation. It may also name a dynamic option provider for a configuration field, but it stores no application data.

## Node SDK and application bindings

The SDK lets an application declare a definition with normal Python classes or fully typed functions. A class field marked with `ConfigField` becomes a typed configuration field; a Pydantic input model provides workflow input ports; an output model provides output ports. The result is a `NodeDefinition`, optionally added to an explicit in-memory `NodeRegistry`.

```python
@node(
    id="qa.test-suite",
    version="1.0",
    handler="test_management.run_suite",
    input_model=SuiteInputs,
)
class TestSuiteNode:
    suite_id: str = ConfigField(ui=Select(provider="test_management.suites"))
    output = TestSuiteResult
```

`suite_id` is configuration selected before execution. It is distinct from `SuiteInputs`, whose workflow data arrives through `DataConnection` records, and from `TestSuiteResult`, which describes produced values. The class is never instantiated or executed by NodeFlowIR as part of registration or validation.

`ConfigurationField` supports a portable type, requiredness, default, description, bounded constraints, and a frontend-neutral widget hint. Supported hints are text, number, boolean, select, multi-select, secret, textarea, and code. These are metadata rather than rendering instructions.

Provider and handler identifiers are stable application-owned strings. `ProviderRegistry` explicitly maps a provider identifier to a sync or async function that returns stable `ProviderOption(value, label)` records. The backend invokes it when it wants fresh choices; static IR validation does not invoke it. `ExecutionHandlerRegistry` explicitly maps a handler identifier to application code, but intentionally offers only registration and lookup—not execution.

```text
Definition field UI                    Execution binding
───────────────────                    ─────────────────
provider "test_management.suites"      handler "test_management.run_suite"
             │                                      │
             ▼                                      ▼
backend provider registry               backend handler registry
             │                                      │
             ▼                                      ▼
fresh value/label options               application-owned business function
             │
             ▼
frontend stores selected stable value in a NodeInstance
```

The Test Management application may add or remove suites at any time. Its provider returns the current choices, such as `{"value": "suite_123", "label": "Regression Suite"}`. Workflows persist only `"suite_123"`; neither the node definition nor its version changes when labels or available suites change.

## Optional NodeFlow DSL

NodeFlow DSL is an authoring adapter, not a second workflow representation. Its parser produces a temporary syntax tree, and its compiler uses the application-provided `NodeRegistry` to create the same `Workflow`, `NodeInstance`, `DataConnection`, `FlowBlock`, and expression models used by visual or structured-IR authoring.

```text
NodeFlow DSL → lexer/parser → temporary syntax AST → compiler → NodeFlowIR → validate_workflow
NodeFlowIR → deterministic formatter → NodeFlow DSL
```

The governing language rule is:

> **The DSL may only express capabilities that already exist in NodeFlowIR.**

The parser is independent of application contracts. The compiler is intentionally registry-aware: it must distinguish a `with` assignment to a static node configuration field from a workflow data input, and it persists a resolved node definition version. The existing semantic validator then remains responsible for type compatibility, output visibility, control-flow scope, and node contract validation.

Source assignments are lexical aliases for deterministic IR values. They are expanded during compilation rather than stored as a new runtime variable model. Collection predicates likewise compile into existing collection expressions with an explicit generated item scope. This preserves the canonical rule that there are no executable source strings in the IR.

The formatter is deliberately conservative. It uses a stable braces-based form and raises an error for an IR construct that DSL 1.0 cannot express instead of silently changing semantics. The [language specification](language-spec.md) defines EBNF, lexical rules, precedence, and mapping details.

## Values and types

Every value has a discriminating `kind`. References are structured models rather than source-code strings:

```text
workflow input    → { kind: "workflow_input", name, path? }
prior node output → { kind: "node_output", node_id, output, path? }
foreach item      → { kind: "loop_item", loop_id, path? }
constant          → { kind: "constant", name, path? }
```

`TypeSpec` is a portable recursive descriptor. It supports scalar JSON-like types, arrays, structured objects, date/datetime, duration, generic execution status, nullability, and allowed scalar values. Type descriptors belong to node ports, workflow inputs/constants, and typed literals. They are deliberately independent of consuming applications' Python classes and schemas.

An expression is a typed tree, not an evaluator. Its vocabulary is closed and serializable: unary/string/null operations, binary comparison/membership/arithmetic/date operations, boolean trees, range checks, collections, aggregations, composition, joins, fallback, and explicit conversion. A consuming runtime may implement the semantics, but it cannot need to interpret arbitrary user code.

## Control-flow and scope semantics

The flow is a structured tree rather than a UI graph API:

- `if` supports `then`, ordered `else_if`, and `else_body`.
- `match` supports typed case values and an optional default.
- `foreach` binds a named item scope over an array value.
- `repeat` is statically bounded; there are no unbounded loops.
- `break` and `continue` are valid only inside `foreach` or `repeat`.
- `parallel` has named branches and an explicit `all` or `any` convergence strategy.
- A `NodeStep` can define a generic failed/timeout/cancelled `on_error` path.

Only nodes earlier in the same lexical sequence are visible to a later expression. Branch, loop, error, and parallel bodies receive their enclosing scope but do not implicitly export node outputs to the enclosing block. This conservative rule eliminates ambiguous conditional/fan-out result semantics. A future construct that exposes a converged value must name and type that output explicitly rather than relying on accidental graph reachability.

## Validation boundary

`validate_workflow` is a non-executing semantic pass. Against the application-provided `NodeRegistry`, it checks:

- node contract/version lookup, node placement, required ports, duplicate bindings, and node-instance configuration fields (requiredness, unknown values, types, constraints, and enums);
- reference existence, field paths, lexical node availability, and active loop scopes;
- value-to-port assignability, typed literals, expression/operator legality, collection shape, aggregation, and conversion compatibility;
- condition/match types, bounded-loop structure, break/continue placement, parallel branch names, and error-flow categories;
- Pydantic model constraints for schema/workflow versions and retry/timeout declarations.

Validation intentionally does not execute a node, resolve a UI provider, confirm a dynamic option is currently available, invoke a handler, or determine infrastructure capabilities. Those require application context outside the generic IR. Configuration rules declared in a generic `NodeDefinition` are validated; any additional application schema is not.

## Versioning, ownership, and serialization

`schema_version` identifies the NodeFlowIR document format and is currently exactly `"1.0"`. `workflow_version` is a positive integer revision of one workflow. They are independent: updating a workflow revision does not imply an IR migration.

The JSON entrypoint serializes the Pydantic model directly. When loading a different schema version, the caller must supply an explicit `MigrationRegistry` path. The package never silently coerces an incompatible document into the current format.

The schema-1.0 `Workflow.id` is the stable workflow-document identity and has
the explicit Python alias `workflow_id`. `WorkflowRevision` records an
immutable revision identity and optional lineage, while `RevisionPrecondition`
is the portable optimistic-concurrency expectation a consumer compares against
its stored current version. Neither model stores revision history or mutates a
workflow.

Access policy and execution policy deliberately remain separate from a
semantic workflow revision. `SubjectReference`, `WorkflowAccessPolicy`, and
`ExecutionIdentityPolicy` describe opaque sharing and run-as intent; a
consumer may change access state without changing the workflow logic revision.
An `executor` grant can be expressed separately from viewer/editor grants.
NodeFlowIR neither resolves a subject nor makes a permission decision.

Node configuration fields can be annotated with `ResourceFieldContract`. The
pure `collect_resource_dependencies` helper derives stable
`ResourceDependency` records from registered definitions and configured IDs.
It performs no provider calls, resource lookups, or authorization checks. See
[access and versioning](access-and-versioning.md) for the full boundary.

## Ownership boundary

NodeFlowIR owns generic IR semantics, contracts, configuration metadata and UI hints, provider/handler references and explicit registries, references, transformations, control flow, validation, and serialization.

Consuming applications own domain node implementations, registry composition, dynamic provider implementations and authorization/freshness policy, handler invocation, runtime/evaluator behavior, retries and timeout enforcement, error-state persistence, scheduler policy, identity, authorization, tenancy, APIs, UI, infrastructure, and integrations. This includes QA test execution, tickets, SAP, agents, databases, and Kubernetes.

> **NodeFlowIR can describe ownership, revision identity, sharing intent, resource dependencies, and execution authorization requirements; the consuming application owns identity, persistence, authorization decisions, and enforcement.**

The deployment boundary is therefore deliberately one-way:

```text
NodeFlowIR → consuming backend → application API → frontend
```

The frontend consumes backend-exposed definition metadata, provider options, and validation diagnostics; it does not need this Python package.

## Visual builder catalog boundary

`WorkflowCatalog` merges catalog entries for built-in IR constructs with registered custom node definitions, without collapsing their different semantics into one executable-node abstraction. A consuming backend serializes this frontend-neutral document through its own API; the frontend uses configuration schemas and structural ports to author the canonical IR directly.

```text
built-in IR capabilities ─┐
                          ├─> WorkflowCatalog ─> consuming backend API ─> visual builder
registered node contracts ┘                                      │
                                                                    └─> NodeFlowIR → validation
```

Catalogs describe semantic kind/type, configuration field contracts, portable data types, control/data ports, cardinality, dynamic branch rules, and framework-neutral presentation metadata. A `visual_mode` separates canvas primitives from nested configuration capabilities; canvas entries select a small generic renderer vocabulary instead of a frontend type-specific component. Catalogs do not describe a visual style, component library, coordinate system, or layout. Dynamic configuration fields keep only an application provider identifier, and node definitions keep only an optional handler identifier; resolving live options and executing business code remain application-owned concerns.

See [the visual builder catalog contract](catalog-contract.md) for serialization, context-aware references, ports, branch metadata, and the frontend authoring sequence; see [the presentation contract](presentation-contract.md) for generic renderer metadata.

## Shared AI authoring contract

> **All workflow authors—visual, DSL, and AI—operate against the same capabilities, contracts, IR schema, and validation rules.**

`AuthoringContext` reuses the same `WorkflowCatalog` exposed to a visual builder and supplements it with the canonical Pydantic `Workflow` schema plus only the provider values that an application explicitly supplies for the current request. It is an integration payload, not an AI runtime and not another workflow representation.

```text
WorkflowCatalog + canonical Workflow schema + supplied provider values
                              │
                              ▼
                      AuthoringContext
                              │
                              ▼
                 application-owned AI / structured output
                              │
                              ▼
                         NodeFlowIR Workflow
                              │
                              ▼
                    existing validate_workflow rules
```

Static validation remains non-executing. An optional `validate_authored_workflow` wrapper can check select/multi-select stable IDs only when current provider options have explicitly been included in context; it never resolves providers itself. See [the shared authoring context](authoring-context.md) for the API, schema, diagnostics, filtering, and Test Management example.

## Consumer integration facade

`NodeFlow` is an explicit, instance-local facade for consuming backends. It owns isolated existing node, provider, handler, and migration registries; delegates catalog construction, canonical loading, validation, DSL compilation/formatting, and authoring-context construction; and resolves a registered handler for an exact `NodeInstance` version without invoking it.

```text
NodeFlow → catalog / validate / DSL / authoring context / provider lookup / handler lookup
                                                                    │
                                                                    ▼
                                                     application-owned runtime execution
```

The facade intentionally has no scheduler, execution state, evaluator, input-resolution implementation, event loop, persistence, or API layer. Workflow definitions describe what should happen; an application runtime combines a validated node instance with its own concrete inputs and invokes the resolved handler under its own policy. See [the consumer integration guide](consumer-integration.md) for startup and handoff details.

## Compatibility, bounded input, and revision inspection

The IR imposes intentionally generous structural limits to reject pathological
untrusted documents cleanly: at most 1,000 nodes, 5,000 data connections,
1,000 steps per block, 256 match/parallel branches, 256 configuration fields
per node instance, 10,000 items in a constructed array, and 64 nested model/
document levels. These are input-safety limits, not scheduling or execution
limits; consuming applications may impose stricter local policy.

`check_workflow_compatibility` is a read-only preflight for explicit schema
migrations, registered node contract versions, and an optional catalog protocol
version. It deliberately stops before full semantic validation. The canonical
validator remains the one authority for workflow meaning.

`workflow_fingerprint` derives a deterministic SHA-256 digest from semantic
workflow data only, while `workflow_diff` provides structured revision changes
for application-owned history/audit experiences. `Deprecation` metadata lets a
registered node remain loadable while clients stop offering it for new authoring.
These contracts add no revision store, permission engine, workflow executor, or
application-specific behavior. See [compatibility and revision tools](compatibility.md).
