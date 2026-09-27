# NodeFlow DSL 1.0 language specification

## Purpose and authority

NodeFlow DSL is an optional textual authoring interface for NodeFlowIR. Parsing produces a temporary syntax tree, and compilation produces the existing canonical `Workflow` Pydantic model. The syntax tree is not persisted and has no independent runtime semantics.

```text
NodeFlow DSL → parser → syntax tree → compiler → NodeFlowIR → existing validation
```

The reverse formatter emits the supported NodeFlowIR subset as deterministic DSL. Visual editors can work directly with the IR and do not need to generate DSL.

> **The DSL may only express capabilities that already exist in NodeFlowIR.**

> **If workflow logic can be represented explicitly and deterministically, put it in the IR. If it requires arbitrary custom computation, make it a node.**

There is no embedded Python, JavaScript, shell, user-defined function, `while`, or exception language. Application work is represented by registered node types.

## Lexical rules

- Source is UTF-8 text. Whitespace, including indentation and line breaks, is cosmetic.
- `//` starts a comment that ends at the next line break.
- Strings are double-quoted JSON-style strings; escapes use JSON rules.
- Identifiers match `[A-Za-z_][A-Za-z0-9_.-]*`. Workflow and node instance IDs must also satisfy the corresponding NodeFlowIR identifier constraints during compilation.
- Node type IDs are unquoted namespaced identifiers such as `qa.test-suite` and `ticket.create`.
- Versions are numeric semantic versions such as `1.0` or `1.0.0`. The file header for this release is exactly `nodeflow 1.0`.
- Integer and decimal literals are supported. Duration literals have one of `ms`, `s`, `m`, `h`, or `d`, for example `500ms`, `10s`, `30m`, and `2h`; they compile to the existing seconds-based duration representation.
- Semicolons are not used. Braces and parentheses provide structure.

The reserved words are `nodeflow`, `workflow`, `named`, `version`, `const`, `run`, `with`, `if`, `else`, `match`, `case`, `default`, `foreach`, `in`, `repeat`, `parallel`, `retry`, `timeout`, `on`, `error`, `output`, `object`, `break`, `continue`, `and`, `or`, `not`, `is`, `null`, `true`, and `false`. Function names such as `filter`, `count`, and `exists` are reserved in call position.

## EBNF

This EBNF is the authoritative syntax definition. NodeFlowIR models remain the authoritative semantic definition. Braces make blocks independent of indentation. In the grammar, a repeated assignment sequence may be separated by whitespace and optionally by commas; brace-delimited `with` clauses are preferred when an adjacent deterministic assignment could otherwise be ambiguous.

