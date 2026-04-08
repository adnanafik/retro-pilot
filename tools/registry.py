"""Tool registry for retro-pilot agent loops.

Central catalog of all available tools with permission-tier filtering.
Agents query the registry to get a scoped tool list matching their
blast-radius ceiling. Execution and confirmation logic stays in AgentLoop.

Permission tiers:
  READ_ONLY, WRITE      — linear watermark: READ_ONLY <= WRITE
  DANGEROUS, REQUIRES_CONFIRMATION — orthogonal; excluded by default,
                                     opt-in via include_dangerous=True
"""
from __future__ import annotations

import abc
from enum import StrEnum
from typing import Any


class Permission(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    DANGEROUS = "dangerous"


_TIER_ORDER: dict[Permission, int] = {
    Permission.READ_ONLY: 0,
    Permission.WRITE: 1,
}


class Tool(abc.ABC):
    """Abstract base for all retro-pilot tools.

    A Tool is a stateless definition object. It declares its name,
    description, input schema, permission level, and execution logic.
    No runtime state is stored — callers pass kwargs at execution time.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @property
    @abc.abstractmethod
    def description(self) -> str: ...

    @property
    @abc.abstractmethod
    def input_schema(self) -> dict[str, Any]: ...

    @property
    @abc.abstractmethod
    def permission(self) -> Permission: ...

    @abc.abstractmethod
    def execute(self, **kwargs) -> str: ...

    def to_api_dict(self) -> dict[str, Any]:
        """Render tool definition in Anthropic tool-use API format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """Central catalog of tools, queryable by permission tier."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get_tools(
        self,
        max_permission: Permission = Permission.READ_ONLY,
        include_dangerous: bool = False,
    ) -> list[Tool]:
        if max_permission not in _TIER_ORDER:
            raise ValueError(
                f"'{max_permission}' is not a valid ceiling permission. "
                f"Use READ_ONLY or WRITE; use include_dangerous=True for "
                f"DANGEROUS and REQUIRES_CONFIRMATION tools."
            )
        max_tier = _TIER_ORDER[max_permission]
        result: list[Tool] = []
        for tool in self._tools.values():
            tier = _TIER_ORDER.get(tool.permission)
            if tier is not None:
                if tier <= max_tier:
                    result.append(tool)
            elif include_dangerous:
                result.append(tool)
        return result

    def get_by_name(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)
