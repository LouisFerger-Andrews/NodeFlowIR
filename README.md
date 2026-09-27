# NodeFlowIR

NodeFlowIR is a reusable Python library that defines the canonical, typed Intermediate Representation (IR) for node-based workflows. It is the contract between workflow producers and consuming runtimes—not a workflow engine, visual builder, or application runtime.

> **If workflow logic can be represented explicitly and deterministically, put it in the IR. If it requires arbitrary custom computation, make it a node.**

> **NodeFlowIR defines workflow semantics and structural contracts; consuming applications own execution and infrastructure.**

This boundary gives visual builders, DSLs, and AI-generated workflows one predictable semantic target without turning NodeFlowIR into a general-purpose programming language. Built-in logic is structural, bounded, typed, serializable, and inspectable. Domain work—running tests, creating tickets, calling APIs, or invoking agents—remains in application-owned nodes.

```text
Visual Builder ─┐
                 │
DSL ─────────────┼──> NodeFlowIR ──> Validation ──> Runtime / Consumer
                 │
AI / PydanticAI ─┘
```

Pydantic v2 models make the IR suitable for structured-output generation, including future PydanticAI integrations, without coupling the package to PydanticAI.

> **Node definitions describe capabilities and bindings; consuming applications own dynamic data and executable business logic.**

## Public API

For normal backend integration, import the deliberately small top-level entry points:

```python
from nodeflowir import NodeDefinition, NodeFlow, NodeInstance, Workflow, node
```

`NodeFlow` is the recommended integration facade. `Workflow`, `NodeInstance`, and the Node SDK declarations remain available for direct canonical IR and contract construction. Specialist public APIs are grouped by concern—such as `nodeflowir.catalog`, `nodeflowir.dsl`, `nodeflowir.authoring`, `nodeflowir.serialization`, and `nodeflowir.validation`—rather than requiring imports from implementation modules. The shared Pydantic base model and other implementation details are intentionally not top-level API.

## Canonical workflow semantics

A `Workflow` is a versioned document with:

- `schema_version`: the NodeFlowIR document format version (`"1.0"` today).
- `workflow_version`: a positive integer revision of this workflow, independent of the schema format.
- Declared workflow inputs and typed literal constants.
- A catalog of configured node instances.
- Explicit data connections that bind a value/expression to a node input port.
- An ordered, structured control-flow `body`.
- Optional named output values.

Node instance IDs are unique. A `NodeStep` places an instance in the control-flow tree exactly once. Node output references are available only after their node has appeared earlier in the same lexical sequence. Outputs from conditional branches, loops, and parallel branches do not silently escape their scope; a future IR addition must model any such fan-in result explicitly.

This makes control and data flow independent of any frontend graph library. A visual editor may project the model as a graph, but its graph is not authoritative.

## Node Definition vs Node Instance

A **Node Definition** is a reusable, versioned contract. It declares a stable type ID, typed input and output ports, typed configuration fields, frontend-neutral UI hints, optional provider and handler references, and metadata. It contains no credentials, provider values, provider implementation, or business logic.

```python
NodeDefinition(
    type="qa.test-suite",
    version="1.0.0",
    inputs={"repository": PortDefinition(type=TypeSpec(kind="string"))},
    outputs={"results": PortDefinition(type=TypeSpec(kind="array", items=...))},
)
```

A **Node Instance** is a workflow-local configured use of one exact definition version. It has an ID, type/version reference, optional label, static configuration, and declarative retry/timeout policy. Its input bindings are workflow `DataConnection` records whose targets name the instance and input port. This makes every input source explicit and avoids duplicating a node-output reference in two representations.

```json
{
  "id": "run-tests",
  "type": "qa.test-suite",
  "type_version": "1.0.0",
  "label": "Run nightly regression suite",
  "retry": {"max_attempts": 3, "delay_seconds": 5, "backoff": "exponential"},
  "timeout": {"timeout_seconds": 900}
}
```

The consuming application owns contract registration and the callable implementation. The SDK can derive a contract from a fully typed function, but never executes it:

```python
from pydantic import BaseModel

from nodeflowir import NodeRegistry, node


class TestSuiteResult(BaseModel):
    results: list[dict]


registry = NodeRegistry()


@node("qa.test-suite", version="1.0.0", registry=registry)
async def run_test_suite(
    repository: str,
) -> TestSuiteResult: ...  # Application-owned implementation.
```