```ebnf
file                = header, workflow, EOF ;
header              = "nodeflow", language-version ;
language-version    = "1.0" ;
numeric-version     = number, { ".", number } ;

workflow            = "workflow", identifier, [ "named", string ], "version",
                      positive-integer, [ parameters ], block ;
parameters          = "(", [ parameter, { ",", parameter } ], ")" ;
parameter           = identifier, ":", type-name ;
type-name           = identifier ;

block               = "{", { statement }, "}" ;
statement           = constant | assignment | node-run | if-statement | match-statement
                    | foreach-statement | repeat-statement | parallel-statement
                    | "break" | "continue" | output-block ;
constant            = "const", identifier, ":", type-name, "=", literal-value ;
assignment          = identifier, "=", expression ;

node-run            = [ identifier, "=" ], "run", node-type, [ "@", version ],
                      { with-clause | retry-clause | timeout-clause | error-clause } ;
node-type           = identifier ;
version             = numeric-version ;
with-clause         = "with", ( "{", assignments, "}" | assignments ) ;
assignments         = assignment, { [ "," ], assignment } ;
retry-clause        = "retry", ( positive-integer | retry-block ) ;
retry-block         = "{", retry-field, { [ "," ], retry-field }, "}" ;
retry-field         = "attempts", "=", positive-integer
                    | "delay", "=", duration
                    | "backoff", "=", backoff
                    | "max_delay", "=", duration ;
backoff             = "fixed" | "linear" | "exponential" ;
timeout-clause      = "timeout", duration ;
error-clause        = "on", "error", [ error-category, { [ "," ], error-category } ], block ;
error-category      = "failed" | "timeout" | "cancelled" ;

if-statement        = "if", expression, block,
                      { "else", "if", expression, block }, [ "else", block ] ;
match-statement     = "match", expression, "{",
                      case-clause, { case-clause }, [ default-clause ], "}" ;
case-clause         = "case", expression, block ;
default-clause      = "default", block ;
foreach-statement   = "foreach", identifier, "in", expression, block ;
repeat-statement    = "repeat", positive-integer, block ;
parallel-statement  = "parallel", [ "all" | "any" ], block ;
output-block        = "output", "{", assignments, "}" ;

expression          = or-expression ;
or-expression       = and-expression, { "or", and-expression } ;
and-expression      = comparison, { "and", comparison } ;
comparison          = additive, [ comparison-operator, additive ]
                    | additive, "is", [ "not" ], "null" ;
comparison-operator = "==" | "!=" | ">" | "<" | ">=" | "<=" | "in" | "not", "in" ;
additive            = multiplicative, { ( "+" | "-" ), multiplicative } ;
multiplicative      = unary, { ( "*" | "/" | "%" ), unary } ;
unary               = [ "not" | "-" ], primary ;
primary             = literal | reference | list | object | call | "(", expression, ")" ;
reference           = identifier, { ".", identifier } ;
list                = "[", [ expression, { ",", expression } ], "]" ;
object              = "object", "{", [ object-field, { [ "," ], object-field } ], "}" ;
object-field        = ( identifier | string ), "=", expression ;
call                = identifier, "(", [ expression, { ",", expression } ], ")" ;
literal             = string | number | duration | "true" | "false" | "null" ;
literal-value       = literal | static-list | static-object ;
static-list         = "[", [ literal-value, { ",", literal-value } ], "]" ;
static-object       = "object", "{", static-field, { [ "," ], static-field }, "}" ;
static-field        = ( identifier | string ), "=", literal-value ;
```

`positive-integer` is greater than zero. A `retry-block` must contain `attempts` exactly once. A `parallel` block must compile to at least two branches; each direct statement in the block forms one IR branch.

## Workflow declarations and references

Workflow parameters use portable NodeFlowIR type names: `String`, `Integer`, `Number`, `Boolean`, `Array`, `Object`, `Date`, `DateTime`, `Duration`, `Status`, `Null`, and `Any`.

`const` declares a typed, workflow-level JSON literal. It is referenced as `const.name`. Constants must be declared before their textual use. Deterministic assignments are lexical aliases for IR values, not stored variables; assigning `failed = filter(...)` simply lets later source expressions reuse that value tree.

References are explicit and never compiled as code strings:

| DSL form | IR form |
| --- | --- |
| `input.environment` | `WorkflowInputReference(name="environment")` |
| `tests.output.passed` | `NodeOutputReference(node_id="tests", output="passed")` |
| `tests.output.results.status` | node output `results` with path `("status",)` |
| `item.status` inside `foreach item` | `LoopItemReference(loop_id="item", path=("status",))` |
| `const.threshold` | `ConstantReference(name="threshold")` |

For compatibility with output ports named `output`, `tests.output` maps to that exact output port. Otherwise, the first segment after `.output` is the named output port.

## Node execution and policies

`run` creates a `NodeInstance` and a `NodeStep`; an assignment on the left supplies the stable instance ID. An omitted `@version` resolves the latest explicitly registered definition and persists that exact version in the IR.

The compiler uses the registered `NodeDefinition` to classify each `with` assignment:

- A declared configuration field must receive a static JSON literal, list, or `object`; it becomes `NodeInstance.config`.
- A declared input port may use a literal, reference, or deterministic expression; it becomes a `DataConnection`.
- Unknown or ambiguous names are compiler errors.

`retry 3` maps to `RetryPolicy(max_attempts=3, delay_seconds=0, backoff="fixed")`. The braced retry form maps its fields to the same model. `timeout 30m` maps to `TimeoutPolicy(timeout_seconds=1800)`. `on error`, optionally limited to `failed`, `timeout`, and/or `cancelled`, maps to the existing `ErrorFlow`; it does not introduce application exception classes.

## Expressions and precedence

Operators have fixed precedence, highest first:

1. Parentheses, literals, references, lists, objects, and calls.
2. Unary `not` (and a negative numeric literal).
3. `*`, `/`, `%`.
4. `+`, `-`.
5. Comparisons, `in`, `not in`, `is null`, and `is not null`.
6. `and`.
7. `or`.

