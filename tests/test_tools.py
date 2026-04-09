import json as json_module

import pytest

import tools.write_tools as write_tools_module
from tools.read_tools import (
    GetGitHistoryTool,
    GetLogsTool,
    GetMetricsTool,
    GetServiceMapTool,
    GetSlackThreadTool,
)
from tools.registry import Permission
from tools.write_tools import NotifyTool, SavePostmortemTool


def test_get_logs_tool_is_read_only():
    t = GetLogsTool()
    assert t.permission == Permission.READ_ONLY


def test_get_logs_tool_schema_has_required_fields():
    t = GetLogsTool()
    schema = t.input_schema
    assert schema["type"] == "object"
    assert "service" in schema["properties"]
    assert "start_time" in schema["properties"]
    assert "end_time" in schema["properties"]


def test_get_metrics_tool_schema():
    t = GetMetricsTool()
    schema = t.input_schema
    assert "namespace" in schema["properties"]
    assert "metric_name" in schema["properties"]


def test_get_git_history_tool_schema():
    t = GetGitHistoryTool()
    schema = t.input_schema
    assert "repo" in schema["properties"]
    assert "since_hours" in schema["properties"]


def test_get_slack_thread_tool_schema():
    t = GetSlackThreadTool()
    schema = t.input_schema
    assert "channel" in schema["properties"]


def test_get_service_map_tool_schema():
    t = GetServiceMapTool()
    schema = t.input_schema
    assert "service" in schema["properties"]


def test_save_postmortem_requires_confirmation():
    t = SavePostmortemTool()
    assert t.permission == Permission.REQUIRES_CONFIRMATION


def test_notify_tool_requires_confirmation():
    t = NotifyTool()
    assert t.permission == Permission.REQUIRES_CONFIRMATION


def test_get_logs_execute_demo_returns_string():
    t = GetLogsTool()
    result = t.execute(
        service="auth-service",
        start_time="2026-01-15T14:00:00Z",
        end_time="2026-01-15T15:00:00Z",
        demo_mode=True,
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_to_api_dict_shape():
    t = GetLogsTool()
    api = t.to_api_dict()
    assert set(api.keys()) == {"name", "description", "input_schema"}


def test_get_logs_execute_demo_via_env_var(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    t = GetLogsTool()
    result = t.execute(
        service="auth-service",
        start_time="2026-01-15T14:00:00Z",
        end_time="2026-01-15T15:00:00Z",
        # no demo_mode kwarg — relies on env var
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_save_postmortem_live_write(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setattr(write_tools_module, "_POSTMORTEMS_DIR", tmp_path)
    t = SavePostmortemTool()
    pm_json = json_module.dumps({"incident_id": "INC-TEST", "draft": True})
    result = t.execute(incident_id="INC-TEST", postmortem_json=pm_json)
    data = json_module.loads(result)
    assert data["status"] == "saved"
    saved_file = tmp_path / "INC-TEST.json"
    assert saved_file.exists()
    assert json_module.loads(saved_file.read_text())["draft"] is True


def test_save_postmortem_invalid_json_raises(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    t = SavePostmortemTool()
    with pytest.raises(ValueError, match="not valid JSON"):
        t.execute(incident_id="INC-TEST", postmortem_json="not json at all")