For a node with static user configuration, a concise class declaration separates configuration from data inputs and outputs:

```python
from pydantic import BaseModel

from nodeflowir import ConfigField, NodeRegistry, Select, node


class SuiteInputs(BaseModel):
    repository: str


class TestSuiteResult(BaseModel):
    passed: bool
    results: list[str]


registry = NodeRegistry()


@node(
    id="qa.test-suite",
    version="1.0",
    display_name="Test Suite",
    category="Quality Assurance",
    handler="test_management.run_suite",
    input_model=SuiteInputs,
    registry=registry,
)
class TestSuiteNode:
    suite_id: str = ConfigField(
        description="Stable Test Management suite ID.",
        ui=Select(provider="test_management.suites"),
    )
    output = TestSuiteResult
```

Here `suite_id` is configuration selected before the workflow runs; `repository` is a workflow data input; and `passed` / `results` are values produced by the node. The declaration is serializable metadata, not an implementation of Test Management.

## Providers, bindings, and frontend metadata

UI metadata is descriptive only. `text`, `number`, `boolean`, `select`, `multi_select`, `secret`, `textarea`, and `code` widgets are portable hints a frontend may use; NodeFlowIR renders none of them. A select field can name a dynamic provider instead of embedding changing business data in the definition.

```text
Node definition
  suite_id → provider "test_management.suites"
                         ↓
Consuming backend resolves fresh options → frontend renders a dropdown
                         ↓
User selects stable value "suite_123" → node instance stores that value
```

The application registers the provider implementation and chooses when to call it (normally while a user configures a node):

```python
from nodeflowir import ProviderRegistry


providers = ProviderRegistry()
providers.register("test_management.suites", get_available_test_suites)

# The backend may expose these JSON-compatible options through its own API.
options = await providers.options("test_management.suites")
# (ProviderOption(value="suite_123", label="Regression Suite"), ...)
```

Provider options always contain a stable `value` and a user-facing `label`. Static workflow validation checks the configuration's declared type and constraints, but deliberately does not invoke a dynamic provider or assert that a value currently exists. This lets the backend apply authorization, tenancy, and freshness rules at the appropriate time.

Similarly, a definition's `handler` is an opaque reference. `ExecutionHandlerRegistry` can bind it to consuming-application code, but exposes no execution API:

```text
NodeFlowIR node definition
  handler "test_management.run_suite"
                         ↓
Consuming backend handler registry
                         ↓
Application-owned run_suite implementation
```

The consuming runtime decides invocation context, retries, isolation, error persistence, and timeout enforcement. NodeFlowIR never calls a handler.

## Test Management example

The preceding `qa.test-suite` definition declares this generic contract:

- Configuration: `suite_id` (string), rendered as a select using `test_management.suites`.
- Workflow input: `repository` (string).
- Outputs: `passed` (boolean) and `results` (array of strings).
- Handler reference: `test_management.run_suite`.

The Test Management application module implements both named references: `test_management.suites` returns the current selectable suites, and `test_management.run_suite` contains the real execution code. NodeFlowIR only stores the references. A user-created instance therefore persists only the stable identifier:

```json
{
  "id": "nightly_regression",
  "type": "qa.test-suite",
  "type_version": "1.0",
  "config": {
    "suite_id": "suite_123"
  }
}
```

Adding a new Test Management suite changes the provider's live result, not the node definition or existing workflow documents.

## NodeFlow DSL

NodeFlow DSL is an optional, braces-based text interface to the canonical IR. It is useful for advanced users and tooling, but it is not a second workflow model: text is parsed into a temporary syntax tree, compiled into `Workflow`, and passed through the existing validator.

```text
NodeFlow DSL → Parser → syntax tree → NodeFlowIR → Validation
NodeFlowIR → Formatter → NodeFlow DSL
```

> **The DSL may only express capabilities that already exist in NodeFlowIR.**

Visual builders can work directly with the IR and do not need to generate DSL. AI tooling may eventually generate either form, though structured IR generation remains preferable where possible.

