from tools.read_tools import (
    GetLogsTool, GetMetricsTool, GetGitHistoryTool,
    GetSlackThreadTool, GetServiceMapTool,
)
from tools.write_tools import SavePostmortemTool, NotifyTool
from tools.registry import Permission


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
