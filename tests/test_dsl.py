from __future__ import annotations

import pytest

from nodeflowir.dsl import DSLParseError, DSLValidationError, compile_dsl, format_workflow, parse
from nodeflowir.ir import (
    AggregationExpression,
    CollectionExpression,
    ForeachStep,
    IfStep,
    MatchStep,
    NodeStep,
    ObjectValue,
    ParallelStep,
    RepeatStep,
    ValueKind,
)
from nodeflowir.ir.types import TypeSpec
from nodeflowir.nodes import (
    ConfigurationField,
    NodeDefinition,
    NodeRegistry,
    PortDefinition,
    Select,
)


def _type(kind: ValueKind, **kwargs: object) -> TypeSpec:
    return TypeSpec(kind=kind, **kwargs)


def _registry() -> NodeRegistry:
    result = _type(
        ValueKind.OBJECT,
        fields={
            "id": _type(ValueKind.STRING),
            "name": _type(ValueKind.STRING),
            "status": _type(ValueKind.STRING),
            "severity": _type(ValueKind.INTEGER),
            "passed": _type(ValueKind.BOOLEAN),
        },
    )
    registry = NodeRegistry()
    registry.register(
        NodeDefinition(
            type="qa.test-suite",
            version="1.0",
            config=(
                ConfigurationField(
                    name="suite_id",
                    type=_type(ValueKind.STRING),
                    ui=Select(provider="test_management.suites"),
                ),
            ),
            inputs={"environment": PortDefinition(type=_type(ValueKind.STRING))},
            outputs={
                "passed": PortDefinition(type=_type(ValueKind.BOOLEAN)),
                "results": PortDefinition(type=_type(ValueKind.ARRAY, items=result)),
            },
        )
    )
    registry.register(
        NodeDefinition(
            type="analysis.failure-review",
            version="1.0",
            inputs={"results": PortDefinition(type=_type(ValueKind.ARRAY, items=result))},
            outputs={"summary": PortDefinition(type=_type(ValueKind.STRING))},
        )
    )
    for type_id, inputs in {
        "ticket.create": {"details": _type(ValueKind.STRING)},
        "notification.team": {"message": _type(ValueKind.STRING)},
        "report.create": {"results": _type(ValueKind.ARRAY, items=result)},
        "audit.success": {},
        "health.check": {},
        "result.process": {"title": _type(ValueKind.STRING)},
        "deploy.development": {},
        "deploy.staging": {},
        "deploy.production": {},
    }.items():
        registry.register(
            NodeDefinition(
                type=type_id,
                version="1.0",
                inputs={name: PortDefinition(type=value) for name, value in inputs.items()},
            )
        )
    return registry


def test_compiles_versioned_nodes_config_inputs_and_full_control_flow() -> None:
    source = """
        // This remains a declarative workflow document.
        nodeflow 1.0
        workflow NightlyRegression named "Nightly Regression" version 3 (
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
                    max_delay = 2m
                }
                timeout 30m

            failed = filter(tests.output.results, status == "failed")
            critical = filter(failed, severity >= 3)

            if count(critical) > 5 {
                analysis = run analysis.failure-review with results = critical
                parallel {
                    run ticket.create with details = analysis.output.summary
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
    """

    workflow = compile_dsl(source, _registry())

    assert workflow.workflow_version == 3
    assert workflow.name == "Nightly Regression"
    assert workflow.inputs["environment"].type.kind is ValueKind.STRING
    assert workflow.nodes[0].config == {"suite_id": "suite_123"}
    assert workflow.nodes[0].retry is not None
    assert workflow.nodes[0].retry.delay_seconds == 10
    assert workflow.nodes[0].timeout is not None
    assert workflow.nodes[0].timeout.timeout_seconds == 1800
    assert isinstance(workflow.body.steps[1], IfStep)
    assert isinstance(workflow.body.steps[1].then.steps[1], ParallelStep)
    assert isinstance(workflow.outputs["failed_count"], AggregationExpression)


def test_expression_precedence_collections_objects_and_constants() -> None:
    source = """
        nodeflow 1.0
        workflow ExpressionWorkflow version 2 (environment: String) {
            const threshold: Integer = 5
            tests = run qa.test-suite@1.0 with {
                suite_id = "suite_123"
                environment = input.environment
            }
            eligible = filter(
                tests.output.results,
                status == "failed" or severity >= const.threshold and not passed
            )
            summary = object {
                failed_count = count(eligible)
                environment = input.environment
            }
            if contains(lower(input.environment), "prod") and count(eligible) > const.threshold {
                run ticket.create with details = "escalate"
            } else {
                run audit.success
            }
            output {
                summary = summary
                results = concat(eligible, tests.output.results)
            }
        }
    """

    workflow = compile_dsl(source, _registry())
    condition = workflow.body.steps[1]
    assert isinstance(condition, IfStep)
    assert condition.condition.kind == "logical"
    summary = workflow.outputs["summary"]
    assert isinstance(summary, ObjectValue)
    assert isinstance(summary.fields["failed_count"], AggregationExpression)
    assert workflow.outputs["results"].kind == "composition"