```text
nodeflow 1.0

workflow NightlyRegression version 3 (environment: String) {
    tests = run qa.test-suite@1.0
        with {
            suite_id = "suite_123"
            environment = input.environment
        }
        retry 3
        timeout 30m

    failed = filter(tests.output.results, status == "failed")

    if any(failed, severity >= 3) {
        run ticket.create with details = failed
    }

    output {
        passed = tests.output.passed
        failed_count = count(failed)
    }
}
```

Compile against the consuming backend's node registry, then format a supported workflow deterministically when text is needed:

```python
from nodeflowir.dsl import compile_dsl, format_workflow

workflow = compile_dsl(source, registry)  # Includes existing IR validation.
formatted = format_workflow(workflow)
```

The language has no embedded programming language or unrestricted loops. `with` fields are classified by the registered node contract: static JSON values become node configuration, while values for node input ports become explicit data connections. See [the language specification](docs/language-spec.md) for EBNF, precedence, scoping, supported deterministic operations, and precise DSL-to-IR mapping rules.

## Values, references, and transformations

Every data binding carries an explicit tagged value model. There are no executable Python snippets or arbitrary expression strings in the IR.

- Literals, typed constants, structured objects, and arrays.
- References to workflow inputs, node outputs (including a typed field path), and a named current `foreach` item.
- Nested unary, binary, logical, range, fallback, conversion, collection, aggregation, composition, and join expressions.

The portable type system includes null, string, integer, number, boolean, array, object, date, datetime, duration, status, and scalar allowed-value sets. Durations are represented as non-negative seconds in JSON. Conversions are explicit; validation does not apply loose implicit coercion.

The expression vocabulary is deliberately bounded. It includes comparisons; `and`/`or`/`not`; null/existence tests; string operators; membership; arithmetic; date/datetime comparisons and duration arithmetic; `coalesce`/`default`; object and array construction; and explicit conversions.

For stable JSON, comparison tokens are named rather than symbolic: `eq`, `ne`, `gt`, `lt`, `gte`, and `lte` represent `==`, `!=`, `>`, `<`, `>=`, and `<=` respectively.

Collection expressions cover `any`, `all`, `none`, filtered `count`, `filter`, `map`, `select`/`pick`, `omit`, `rename`, `distinct`/`unique`, `first`, `last`, `length`, `empty`, `not_empty`, `flatten`, `zip`, `sort_by`, and `group_by`. Aggregations cover `sum`, `avg`, `min`, `max`, `count`, and `distinct`. Composition includes `merge`, `concat`, `append`, `prepend`, and a predicate-based `join`.

## Control flow and declarative policies

`FlowBlock` provides an ordered control-flow tree with node steps, `if` / `else_if` / `else`, `match`, bounded `foreach`, bounded `repeat`, `break`, `continue`, and declarative `parallel` branches. A parallel block has an explicit `all` or `any` convergence strategy. `NodeStep.on_error` can attach a generic failed/timeout/cancelled error path.

`RetryPolicy` describes maximum attempts, delay, fixed/linear/exponential backoff, and optional maximum delay. `TimeoutPolicy` describes a positive timeout in seconds. NodeFlowIR represents this intent; a consumer runtime decides how to enforce it.

## Illustrative workflow

The following is a shortened but concrete fragment of a workflow that runs a test suite, checks whether any result is both failed and severe, counts the failed tests, and takes a branch. The full model is structural JSON, not a code string.

```json
{
  "schema_version": "1.0",
  "workflow_version": 12,
  "id": "nightly-tests",
  "name": "Nightly Tests",
  "nodes": [
    {"id": "run-tests", "type": "qa.test-suite", "type_version": "1.0.0"},
    {"id": "create-ticket", "type": "tickets.create", "type_version": "1.0.0"},
    {"id": "create-report", "type": "reports.create", "type_version": "1.0.0"}
  ],
  "connections": [
    {
      "target": {"node_id": "run-tests", "port": "repository"},
      "value": {"kind": "literal", "value": "service-api"}
    },
    {
      "target": {"node_id": "create-ticket", "port": "failed_count"},
      "value": {
        "kind": "aggregation",
        "operator": "count",
        "collection": {"kind": "node_output", "node_id": "run-tests", "output": "results"},
        "item_scope": "test",
        "predicate": {
          "kind": "logical",
          "operator": "and",
          "operands": [
            {
              "kind": "binary", "operator": "eq",
              "left": {"kind": "loop_item", "loop_id": "test", "path": ["status"]},
              "right": {"kind": "literal", "value": "failed"}
            },
            {
              "kind": "binary", "operator": "gte",
              "left": {"kind": "loop_item", "loop_id": "test", "path": ["severity"]},
              "right": {"kind": "literal", "value": 3}
            }
          ]
        }
      }
    }
  ],
  "body": {
    "steps": [
      {"kind": "node", "node_id": "run-tests"},
      {
        "kind": "if",
        "condition": {
          "kind": "collection", "operator": "any",
          "collection": {"kind": "node_output", "node_id": "run-tests", "output": "results"},
          "item_scope": "test",
          "predicate": {"kind": "logical", "operator": "and", "operands": ["…same predicates…"]}
        },
        "then": {"steps": [{"kind": "node", "node_id": "create-ticket"}]},
        "else_body": {"steps": [{"kind": "node", "node_id": "create-report"}]}
      }
    ]
  }
}
```