The compiler maps comparisons, membership, arithmetic, logical expressions, null tests, and string operations directly to the matching IR expression model. Examples:

```text
status == "failed" and severity >= 3
not tests.output.passed
input.environment in ["staging", "production"]
customer.output.email is not null
contains(result.message, "timeout")
lower(name)
```

Supported deterministic calls map to existing IR operations:

- Unary/string: `exists`, `missing`, `lower`, `upper`, `trim`, `length`, `empty`, `not_empty`, `first`, `last`.
- String predicates: `contains`, `starts_with`, `ends_with`, `matches`.
- Collection predicates: `any`, `all`, `none`, `filter`, and filtered `count`.
- Collection transformations: `map`, `select`, `pick`, `omit`, `rename`, `unique`, `sort_by`, `group_by`, `flatten`, and `zip`.
- Aggregations: `count`, `sum`, `avg`, `min`, `max`, and `distinct`. A second `sum`/`avg`/`min`/`max` argument maps the collection first, so `avg(results, duration)` is supported.
- Composition/fallback: `merge`, `concat`, `append`, `prepend`, `coalesce`, and `default`.
- Two-collection predicates: `join(left_collection, right_collection, left.id == right.id)`.

`sort_by(results, severity, desc)` accepts `asc` (default) or `desc`. `select`, `pick`, `omit`, and `rename` accept simple or quoted field names, for example `rename(results, status, state)`. `object { key = value }` maps to `ObjectValue` and list literals map to `ArrayValue`.

Collection predicate and mapper scopes are explicit in the compiled IR. Source may use a bare field name inside a collection call, such as `filter(results, status == "failed")`; the compiler creates a deterministic internal item scope and compiles `status` as a reference to that scope. In a `foreach`, use the declared loop name explicitly, for example `result.status`.

## Control flow and scope

`if` / `else if` / `else`, `match` / `case` / `default`, `foreach`, `repeat`, and `parallel` map one-to-one to their existing structured IR models. `repeat` is statically bounded. `break` and `continue` are syntactically accepted anywhere but rejected by the existing IR validator unless they are inside a `foreach` or `repeat` body. DSL case syntax has no visual identity field, so the compiler creates stable match-local case IDs in source order (`case_1`, `case_2`, ...); parallel branches use their explicit node alias when present or match-local `branch_1`, `branch_2`, ... IDs.

DSL 1.0 intentionally has no `fail` statement or application exception syntax because the current IR has no corresponding generic control-flow construct. A workflow that needs that behavior uses a registered application node in a `case` or `default` block.

Assignments, node aliases, and loop names are lexical. Branch, loop, parallel, and error-flow-local aliases do not escape their block, matching NodeFlowIR's conservative output visibility rules. The compiler deliberately runs existing semantic validation after construction, so unknown node outputs, unavailable branch outputs, incompatible ports, and expression type errors remain authoritative IR diagnostics.

## Formatting and errors

`format_workflow(workflow)` emits stable four-space indentation, double-quoted JSON strings, explicit node versions, braced `with` clauses, and a final newline. It preserves workflow semantics for the supported subset; lexical assignments may be expanded because they do not exist in the IR. An IR feature with no DSL 1.0 spelling raises `DSLFormatError` instead of being silently changed.

Parser and compiler errors include line, column, the relevant source line, and a caret. For example:

```text
Line 12, column 9: expected an expression
    if {
        ^
```

## Complete example

```text
nodeflow 1.0

workflow NightlyRegression version 3 (
    environment: String
) {
    tests = run qa.test-suite@1.0
        with
            suite_id = "suite_123"
            environment = input.environment
        retry {
            attempts = 3
            delay = 10s
            backoff = exponential
        }
        timeout 30m

    failed = filter(tests.output.results, status == "failed")
    critical = filter(failed, severity >= 3)

    if count(critical) > 5 {
        analysis = run analysis.failure-review with results = critical
        parallel {
            run ticket.create with {
                severity = "high"
                details = analysis.output.summary
            }
            run notification.team with message = analysis.output.summary
        }
    } else if any(failed, severity >= 2) {
        run report.create with results = failed
    } else {
        run audit.success
    }

    output {
        passed = tests.output.passed
        failed_count = count(failed)
        critical_count = count(critical)
    }
}
```

The illustrative node identifiers need to be registered by the consuming application. The DSL itself never supplies their business implementation.
