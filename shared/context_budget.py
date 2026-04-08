"""Context budget management for AgentLoop.

Tracks estimated token usage and compacts message history when approaching
the context limit. Strategy A: replace processed tool_result bodies with
compact stubs — the model's interpretations in assistant turns are preserved.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MIN_THRESHOLD = 0.60
_MAX_THRESHOLD = 1.0


class ContextBudget:
    def __init__(self, max_tokens: int = 8192, compaction_threshold: float = 0.75) -> None:
        if not (_MIN_THRESHOLD <= compaction_threshold <= _MAX_THRESHOLD):
            raise ValueError(
                f"compaction_threshold must be in [{_MIN_THRESHOLD}, {_MAX_THRESHOLD}], "
                f"got {compaction_threshold}"
            )
        self._max_tokens = max_tokens
        self._threshold = compaction_threshold
        self._trigger_at = int(max_tokens * compaction_threshold)

    def should_compact(self, messages: list[dict]) -> bool:
        return self._estimate_tokens(messages) >= self._trigger_at

    def compact(self, messages: list[dict]) -> list[dict]:
        last_user_idx: int | None = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_idx = i
                break

        compacted: list[dict] = []
        for i, msg in enumerate(messages):
            if msg.get("role") != "user" or i == last_user_idx:
                compacted.append(msg)
                continue
            content = msg.get("content", "")
            if not isinstance(content, list):
                compacted.append(msg)
                continue
            new_content: list[dict] = []
            for block in content:
                if (isinstance(block, dict) and block.get("type") == "tool_result"
                        and not block.get("is_error")):
                    raw_chars = len(str(block.get("content", "")))
                    new_content.append({
                        **block,
                        "content": (
                            f"[compacted: {raw_chars} chars of tool output — "
                            "key findings extracted in subsequent assistant turn]"
                        ),
                    })
                else:
                    new_content.append(block)
            compacted.append({**msg, "content": new_content})
        return compacted

    @staticmethod
    def _estimate_tokens(messages: list[dict]) -> int:
        def _count(obj: object) -> int:
            if isinstance(obj, str):
                return len(obj)
            if isinstance(obj, dict):
                return sum(_count(v) for v in obj.values())
            if isinstance(obj, list):
                return sum(_count(i) for i in obj)
            return 0
        return _count(messages) // 4
