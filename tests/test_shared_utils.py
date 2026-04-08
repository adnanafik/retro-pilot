import json
import os
import tempfile

import pytest

from shared.config import RetroPilotConfig, load_config
from shared.context_budget import ContextBudget
from shared.state_store import StateStore
from shared.tenant_context import SlidingWindowRateLimiter
from shared.trust_context import AuditLog, ExplanationGenerator


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


# --- AuditLog tests ---

def test_audit_log_creates_jsonl_file(tmp_path):
    log = AuditLog(base_dir=tmp_path)
    log.record(
        incident_id="INC-001", tool_name="get_logs",
        inputs={"service": "auth"}, result="ok"
    )
    files = list(tmp_path.glob("audit-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["incident_id"] == "INC-001"
    assert entry["tool"] == "get_logs"


def test_audit_log_result_truncated_at_200(tmp_path):
    log = AuditLog(base_dir=tmp_path)
    log.record(
        incident_id="INC-001", tool_name="t",
        inputs={}, result="x" * 500
    )
    files = list(tmp_path.glob("audit-*.jsonl"))
    entry = json.loads(files[0].read_text().strip())
    assert len(entry["result_preview"]) == 200


def test_audit_log_appends_not_overwrites(tmp_path):
    log = AuditLog(base_dir=tmp_path)
    log.record(incident_id="INC-001", tool_name="t1", inputs={}, result="r1")
    log.record(incident_id="INC-001", tool_name="t2", inputs={}, result="r2")
    files = list(tmp_path.glob("audit-*.jsonl"))
    lines = files[0].read_text().strip().splitlines()
    assert len(lines) == 2


# --- ExplanationGenerator tests ---

def test_explanation_generator_demo_mode_returns_stub(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    gen = ExplanationGenerator()
    result = gen.explain("get_logs", {"service": "auth"}, "INC-001")
    assert "[DEMO]" in result
    assert "get_logs" in result


def test_explanation_generator_no_backend_returns_stub():
    gen = ExplanationGenerator(backend=None)
    result = gen.explain("save_postmortem", {}, "INC-001")
    assert "[DEMO]" in result


# --- SlidingWindowRateLimiter tests ---

def test_rate_limiter_unlimited_always_allows():
    limiter = SlidingWindowRateLimiter(max_calls_per_hour=0)
    for _ in range(100):
        assert limiter.check_and_consume() is True


def test_rate_limiter_blocks_at_limit():
    limiter = SlidingWindowRateLimiter(max_calls_per_hour=3)
    assert limiter.check_and_consume() is True
    assert limiter.check_and_consume() is True
    assert limiter.check_and_consume() is True
    assert limiter.check_and_consume() is False  # 4th call blocked


def test_rate_limiter_calls_in_window():
    limiter = SlidingWindowRateLimiter(max_calls_per_hour=10)
    limiter.check_and_consume()
    limiter.check_and_consume()
    assert limiter.calls_in_window == 2


# --- load_config tests ---

def test_load_config_defaults_when_no_file():
    config = load_config(path="/tmp/nonexistent-retro-pilot-xyz.yml")
    assert isinstance(config, RetroPilotConfig)
    assert config.demo_mode is False
    assert config.evaluator.pass_threshold == 0.80


def test_load_config_env_var_substitution(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MODEL", "claude-haiku-4-5-20251001")
    config_file = tmp_path / "retro-pilot.yml"
    config_file.write_text("llm:\n  model: ${TEST_MODEL}\n")
    config = load_config(path=config_file)
    assert config.llm.model == "claude-haiku-4-5-20251001"


def test_load_config_extra_keys_raises(tmp_path):
    from pydantic import ValidationError
    config_file = tmp_path / "retro-pilot.yml"
    config_file.write_text("unknown_key: value\n")
    with pytest.raises(ValidationError):
        load_config(path=config_file)
