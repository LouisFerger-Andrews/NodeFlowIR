# Shared workflow authoring context

## One authoring contract

> **All workflow authors—visual, DSL, and AI—operate against the same capabilities, contracts, IR schema, and validation rules.**

NodeFlowIR has one canonical workflow model: `Workflow`. A visual builder creates that model directly; the optional DSL parses and compiles into it; a structured-output system should produce it directly. None of those paths has an author-specific workflow model, node registry, or validator.

```text
Visual Builder ───────────────┐
                              │
NodeFlow DSL → Compiler ──────┼──> NodeFlowIR Workflow ──> Validation
                              │
AI / structured output ───────┘
```

The shared `WorkflowCatalog` is the capability source for both visual and AI authoring:

```text
registered custom nodes ─┐
                         ├─> WorkflowCatalog ─┬─> visual builder
built-in IR constructs ──┘                     └─> authoring context → AI system
```

If a node or construct is absent from the catalog, it is not available to either author. A new registered node appears in both places through the same catalog build.

Catalog presentation metadata is intentionally ignored by structured authoring: it helps a visual builder choose generic renderers, but it is not part of the canonical `Workflow` schema and does not alter AI or DSL semantics.

## `AuthoringContext`

`AuthoringContext` is a Pydantic model intended to be serialized, passed as dependency/context data, or otherwise supplied to an application-owned structured author. It contains:

- the NodeFlowIR schema version and the canonical `Workflow.model_json_schema()` validation schema;
- a `WorkflowCatalog`, including registered node contracts and built-in constructs;
- explicitly supplied current provider options, keyed by the stable provider reference; and
- machine-readable constraints that restate the existing validation boundary.

It does not contain an LLM, prompt, conversation history, model settings, credentials, handler implementation, or provider implementation.

```python
from nodeflowir import build_workflow_catalog
from nodeflowir.authoring import build_authoring_context

catalog = build_workflow_catalog(node_registry=node_registry)
context = build_authoring_context(
    catalog=catalog,
    provider_values={
        "test_management.suites": [
            {"value": "suite_123", "label": "Regression Suite"},
            {"value": "suite_456", "label": "Smoke Tests"},
        ]
    },
)

payload = context.model_dump(mode="json")
```

`provider_values` is deliberately an input rather than a registry lookup. The consuming application decides which providers are relevant to an authoring request, resolves them under its authorization and freshness policy, and supplies only those results. Provider values not referenced by the chosen catalog are rejected, which catches stale or unrelated context data.

`categories` and `item_ids` can filter the catalog before it is included in context:

```python
focused = build_authoring_context(
    catalog=catalog,
    categories=("Testing", "Logic"),
    provider_values=current_options,
)
```

Filtering limits context size; it does not invent a retrieval system or change which workflow features exist.

## Structured output and schema

`workflow_json_schema()` returns the ordinary Pydantic validation schema for `Workflow`. The schema includes the existing `kind` discriminators for control-flow steps and values, as well as finite enums for operators, retry strategies, sort directions, and other bounded vocabulary.

References remain structured in generated output. For example, a test result collection is represented as a node-output reference, not as the DSL string `tests.output.results`:

```json
{
  "kind": "node_output",
  "node_id": "tests",
  "output": "results"
}
```

The DSL may display compact reference syntax, but it is not an intermediate form for AI authoring.

An application using PydanticAI (or another structured-output framework) owns the agent and gives it the canonical `Workflow` type:

```python
# Consuming application code; NodeFlowIR does not depend on pydantic-ai.
from pydantic_ai import Agent

from nodeflowir import Workflow
from nodeflowir.authoring import build_authoring_context

context = build_authoring_context(catalog=catalog, provider_values=provider_values)
agent = Agent(..., output_type=Workflow)

# The application supplies `context` through its own prompt/dependency design,
# then validates the resulting Workflow as shown below.
```

## Validation and correction data

Every generated workflow first uses the established static validator:

```python
from nodeflowir.authoring import validate_authored_workflow

result = validate_authored_workflow(workflow, registry=node_registry)
result.raise_for_errors()
```

That is the same `validate_workflow` pass used by visual and DSL workflows. It checks registered node types and versions, configuration, references, lexical visibility, expression semantics, control flow, and port type compatibility. The authoring helper does not maintain a separate rule set.

When current provider options are explicitly available, pass the context (or a provider-value mapping) to opt into dynamic selection checks:

```python
result = validate_authored_workflow(
    workflow,
    registry=node_registry,
    context=context,
)
```

This checks selected `select`/`multi_select` stable IDs against the supplied options. It does not call a provider. Missing provider data simply leaves that optional dynamic check out, so loading and static validation never depend on external systems.

Diagnostics serialize as structured `code`, `message`, `path`, `expected`, and `received` fields. For example, a stale suite ID produces an `invalid_dynamic_provider_value` issue at `("nodes", 0, "config", "suite_id")`, with the rejected stable ID in `received`. Existing callers may continue to read the compatibility `location` property.

## Test Management example

Suppose the application has registered `qa.test-suite@1.0`, whose `suite_id` configuration field uses the `test_management.suites` provider, and has registered `ticket.create@1.0`. The application supplies the current suite choices above.

For the request “Run the Regression Suite. If any result fails, create a ticket,” a structured author can produce a `Workflow` with:

- a `qa.test-suite` node instance configured with the stable ID `"suite_123"`;
- a structured `node_output` reference to that node's `results` output;
- the built-in `any` collection expression with an explicit loop-item scope and `status == "failed"` predicate; and
- an `if` whose true branch contains the registered `ticket.create` node.

The suite label is useful authoring context only. The persisted node configuration contains `"suite_123"`, so renamed labels or newly added suites do not require a node-definition change. NodeFlowIR does not execute the test suite, create the ticket, call a provider, or call an AI model.