def test_compiles_foreach_repeat_break_continue_and_match() -> None:
    source = """
        nodeflow 1.0
        workflow IterationWorkflow version 1 (environment: String) {
            tests = run qa.test-suite@1.0 with {
                suite_id = "suite_123"
                environment = input.environment
            }
            foreach result in tests.output.results {
                if result.status == "cancelled" {
                    continue
                } else {
                    run result.process with title = result.name
                }
                if result.severity >= 5 {
                    break
                }
            }
            repeat 3 {
                run health.check
            }
            match input.environment {
                case "development" { run deploy.development }
                case "staging" { run deploy.staging }
                case "production" { run deploy.production }
                default { run health.check }
            }
        }
    """

    workflow = compile_dsl(source, _registry())

    assert isinstance(workflow.body.steps[1], ForeachStep)
    assert isinstance(workflow.body.steps[2], RepeatStep)
    assert isinstance(workflow.body.steps[3], MatchStep)
    foreach = workflow.body.steps[1]
    assert isinstance(foreach, ForeachStep)
    assert foreach.body.steps[0].kind == "if"
    assert foreach.body.steps[1].kind == "if"


def test_compiles_supported_operations_and_error_flow() -> None:
    source = """
        nodeflow 1.0
        workflow Operations version 1 (environment: String) {
            tests = run qa.test-suite@1.0
                with { suite_id = "suite_123" environment = input.environment }
                retry 3
                timeout 30s
                on error timeout {
                    run notification.team with message = "test suite timed out"
                }
            if input.environment in ["staging", "production"] and exists(tests.output.passed) {
                run audit.success
            } else {
                run health.check
            }
            output {
                any_failed = any(tests.output.results, status == "failed")
                all_passed = all(tests.output.results, passed == true)
                none_critical = none(tests.output.results, severity >= 5)
                filtered_count = count(tests.output.results, severity >= 3)
                mapped = map(tests.output.results, severity)
                selected = select(tests.output.results, "id", "status")
                picked = pick(tests.output.results, id, name)
                omitted = omit(tests.output.results, "passed")
                renamed = rename(tests.output.results, status, state)
                unique_results = unique(tests.output.results)
                distinct_values = distinct(map(tests.output.results, severity))
                ordered = sort_by(tests.output.results, severity, desc)
                grouped = group_by(tests.output.results, status)
                zipped = zip(tests.output.results, tests.output.results)
                flattened = flatten([[1], [2]])
                joined = join(tests.output.results, tests.output.results, left.id == right.id)
                merged = merge(
                    object { environment = input.environment },
                    object { suite = "nightly" }
                )
                concatenated = concat(tests.output.results, tests.output.results)
                appended = append(tests.output.results, object {
                    id = "new" name = "New" status = "passed" severity = 1 passed = true
                })
                prepended = prepend(tests.output.results, object {
                    id = "first" name = "First" status = "passed" severity = 1 passed = true
                })
                fallback = coalesce(input.environment, "unknown")
                defaulted = default(input.environment, "unknown")
                score = count(tests.output.results) / 2 * 100
                message = trim(upper(" ready "))
                missing_value = tests.output.passed is not null
            }
        }
    """

    workflow = compile_dsl(source, _registry())
    node_step = workflow.body.steps[0]
    assert isinstance(node_step, NodeStep)
    assert node_step.on_error is not None
    assert [category.value for category in node_step.on_error.categories] == ["timeout"]
    assert workflow.nodes[0].retry is not None
    assert workflow.nodes[0].retry.delay_seconds == 0
    assert isinstance(workflow.outputs["filtered_count"], AggregationExpression)
    assert isinstance(workflow.outputs["ordered"], CollectionExpression)
    assert workflow.outputs["joined"].kind == "join"
    formatted = format_workflow(workflow)
    assert "on error timeout {" in formatted
    assert format_workflow(workflow) == formatted
    assert compile_dsl(formatted, _registry()).id == workflow.id


def test_parsing_reports_a_precise_source_location() -> None:
    with pytest.raises(DSLParseError, match=r"Line 3, column"):
        parse(
            """
            nodeflow 1.0
            workflow Broken version 1 { if { run audit.success } }
            """
        )


def test_compilation_runs_existing_ir_validation() -> None:
    source = """
        nodeflow 1.0
        workflow InvalidReference version 1 (environment: String) {
            tests = run qa.test-suite@1.0 with {
                suite_id = "suite_123"
                environment = input.environment
            }
            run ticket.create with details = tests.output.missing
        }
    """
    with pytest.raises(DSLValidationError, match="has no output port 'missing'"):
        compile_dsl(source, _registry())


def test_validation_rejects_break_outside_iteration() -> None:
    source = """
        nodeflow 1.0
        workflow BrokenControl version 1 {
            run audit.success
            break
        }
    """
    with pytest.raises(DSLValidationError, match="only valid inside foreach or repeat"):
        compile_dsl(source, _registry())


def test_formatter_round_trips_a_supported_workflow() -> None:
    source = """
        nodeflow 1.0
        workflow RoundTrip version 4 (environment: String) {
            tests = run qa.test-suite@1.0 with {
                suite_id = "suite_123"
                environment = input.environment
            }
            if any(tests.output.results, severity >= 3) {
                run ticket.create with details = "high"
            } else {
                run audit.success
            }
            output { passed = tests.output.passed }
        }
    """
    registry = _registry()
    workflow = compile_dsl(source, registry)
    formatted = format_workflow(workflow)
    reparsed = compile_dsl(formatted, registry)

    assert formatted.startswith("nodeflow 1.0\n")
    assert reparsed.model_dump(mode="json") == workflow.model_dump(mode="json")
