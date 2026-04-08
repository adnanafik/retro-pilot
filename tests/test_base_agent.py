# tests/test_base_agent.py
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from agents.base_agent import AgentLoop, BaseAgent, LoopOutcome
from tools.registry import Permission, Tool


class SimpleOutput(BaseModel):
    answer: str
    confidence: str = "HIGH"


class EchoTool(Tool):
    @property
    def name(self) -> str: return "echo"
    @property
    def description(self) -> str: return "Echo the input"
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    @property
    def permission(self) -> Permission: return Permission.READ_ONLY
    def execute(self, **kwargs) -> str: return f"echo: {kwargs.get('text', '')}"


def _make_tool_use_block(tool_name: str, tool_id: str, tool_input: dict) -> MagicMock:
    """Build a mock tool_use content block with a real .name string attribute.

    MagicMock(name=...) sets the mock's internal label, not an accessible
    attribute. We must set .name after construction to get the string value.
    """
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = tool_name
    block.input = tool_input
    return block


def make_mock_backend(tool_calls: list[dict] | None = None):
    """Returns a mock LLM backend.

    tool_calls: list of {"name": str, "input": dict} to return on first call.
                Empty list or None → model ends turn immediately.
    """
    backend = MagicMock()

    def side_effect_factory(calls_remaining: list):
        def side_effect(**kwargs):
            if calls_remaining:
                call = calls_remaining.pop(0)
                response = MagicMock()
                response.content = [
                    _make_tool_use_block(call["name"], "tu_1", call["input"])
                ]
                response.stop_reason = "tool_use"
                return response
            else:
                response = MagicMock()
                text_block = MagicMock()
                text_block.type = "text"
                text_block.text = "done"
                response.content = [text_block]
                response.stop_reason = "end_turn"
                return response
        return side_effect

    remaining = list(tool_calls or [])
    backend.complete_with_tools.side_effect = side_effect_factory(remaining)

    # Extraction call (complete, not complete_with_tools)
    backend.complete.return_value = '{"answer": "Redis pool exhausted", "confidence": "HIGH"}'
    return backend


@pytest.mark.asyncio
async def test_loop_end_turn_immediately():
    backend = make_mock_backend(tool_calls=[])
    loop = AgentLoop(
        tools=[EchoTool()],
        backend=backend,
        domain_system_prompt="You are a test agent.",
        response_model=SimpleOutput,
        model="claude-sonnet-4-6",
    )
    result = await loop.run(
        messages=[{"role": "user", "content": "analyse this"}],
        incident_id="INC-001",
    )
    assert result.outcome == LoopOutcome.COMPLETED
    assert result.extracted.answer == "Redis pool exhausted"
    assert result.turns_used == 1


@pytest.mark.asyncio
async def test_loop_executes_tool_then_ends():
    backend = make_mock_backend(
        tool_calls=[{"name": "echo", "input": {"text": "hello"}}]
    )
    loop = AgentLoop(
        tools=[EchoTool()],
        backend=backend,
        domain_system_prompt="You are a test agent.",
        response_model=SimpleOutput,
        model="claude-sonnet-4-6",
    )
    result = await loop.run(
        messages=[{"role": "user", "content": "analyse this"}],
        incident_id="INC-001",
    )
    assert result.outcome == LoopOutcome.COMPLETED
    assert result.turns_used == 2  # 1 tool call turn + 1 end turn


@pytest.mark.asyncio
async def test_loop_respects_max_turns():
    # Always returns a tool call — should hit turn limit
    backend = MagicMock()
    always_tool = MagicMock()
    always_tool.content = [
        _make_tool_use_block("echo", "tu_1", {"text": "x"})
    ]
    always_tool.stop_reason = "tool_use"
    backend.complete_with_tools.return_value = always_tool
    backend.complete.return_value = '{"answer": "partial", "confidence": "LOW"}'

    loop = AgentLoop(
        tools=[EchoTool()],
        backend=backend,
        domain_system_prompt="You are a test agent.",
        response_model=SimpleOutput,
        model="claude-sonnet-4-6",
        max_turns=3,
    )
    result = await loop.run(
        messages=[{"role": "user", "content": "analyse this"}],
        incident_id="INC-001",
    )
    assert result.outcome == LoopOutcome.TURN_LIMIT
    assert result.turns_used == 3


def test_base_agent_name_derived_from_class():
    class MySpecialistAgent(BaseAgent):
        async def run(self, *args, **kwargs): pass
        def describe(self) -> str: return "test"

    agent = MySpecialistAgent()
    assert agent.name == "my_specialist_agent"


@pytest.mark.asyncio
async def test_loop_tool_failure_when_only_tool_errors():
    """All registered tools fail → TOOL_FAILURE outcome."""
    backend = make_mock_backend(
        tool_calls=[{"name": "echo", "input": {"text": "x"}}]
    )
    backend.complete.return_value = '{"answer": "partial", "confidence": "LOW"}'

    class BrokenTool(EchoTool):
        def execute(self, **kwargs) -> str:
            raise RuntimeError("connection refused")

    loop = AgentLoop(
        tools=[BrokenTool()],
        backend=backend,
        domain_system_prompt="test",
        response_model=SimpleOutput,
        model="claude-sonnet-4-6",
    )
    result = await loop.run(
        messages=[{"role": "user", "content": "go"}],
        incident_id="INC-001",
    )
    assert result.outcome == LoopOutcome.TOOL_FAILURE
    assert "echo" in result.failed_tools


@pytest.mark.asyncio
async def test_loop_context_budget_compaction_called():
    """ContextBudget.should_compact is consulted each turn."""
    from unittest.mock import patch

    from shared.context_budget import ContextBudget

    budget = ContextBudget(max_tokens=8192)
    backend = make_mock_backend(tool_calls=[])

    with patch.object(budget, "should_compact", return_value=False) as mock_compact:
        loop = AgentLoop(
            tools=[EchoTool()],
            backend=backend,
            domain_system_prompt="test",
            response_model=SimpleOutput,
            model="claude-sonnet-4-6",
            context_budget=budget,
        )
        await loop.run(
            messages=[{"role": "user", "content": "go"}],
            incident_id="INC-001",
        )
        mock_compact.assert_called_once()