The abbreviated predicate marker above is for readability only; a persisted document always contains the full nested value objects. [The tested Python construction](tests/test_workflow_validation.py) shows the complete equivalent IR.

## Validation and JSON

`validate_workflow(workflow, registry)` returns structured diagnostics without executing a node. It validates registered definition versions; required, unknown, typed, constrained, and enumerated configuration values; required bindings; unknown nodes/ports/outputs; value paths; type compatibility; expression/operator applicability; collection and aggregation constraints; explicit conversion legality; loop scope/control; branch structure; and retry/timeout model constraints. It never invokes provider or handler bindings.

JSON serialization is deterministic and human-inspectable:

```python
from nodeflowir import validate_workflow
from nodeflowir.serialization import workflow_from_json, workflow_to_json

validation = validate_workflow(workflow, registry)
validation.raise_for_errors()

document = workflow_to_json(workflow)
round_tripped = workflow_from_json(document)
```

Loading a different `schema_version` requires a registered explicit migration. A workflow revision changing from 12 to 13 does not require an IR schema migration.

## Visual Builder Integration Contract

NodeFlowIR can build a frontend-neutral `WorkflowCatalog` that combines registered application nodes with the built-in IR constructs already supported by the package.

```text
NodeFlowIR
    ↓ Unified Workflow Catalog
Consuming Backend
    ↓ application API
Frontend Visual Builder
```

> **NodeFlowIR defines semantics and structural contracts; the frontend defines presentation and interaction.**

The catalog lets a backend expose a dynamic “add workflow element” menu without frontend code knowing every node type or built-in operation in advance. Its entries have a semantic kind/type, display metadata, a configuration schema, typed data/control ports, requiredness, cardinality, and (where necessary) dynamic branch definitions. It intentionally has no colors, icons, coordinates, dimensions, or frontend-framework concepts.

```python
from nodeflowir import build_workflow_catalog

catalog = build_workflow_catalog(node_registry=registry)
payload = catalog.model_dump(mode="json")
```

Built-in entries include the implemented control flow, expressions, collections, transformations, aggregations, values/references, and declarative execution policies. Registered nodes appear alongside them as `kind: "node"` entries. For example, a `qa.test-suite` configuration field using `Select(provider="test_management.suites")` is exposed as a `dynamic_select` field with that provider identifier—not with a frozen list of Test Management suites.

Configuration field types are semantic rather than merely primitive. In addition to literal values and enums, the catalog describes expressions, references, node-output references, collection references, field references, objects, lists, durations, dynamic selects, and multi-selects. This allows an editor to offer a structured selector such as “Test Suite → Results → status” and persist a typed NodeFlowIR reference/expression, not arbitrary source text. Reference metadata marks context-sensitive sources such as earlier node outputs; backend validation remains authoritative for scope and type correctness.

Ports define only permitted structural connections. Every executable node has reserved `$control.in` / `$control.out` ports for its generic `NodeStep` placement, alongside its declared data inputs and outputs. `if` has one incoming control port, `true` and `false` control outputs, and a required expression condition. `foreach` exposes `each` and `completed`; `parallel` and `match` explicitly declare dynamic branch outputs and their branch constraints. `ports_are_compatible(source, target)` provides an optional local control/data and portable-type check, while `validate_workflow` remains the final semantic check.

The normal frontend sequence is:

