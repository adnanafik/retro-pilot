"""Base agent class and AgentLoop for retro-pilot.

Every agent extends BaseAgent and implements run() and describe().
AgentLoop is the generic tool-use engine — it runs until end_turn,
max_turns, or tool failure, then does a separate extraction call to
convert conversation history into a typed Pydantic model.
"""
from __future__ import annotations

import abc
import json
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from shared.context_budget import ContextBudget
from tools.registry import Tool

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMBackend(Protocol):
    """Interface that all LLM backends must satisfy."""

    def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
        model: str,
        max_tokens: int,
    ) -> object: ...

    def complete(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
    ) -> str: ...


class LoopOutcome(StrEnum):
    COMPLETED    = "completed"
    TURN_LIMIT   = "turn_limit"
    TOOL_FAILURE = "tool_failure"


@dataclass
class LoopResult(Generic[T]):
    outcome: LoopOutcome
    extracted: T
    turns_used: int
    failed_tools: list[str] = field(default_factory=list)
    last_assistant_text: str = ""


def _loop_footer(schema_json: str) -> str:
    return f"""

When you have gathered enough evidence, stop calling tools and end your turn.
After you stop, your full conversation will be passed to an extraction step that
converts it into the following JSON schema. Reason toward this shape in your analysis:

{schema_json}

Do not produce JSON yourself — just end your turn when your analysis is complete.
"""


class AgentLoop(Generic[T]):
    """Generic tool-use loop engine.

    Runs until:
      COMPLETED   — model ends turn with no tool calls
      TURN_LIMIT  — max_turns reached
      TOOL_FAILURE — every registered tool errored

    After exit, a second extraction call converts history → typed T instance.
    """

    def __init__(
        self,
        tools: list[Tool],
        backend: LLMBackend,
        domain_system_prompt: str,
        response_model: type[T],
        model: str,
        max_turns: int = 10,
        max_tokens: int = 4096,
        context_budget: ContextBudget | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in tools}
        self._backend = backend
        self._response_model = response_model
        self._model = model
        self._max_turns = max_turns
        self._max_tokens = max_tokens
        self._context_budget = context_budget

        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        self._system = domain_system_prompt + _loop_footer(schema_json)

    async def run(
        self,
        messages: list[dict],
        incident_id: str = "",
    ) -> LoopResult[T]:
        history = list(messages)
        failed_tools: list[str] = []
        _failed_set: set[str] = set()
        last_text = ""

        for turn in range(self._max_turns):
            logger.debug("AgentLoop turn %d/%d", turn + 1, self._max_turns)

            if self._context_budget and self._context_budget.should_compact(history):
                history = self._context_budget.compact(history)

            raw = self._backend.complete_with_tools(
                messages=list(history),
                tools=[t.to_api_dict() for t in self._tools.values()],
                system=self._system,
                model=self._model,
                max_tokens=self._max_tokens,
            )

            text_blocks = [b for b in raw.content if b.type == "text"]
            tool_uses = [b for b in raw.content if b.type == "tool_use"]

            if text_blocks:
                last_text = " ".join(b.text for b in text_blocks)

            # Append full assistant message
            assistant_content: list[dict] = []
            for b in text_blocks:
                assistant_content.append({"type": "text", "text": b.text})
            for b in tool_uses:
                assistant_content.append({
                    "type": "tool_use", "id": b.id,
                    "name": b.name, "input": b.input,
                })
            history.append({"role": "assistant", "content": assistant_content})

            if not tool_uses:
                extracted = self._extract(history)
                return LoopResult(
                    outcome=LoopOutcome.COMPLETED,
                    extracted=extracted,
                    turns_used=turn + 1,
                    failed_tools=failed_tools,
                    last_assistant_text=last_text,
                )

            # Execute tools and collect results
            tool_results: list[dict] = []
            for tu in tool_uses:
                tool = self._tools.get(tu.name)
                if tool is None:
                    content = f"Unknown tool: {tu.name}"
                    is_error = True
                    failed_tools.append(tu.name)
                    _failed_set.add(tu.name)
                else:
                    try:
                        content = tool.execute(**tu.input)
                        is_error = False
                    except Exception as exc:
                        content = f"Tool error ({type(exc).__name__}): {exc}"
                        is_error = True
                        failed_tools.append(tu.name)
                        _failed_set.add(tu.name)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": content,
                    "is_error": is_error,
                })

            history.append({"role": "user", "content": tool_results})

            # If every registered tool has failed, abort
            if _failed_set >= set(self._tools):
                extracted = self._extract(history)
                return LoopResult(
                    outcome=LoopOutcome.TOOL_FAILURE,
                    extracted=extracted,
                    turns_used=turn + 1,
                    failed_tools=failed_tools,
                    last_assistant_text=last_text,
                )

        # Turn limit
        extracted = self._extract(history)
        return LoopResult(
            outcome=LoopOutcome.TURN_LIMIT,
            extracted=extracted,
            turns_used=self._max_turns,
            failed_tools=failed_tools,
            last_assistant_text=last_text,
        )

    def _extract(self, history: list[dict]) -> T:
        """Second extraction call: convert full history → typed T."""
        schema_json = json.dumps(self._response_model.model_json_schema(), indent=2)
        prompt = (
            "Based on the investigation above, extract the findings into valid JSON "
            f"matching this schema:\n{schema_json}\n\nRespond with JSON only."
        )
        raw_json = self._backend.complete(
            system="You extract structured findings from agent conversations into JSON.",
            user=prompt,
            model=self._model,
            max_tokens=2048,
        )
        # Strip markdown code fences if present
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_json.strip(), flags=re.MULTILINE)
        return self._response_model.model_validate_json(cleaned)


class BaseAgent(abc.ABC):
    """Abstract base for all retro-pilot agents.

    Subclasses implement run() and describe(). The AgentLoop is constructed
    inside run() with the agent's specific tools and system prompt.
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, backend: LLMBackend | None = None, model: str | None = None) -> None:
        self.backend = backend
        self.model = model or self.DEFAULT_MODEL

    @abc.abstractmethod
    async def run(self, *args, **kwargs): ...

    @abc.abstractmethod
    def describe(self) -> str: ...

    @property
    def name(self) -> str:
        cls = type(self).__name__
        return re.sub(r"(?<!^)(?=[A-Z])", "_", cls).lower()
