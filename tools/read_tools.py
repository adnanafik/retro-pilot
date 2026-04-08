"""Read-only tools for retro-pilot evidence collection.

All tools here are READ_ONLY — they fetch data, never mutate state.
In DEMO_MODE (demo_mode=True kwarg), they return synthetic data without
making external API calls.
"""
from __future__ import annotations

import json
import os
from typing import Any

from tools.registry import Permission, Tool


def _demo_active(kwarg_override: bool) -> bool:
    """Return True if demo mode is active via kwarg or DEMO_MODE env var."""
    return kwarg_override or os.environ.get("DEMO_MODE", "").lower() == "true"


class GetLogsTool(Tool):
    """Fetch log entries for a service within a time window.

    Returns relevant log lines around the incident window. Fetches only
    pertinent sections — not entire log files. Use start_time/end_time
    to scope the window; ±30 minutes around the incident is typical.
    """

    @property
    def name(self) -> str:
        return "get_logs"

    @property
    def description(self) -> str:
        return (
            "Fetch log entries for a named service within a time window. "
            "Returns log lines as a JSON array of {timestamp, level, service, message} objects. "
            "Scope the window tightly — the tool returns at most 200 lines."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name, e.g. 'auth-service'"},
                "start_time": {"type": "string", "description": "ISO 8601 start of window"},
                "end_time": {"type": "string", "description": "ISO 8601 end of window"},
                "level_filter": {
                    "type": "string",
                    "enum": ["ERROR", "WARN", "INFO", "DEBUG", "ALL"],
                    "description": "Minimum log level to return. Default ALL.",
                },
            },
            "required": ["service", "start_time", "end_time"],
        }

    @property
    def permission(self) -> Permission:
        return Permission.READ_ONLY

    def execute(
        self,
        *,
        service: str,
        start_time: str,
        end_time: str,
        level_filter: str = "ALL",
        demo_mode: bool = False,
        **_: Any,
    ) -> str:
        if _demo_active(demo_mode):
            return json.dumps([
                {
                    "timestamp": start_time,
                    "level": "ERROR",
                    "service": service,
                    "message": f"Connection pool exhausted for {service}",
                },
                {
                    "timestamp": end_time,
                    "level": "WARN",
                    "service": service,
                    "message": f"Timeout waiting for pool slot in {service}",
                },
            ])
        return json.dumps({"error": "No log backend configured. Set DEMO_MODE=true for demo."})


class GetMetricsTool(Tool):
    """Fetch time-series metrics for a namespace/metric around the incident."""

    @property
    def name(self) -> str:
        return "get_metrics"

    @property
    def description(self) -> str:
        return (
            "Fetch time-series metric data for a given namespace and metric name. "
            "Returns an array of {timestamp, metric_name, value, unit} snapshots. "
            "Use the incident window ±30 minutes to capture ramp-up and recovery."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "Metric namespace, e.g. 'auth-service'"},
                "metric_name": {"type": "string", "description": "e.g. 'connection_pool_utilisation'"},
                "start_time": {"type": "string", "description": "ISO 8601 start"},
                "end_time": {"type": "string", "description": "ISO 8601 end"},
                "period_seconds": {"type": "integer", "description": "Aggregation period. Default 60."},
            },
            "required": ["namespace", "metric_name", "start_time", "end_time"],
        }

    @property
    def permission(self) -> Permission:
        return Permission.READ_ONLY

    def execute(
        self,
        *,
        namespace: str,
        metric_name: str,
        start_time: str,
        end_time: str,
        period_seconds: int = 60,
        demo_mode: bool = False,
        **_: Any,
    ) -> str:
        if _demo_active(demo_mode):
            return json.dumps([
                {
                    "timestamp": start_time,
                    "metric_name": metric_name,
                    "value": 82.0,
                    "unit": "Percent",
                },
                {
                    "timestamp": end_time,
                    "metric_name": metric_name,
                    "value": 100.0,
                    "unit": "Percent",
                },
            ])
        return json.dumps({"error": "No metrics backend configured. Set DEMO_MODE=true for demo."})


class GetGitHistoryTool(Tool):
    """Fetch recent commits, deploys, and merged PRs for a repo."""

    @property
    def name(self) -> str:
        return "get_git_history"

    @property
    def description(self) -> str:
        return (
            "Fetch commits, deployments, and merged PRs for a repository in the "
            "last N hours. Returns an array of git events sorted by timestamp descending. "
            "Use this to identify what changed before the incident."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/repo slug, e.g. 'acme/auth-service'"},
                "since_hours": {"type": "integer", "description": "Look back N hours. Default 24."},
            },
            "required": ["repo"],
        }

    @property
    def permission(self) -> Permission:
        return Permission.READ_ONLY

    def execute(
        self,
        *,
        repo: str,
        since_hours: int = 24,
        demo_mode: bool = False,
        **_: Any,
    ) -> str:
        if _demo_active(demo_mode):
            return json.dumps([
                {
                    "timestamp": "2026-01-15T13:55:00Z",
                    "commit_sha": "abc1234",
                    "author": "dev@acme.com",
                    "message": "No code changes",
                    "repo": repo,
                    "type": "deploy",
                },
            ])
        return json.dumps({"error": "No git backend configured. Set DEMO_MODE=true for demo."})


class GetSlackThreadTool(Tool):
    """Fetch the Slack thread from an incident channel."""

    @property
    def name(self) -> str:
        return "get_slack_thread"

    @property
    def description(self) -> str:
        return (
            "Fetch messages from a Slack channel incident thread. "
            "Returns messages sorted chronologically. Useful for understanding "
            "timeline of human response and communications during the incident."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Slack channel name, e.g. '#incident-2026-0001'"},
                "limit": {"type": "integer", "description": "Max messages to return. Default 100."},
            },
            "required": ["channel"],
        }

    @property
    def permission(self) -> Permission:
        return Permission.READ_ONLY

    def execute(
        self,
        *,
        channel: str,
        limit: int = 100,
        demo_mode: bool = False,
        **_: Any,
    ) -> str:
        if _demo_active(demo_mode):
            return json.dumps([
                {
                    "timestamp": "2026-01-15T14:12:00Z",
                    "author": "oncall",
                    "text": f"Incident declared in {channel}. Investigating auth-service errors.",
                    "thread_ts": None,
                },
            ])
        return json.dumps({"error": "No Slack backend configured. Set DEMO_MODE=true for demo."})


class GetServiceMapTool(Tool):
    """Fetch the dependency map for a service."""

    @property
    def name(self) -> str:
        return "get_service_map"

    @property
    def description(self) -> str:
        return (
            "Fetch upstream and downstream dependencies for a service. "
            "Returns a list of {service, relationship} pairs. "
            "Use this to understand blast radius and cascade paths."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name to look up"},
            },
            "required": ["service"],
        }

    @property
    def permission(self) -> Permission:
        return Permission.READ_ONLY

    def execute(self, *, service: str, demo_mode: bool = False, **_: Any) -> str:
        if _demo_active(demo_mode):
            return json.dumps({
                "service": service,
                "upstream": [],
                "downstream": ["payment-service", "session-service"],
            })
        return json.dumps({"error": "No service map backend configured. Set DEMO_MODE=true."})
