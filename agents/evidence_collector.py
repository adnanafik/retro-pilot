"""EvidenceCollector — parallel evidence gathering for retro-pilot.

Runs four workers concurrently (Log, Metrics, Git, Slack), each with
READ_ONLY scoped tools. Workers cannot spawn further workers.
Assembles typed Evidence, noting gaps where data was unavailable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime, timedelta

from agents.base_agent import BaseAgent
from shared.models import (
    Evidence,
    GitEvent,
    Incident,
    LogEntry,
    MetricSnapshot,
    SlackMessage,
)
from tools.read_tools import (
    GetGitHistoryTool,
    GetLogsTool,
    GetMetricsTool,
    GetSlackThreadTool,
)

logger = logging.getLogger(__name__)

_WINDOW_MINUTES = 30  # ± window around incident


class EvidenceCollector(BaseAgent):
    """Gathers evidence from logs, metrics, git, and Slack in parallel.

    Each data source runs in an isolated worker with READ_ONLY tools.
    Workers cannot call each other or spawn sub-workers.
    """

    def describe(self) -> str:
        return "Parallel evidence collector: fetches logs, metrics, git history, and Slack thread"

    def run(self, incident: Incident, demo_mode: bool = False) -> Evidence:
        """Collect evidence for an incident.

        Args:
            incident: The Incident to investigate.
            demo_mode: If True (or DEMO_MODE env var set), returns synthetic data.

        Returns:
            Evidence with logs, metrics, git_events, slack_messages, gaps.
        """
        use_demo = demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true"
        return asyncio.run(self._collect(incident, use_demo))

    async def _collect(self, incident: Incident, demo_mode: bool) -> Evidence:
        start = incident.started_at - timedelta(minutes=_WINDOW_MINUTES)
        end = incident.resolved_at + timedelta(minutes=_WINDOW_MINUTES)
        start_iso = start.isoformat()
        end_iso = end.isoformat()

        log_tool = GetLogsTool()
        metrics_tool = GetMetricsTool()
        git_tool = GetGitHistoryTool()
        slack_tool = GetSlackThreadTool()

        results = await asyncio.gather(
            self._run_log_worker(log_tool, incident, start_iso, end_iso, demo_mode),
            self._run_metrics_worker(metrics_tool, incident, start_iso, end_iso, demo_mode),
            self._run_git_worker(git_tool, incident, demo_mode),
            self._run_slack_worker(slack_tool, incident, demo_mode),
            return_exceptions=True,
        )

        logs, metrics, git_events, slack_messages = [], [], [], []
        gaps: list[str] = []

        for label, result in zip(
            ["logs", "metrics", "git_events", "slack_messages"], results, strict=True
        ):
            if isinstance(result, Exception):
                gaps.append(f"{label}: {result}")
                logger.warning("EvidenceCollector: %s worker failed: %s", label, result)
            else:
                if label == "logs":
                    logs = result
                elif label == "metrics":
                    metrics = result
                elif label == "git_events":
                    git_events = result
                elif label == "slack_messages":
                    slack_messages = result

        return Evidence(
            logs=logs,
            metrics=metrics,
            git_events=git_events,
            slack_messages=slack_messages,
            collected_at=datetime.now(tz=UTC),
            gaps=gaps,
        )

    async def _run_log_worker(
        self, tool: GetLogsTool, incident: Incident,
        start: str, end: str, demo_mode: bool
    ) -> list[LogEntry]:
        entries: list[LogEntry] = []
        for service in incident.affected_services:
            raw = tool.execute(service=service, start_time=start, end_time=end,
                               demo_mode=demo_mode)
            for item in json.loads(raw):
                if isinstance(item, dict) and "timestamp" in item:
                    entries.append(LogEntry(
                        timestamp=datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")),
                        level=item.get("level", "INFO"),
                        service=item.get("service", service),
                        message=item.get("message", ""),
                    ))
        return entries

    async def _run_metrics_worker(
        self, tool: GetMetricsTool, incident: Incident,
        start: str, end: str, demo_mode: bool
    ) -> list[MetricSnapshot]:
        snapshots: list[MetricSnapshot] = []
        ns = incident.metrics_namespace or incident.affected_services[0]
        raw = tool.execute(namespace=ns, metric_name="error_rate",
                           start_time=start, end_time=end, demo_mode=demo_mode)
        for item in json.loads(raw):
            if isinstance(item, dict) and "timestamp" in item:
                snapshots.append(MetricSnapshot(
                    timestamp=datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")),
                    metric_name=item.get("metric_name", "error_rate"),
                    value=float(item.get("value", 0.0)),
                    unit=item.get("unit", ""),
                ))
        return snapshots

    async def _run_git_worker(
        self, tool: GetGitHistoryTool, incident: Incident, demo_mode: bool
    ) -> list[GitEvent]:
        events: list[GitEvent] = []
        for repo in incident.involved_repos:
            raw = tool.execute(repo=repo, since_hours=24, demo_mode=demo_mode)
            for item in json.loads(raw):
                if isinstance(item, dict) and "timestamp" in item:
                    events.append(GitEvent(
                        timestamp=datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")),
                        commit_sha=item.get("commit_sha", ""),
                        author=item.get("author", ""),
                        message=item.get("message", ""),
                        repo=item.get("repo", repo),
                        type=item.get("type", "commit"),
                    ))
        return events

    async def _run_slack_worker(
        self, tool: GetSlackThreadTool, incident: Incident, demo_mode: bool
    ) -> list[SlackMessage]:
        raw = tool.execute(channel=incident.slack_channel, demo_mode=demo_mode)
        messages: list[SlackMessage] = []
        for item in json.loads(raw):
            if isinstance(item, dict) and "timestamp" in item:
                messages.append(SlackMessage(
                    timestamp=datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")),
                    author=item.get("author", ""),
                    text=item.get("text", ""),
                    thread_ts=item.get("thread_ts"),
                ))
        return messages
