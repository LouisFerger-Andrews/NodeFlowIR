from pydantic import BaseModel

from nodeflowir import NodeRegistry, node
from nodeflowir.ir import ValueKind


class SuiteResult(BaseModel):
    passed: bool
    duration_seconds: float


def test_node_decorator_derives_and_registers_a_contract() -> None:
    registry = NodeRegistry()

    @node("qa.test-suite", registry=registry)
    async def run_test_suite(suite_id: str, retry: int = 0) -> SuiteResult:
        raise NotImplementedError

    definition = registry.resolve("qa.test-suite", "1.0.0")

    assert run_test_suite.__nodeflowir_definition__ == definition
    assert definition.inputs["suite_id"].required
    assert not definition.inputs["retry"].required
    assert definition.inputs["suite_id"].type.kind is ValueKind.STRING
    assert definition.outputs["passed"].type.kind is ValueKind.BOOLEAN
