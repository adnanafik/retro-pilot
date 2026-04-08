import json
import os
import tempfile
from pathlib import Path

import pytest

from shared.context_budget import ContextBudget
from shared.state_store import StateStore


def test_context_budget_threshold_validation():
    with pytest.raises(ValueError):
        ContextBudget(max_tokens=8192, compaction_threshold=0.5)


def test_context_budget_should_compact_false_below_threshold():
    budget = ContextBudget(max_tokens=8192)
    messages = [{"role": "user", "content": "short"}]
    assert budget.should_compact(messages) is False


def test_context_budget_compact_replaces_tool_results():
    budget = ContextBudget(max_tokens=100, compaction_threshold=0.60)
    long_content = "x" * 500
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "1",
             "content": long_content, "is_error": False}
        ]},
        {"role": "assistant", "content": [{"type": "text", "text": "found issue"}]},
        # last user message — must NOT be compacted
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "2",
             "content": "recent result", "is_error": False}
        ]},
    ]
    compacted = budget.compact(messages)
    # First user message tool result should be compacted
    assert "compacted" in compacted[0]["content"][0]["content"]
    # Last user message must be preserved
    assert compacted[2]["content"][0]["content"] == "recent result"


def test_state_store_set_and_get():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        store = StateStore(path=path)
        store.set("INC-001", "triage", {"confidence": "HIGH"})
        result = store.get("INC-001", "triage")
        assert result == {"confidence": "HIGH"}
    finally:
        os.unlink(path)


def test_state_store_get_missing_returns_none():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        store = StateStore(path=path)
        assert store.get("INC-999", "missing") is None
    finally:
        os.unlink(path)


def test_state_store_persists_across_instances():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        StateStore(path=path).set("INC-001", "ns", {"key": "val"})
        result = StateStore(path=path).get("INC-001", "ns")
        assert result == {"key": "val"}
    finally:
        os.unlink(path)