1. Request the catalog from the consuming backend.
2. Build the element menu from its categories and entries.
3. Render the selected item's configuration schema and request fresh dynamic provider values when needed.
4. Create the frontend's own visual element from the port and branch contracts.
5. Persist the user's structured configuration, bindings, and control flow as NodeFlowIR directly.
6. Submit the IR to the backend for validation.

The frontend does not import this package, execute handlers, or generate DSL. A visual shape such as `Test Suite → If / Else → Ticket / Report` is a projection of catalog metadata and canonical IR structure; its appearance and interaction design remain entirely frontend-owned. See [the visual builder catalog contract](docs/catalog-contract.md) for the complete API-neutral contract.

## Authoring Consistency

> **All workflow authors—visual, DSL, and AI—operate against the same capabilities, contracts, IR schema, and validation rules.**

There is no AI-specific workflow model, node registry, DSL intermediate form, or validator. Visual authoring creates canonical IR directly; the optional DSL compiles into it; structured AI output should create the same `Workflow` Pydantic model directly.

```text
                     Unified Workflow Catalog
                    /            |            \
                   /             |             \
            Visual UI        NodeFlow DSL        AI
                 │                 │              │
                 └───────── canonical NodeFlowIR ─┘
                                      │
                                 Validation
```

`AuthoringContext` is a framework-neutral, serializable payload for an application-owned AI system. It combines the existing `WorkflowCatalog`, the canonical `Workflow` JSON Schema, and only the current dynamic provider values that the backend chooses to supply. It does not resolve providers, run a model, call a handler, or add PydanticAI as a dependency.

```python
from nodeflowir import Workflow, build_workflow_catalog
from nodeflowir.authoring import build_authoring_context, validate_authored_workflow

catalog = build_workflow_catalog(node_registry=registry)
context = build_authoring_context(
    catalog=catalog,
    provider_values={
        "test_management.suites": [
            {"value": "suite_123", "label": "Regression Suite"},
        ]
    },
)

# Application-owned PydanticAI (or another structured-output system):
# agent = Agent(..., output_type=Workflow)

result = validate_authored_workflow(workflow, registry=registry, context=context)
result.raise_for_errors()
```

The same Test Suite definition therefore appears in visual and AI capability discovery. The frontend can request current suites for a dropdown; an application can give the same stable value/label options to an AI authoring request. Both persist only `"suite_123"` in the canonical node configuration. `validate_authored_workflow` always delegates static checks to `validate_workflow`; supplied provider values merely enable an optional dynamic stable-ID check. Errors serialize with `code`, `message`, `path`, `expected`, and `received` fields to support correction loops.

For the complete integration boundary, structured schema guidance, filtering, and Test Management example, see [the shared authoring context](docs/authoring-context.md).

## Consumer Integration

> **NodeFlowIR defines workflow semantics and structural contracts; consuming applications own execution and infrastructure.**

`NodeFlow` is the recommended thin, explicit integration entry point. Each instance composes isolated existing node, provider, handler, and migration registries—there is no module-level registration state and no workflow execution.

```python
from nodeflowir import NodeFlow

flow = NodeFlow()
flow.register_node(TestSuiteNode)  # A class/function already declared with @node.
flow.register_node(CreateTicketNode)
flow.register_provider("test_management.suites", get_available_suites)
flow.register_handler("test_management.run_suite", run_suite)

catalog = flow.build_catalog()
workflow = flow.load_workflow(workflow_payload)  # Parses, migrates if configured, validates.

context = flow.build_authoring_context(
    provider_values={"test_management.suites": current_suites},
)

handler = flow.resolve_handler(workflow.nodes[0])
# Calling handler, resolving runtime values, scheduling, and persistence are application-owned.
```

`flow.nodes`, `flow.providers`, and `flow.handlers` expose the established explicit registries when an application needs their lower-level behavior. The facade also exposes `parse_dsl`, `format_dsl`, `validate`, `validate_authored_workflow`, and async `resolve_provider`; each delegates to the existing canonical subsystem. It never resolves every provider automatically, invokes a handler, creates an event loop, or executes a workflow.

See [the consumer integration guide](docs/consumer-integration.md) for startup, diagnostics, visual/DSL/AI entry points, handler resolution, and the execution-handoff boundary.

## Repository boundaries

