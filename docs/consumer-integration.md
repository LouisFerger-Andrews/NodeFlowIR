# Consumer integration

## Purpose and boundary

`NodeFlow` is the thin, application-local integration facade for NodeFlowIR. It composes the existing node, provider, handler, and migration registries; it does not replace any of them and has no global state.

> **NodeFlowIR defines and validates what a workflow means. The consuming application decides when and how it is executed.**

```text
                         NodeFlowIR
                             │
                      Integration API
                             │
       ┌──────────────┬──────┴──────┬──────────────┐
       ↓              ↓             ↓              ↓
    Catalog          DSL        AI Context      Validation
       │              │             │              │
       └──────────────┴──────┬──────┴──────────────┘
                             ↓
                     Canonical Workflow
                             ↓
                     Handler Resolution
                             ↓
                   Consuming Application
                             ↓
                    Actual Execution
```

The consuming application owns HTTP APIs, persistence, authentication, authorization, tenancy, scheduling, execution state, node invocation, infrastructure, and all business code. `NodeFlow` does not create an event loop, execute a handler, resolve node inputs from runtime state, or perform a side effect.

## Application startup

Create one explicit facade for an application environment, register its contracts and bindings, then use that instance at application boundaries. Separate instances are isolated, which keeps tests and multiple application environments independent.

```python
from nodeflowir import NodeFlow

flow = NodeFlow()

# These application-owned classes/functions were declared with @node earlier.
flow.register_node(TestSuiteNode)
flow.register_node(CreateTicketNode)

flow.register_provider("test_management.suites", get_available_suites)
flow.register_handler("test_management.run_suite", run_suite)
flow.register_handler("ticketing.create", create_ticket)
```

`register_node` also accepts an explicit `NodeDefinition`. A class or function must already have been decorated with `@node`; the facade does not infer contracts or execute declarations at startup.

The usual lifecycle is:

```text
application starts
      ↓
create NodeFlow instance
      ↓
register application node definitions, providers, and handlers
      ↓
serve catalog / receive canonical workflows from visual UI, DSL, or AI
      ↓
validate canonical IR
      ↓
application scheduler or runtime decides whether and when to execute
```

## Catalog and visual authoring

The facade exposes the existing unified catalog exactly as other APIs do:

```python
catalog = flow.build_catalog()
payload = catalog.model_dump(mode="json")
```

It contains built-in IR constructs plus registered application nodes, configuration metadata, data/control ports, provider references, and dynamic branch rules. A backend serializes `payload` through its own API; NodeFlowIR does not implement that API. See [the visual builder catalog contract](catalog-contract.md) for rendering and graph-authoring details.

Provider resolution is explicit and async-compatible:

```python
options = await flow.resolve_provider("test_management.suites")
# (ProviderOption(value="suite_123", label="Regression Suite"), ...)
```

The application selects when to make this call and supplies authorization, tenancy, or edit context through `ProviderContext` where needed. No provider is refreshed in the background or resolved while building a catalog.

## Canonical workflow loading and validation

`load_workflow` accepts canonical JSON text/bytes, a JSON-compatible document, or an existing `Workflow`. It applies configured explicit migrations, parses the canonical Pydantic model, and runs the existing semantic validator:

```python
from nodeflowir import WorkflowValidationError

try:
    workflow = flow.load_workflow(workflow_payload)
except WorkflowValidationError as error:
    diagnostics = error.result.model_dump(mode="json")
    # Return or persist structured diagnostics in an application-owned API.
```

Pydantic parse errors and migration errors retain their native structured exceptions. A `WorkflowValidationError` specifically represents a structurally valid canonical workflow that failed the established NodeFlowIR semantics. `flow.validate(workflow)` returns the same `ValidationResult` directly when an application wants to handle valid and invalid workflows without raising.

Canonical storage remains independent of NodeFlowIR consumers:

```python
document = workflow.model_dump(mode="json")
# The application stores document wherever it chooses.
```

## DSL and structured authoring

The DSL still compiles to the same canonical model:

```python
workflow = flow.parse_dsl(source)
source = flow.format_dsl(workflow)
```

AI/structured authoring receives the same currently registered capabilities as the visual builder:

```python
context = flow.build_authoring_context(
    provider_values={
        "test_management.suites": current_suites,
    },
)

# Application-owned PydanticAI or another structured-output system produces Workflow.
result = flow.validate_authored_workflow(
    workflow,
    authoring_context=context,
)
```

Building authoring context never resolves providers. The backend explicitly selects and supplies only the current provider values relevant to the request. The static part of `validate_authored_workflow` is the normal validator; context merely enables optional stable provider-ID checks.

> **All workflow authors—visual, DSL, and AI—operate against the same capabilities, contracts, IR schema, and validation rules.**

## Handler resolution and execution handoff

The facade resolves the exact handler binding for an exact node instance version:

```python
handler = flow.resolve_handler(node_instance)
```

```text
NodeInstance (qa.test-suite@1.0)
        ↓
NodeDefinition.handler (test_management.run_suite)
        ↓
application handler registry
        ↓
registered application callable
```

`resolve_handler` returns the callable but does not call it. It raises `NodeHandlerResolutionError` when the definition has no handler reference or the referenced application handler is not registered. The consuming runtime chooses its invocation policy:

```python
# Application runtime code, intentionally outside NodeFlowIR:
# resolved_inputs = runtime_state.resolve_for(node_instance)
# result = await handler(resolved_inputs, node_instance.config)
```

There are three deliberately separate layers:

1. **Workflow definition** — the canonical `Workflow` says what should happen. NodeFlowIR owns this layer.
2. **Execution handoff** — an application combines a validated instance, its static configuration, and values resolved from its own runtime state. NodeFlowIR supplies contracts and handler lookup but does not prescribe state shape or evaluation timing.
3. **Application runtime** — schedules, resolves values, calls handlers, persists results/errors, and enforces retries/timeouts. The consuming application owns this layer.

Input references and deterministic expressions are already explicit in IR. Turning them into concrete values requires workflow inputs, prior node results, loop state, and runtime policy, so NodeFlowIR intentionally provides no premature `resolve_node_inputs` implementation. This preserves the no-execution boundary while leaving a clean handoff point for a future application runtime adapter.