NodeFlowIR owns generic workflow semantics: models, portable types, node contracts, configuration and UI metadata, provider/handler binding references and explicit registries, data references and transformations, control-flow declarations, validation, JSON serialization, and schema-migration plumbing.

Consuming applications own custom node implementations, integration code, dynamic provider implementations and their resolution policy, handler invocation, execution planning, scheduling, persistence, databases, APIs, tenancy, authentication, RBAC, observability, and infrastructure such as Kubernetes. NodeFlowIR neither executes nodes nor calls external systems.

```text
NodeFlowIR
    ↓ contracts, metadata, validation
Consuming Backend
    ↓ application API
Frontend
```

The frontend does not import this Python package. Its backend exposes registered node metadata, fresh provider options, and validation results through an application-owned API.

## Development with Nix

Nix provides the reproducible development shell; `pyproject.toml` remains the normal Python package contract.

```bash
nix develop
uv sync --extra dev
uv run pytest
uv run ruff check .
```

The flake provides Python 3.12, `uv`, Ruff, Pyright, and Git. A normal Python consumer can install the package with its preferred installer once it is published.

## Project structure

```text
nodeflowir/
├── ir/
│   ├── values.py        # Tagged values, references, and expression vocabulary
│   ├── control_flow.py  # Structured flow blocks and declarative error paths
│   ├── workflow.py      # Top-level document, inputs, constants, outputs
│   ├── node.py          # Configured node instances and retry/timeout policies
│   └── edge.py          # Explicit data connections to node input ports
├── nodes/               # SDK, contracts, config/UI fields, registries, bindings
├── catalog/             # Unified frontend-facing built-in and custom-node metadata
├── authoring/           # Shared structured context and optional dynamic validation overlay
├── integration.py        # Explicit consumer facade composing existing subsystems
├── dsl/                 # Lexer, parser, syntax AST, compiler, deterministic formatter
├── validation/          # Semantic type/reference/control-flow validation
└── serialization/       # JSON entrypoints and explicit schema migrations
docs/
├── architecture.md
├── authoring-context.md
├── catalog-contract.md
├── consumer-integration.md
└── language-spec.md
tests/
```

## Current Implementation

This repository currently implements:

- Pydantic v2 models for schema-versioned workflows and independently versioned workflow revisions.
- Versioned node contracts, configured node instances, an explicit in-memory registry, and a class/function Node SDK.
- Typed configuration fields with defaults, portable constraints, enum support, and frontend-neutral UI metadata.
- Explicit dynamic-option provider and execution-handler registries. Providers return stable value/label metadata; handlers can only be registered and resolved, never executed by NodeFlowIR.
- A serializable unified workflow catalog for built-in IR constructs and registered custom node definitions, including semantic configuration fields, typed control/data ports, dynamic branch metadata, and local port-compatibility checks.
- A framework-neutral shared authoring context that reuses the unified catalog and canonical `Workflow` JSON Schema, accepts explicitly supplied dynamic provider options, supports catalog filtering, and optionally validates selected provider IDs through the existing validation result model.
- An explicit, instance-local `NodeFlow` integration facade for registration, catalog discovery, canonical workflow loading/validation, DSL and authoring access, provider lookup, and non-executing handler resolution.
- Static node-instance validation against registered definitions, including configuration field names, required values, types, constraints, enums, node versions, and workflow input ports.
- An optional NodeFlow DSL 1.0 with a location-aware parser, temporary syntax tree, compiler to canonical IR, existing semantic validation, and deterministic formatter for the supported subset.
- Typed literals, constants, workflow/node/loop references, typed field paths, structured object/array construction, and a bounded serializable expression vocabulary.
- Typed collection transforms, aggregation, data composition, fallback, conversion, date/datetime/duration operations, and allowed-value sets.
- Structured `if`, `match`, `foreach`, bounded `repeat`, loop control, parallel convergence, generic error paths, retry declarations, and timeout declarations.
- Non-executing semantic validation and deterministic JSON round trips with explicit schema migration support.
- A flake-based development shell and unit tests for workflow semantics.

It does **not** implement PydanticAI integration, a visual builder, a node executor, provider or handler business implementations, scheduler, persistence layer, application APIs, frontend, Kubernetes integration, arbitrary embedded programming languages, or business-specific nodes.

For design rationale and exact ownership boundaries, see [the architecture note](docs/architecture.md).
