"""Pydantic models shared across all retro-pilot agents.

All inter-agent communication uses these typed models — no raw dicts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ── Sub-models for Evidence ────────────────────────────────────────────────────

class LogEntry(BaseModel):
    timestamp: datetime
    level: str
    service: str
    message: str


class MetricSnapshot(BaseModel):
    timestamp: datetime
    metric_name: str
    value: float
    unit: str


class GitEvent(BaseModel):
    timestamp: datetime
    commit_sha: str
    author: str
    message: str
    repo: str
    type: Literal["commit", "deploy", "pr_merge", "tag"]


class SlackMessage(BaseModel):
    timestamp: datetime
    author: str
    text: str
    thread_ts: str | None = None


# ── Input ──────────────────────────────────────────────────────────────────────

class Incident(BaseModel):
    id: str = Field(..., description="e.g. 'INC-2026-0142'")
    title: str
    severity: Literal["SEV1", "SEV2", "SEV3", "SEV4"]
    started_at: datetime
    resolved_at: datetime
    affected_services: list[str]
    involved_repos: list[str]
    slack_channel: str
    metrics_namespace: str | None = None
    reported_by: str


# ── Intermediate outputs ───────────────────────────────────────────────────────

class Evidence(BaseModel):
    logs: list[LogEntry]
    metrics: list[MetricSnapshot]
    git_events: list[GitEvent]
    slack_messages: list[SlackMessage]
    collected_at: datetime
    gaps: list[str] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    timestamp: datetime
    description: str
    source: Literal["log", "metric", "git", "slack", "manual"]
    significance: Literal["low", "medium", "high", "critical"]


class Timeline(BaseModel):
    events: list[TimelineEvent]
    first_signal_at: datetime
    detection_lag_minutes: int = Field(..., ge=0)
    resolution_duration_minutes: int = Field(..., ge=0)


class RootCause(BaseModel):
    primary: str
    contributing_factors: list[str]
    trigger: str
    blast_radius: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    evidence_refs: list[str]


class ActionItem(BaseModel):
    title: str
    owner_role: str
    deadline_days: int = Field(..., ge=1)
    priority: Literal["P1", "P2", "P3"]
    type: Literal["prevention", "detection", "response", "documentation"]
    acceptance_criteria: str


# ── Final output ───────────────────────────────────────────────────────────────

class PostMortem(BaseModel):
    incident: Incident
    executive_summary: str
    timeline: Timeline
    root_cause: RootCause
    action_items: list[ActionItem]
    lessons_learned: list[str]
    similar_incidents: list[str] = Field(default_factory=list)
    draft: bool = True
    generated_at: datetime
    revision_count: int = Field(default=0, ge=0)


# ── Evaluator output ───────────────────────────────────────────────────────────

class EvaluationScore(BaseModel):
    total: float = Field(..., ge=0.0, le=1.0)
    timeline_completeness: float = Field(..., ge=0.0, le=1.0)
    root_cause_clarity: float = Field(..., ge=0.0, le=1.0)
    action_item_quality: float = Field(..., ge=0.0, le=1.0)
    executive_summary_clarity: float = Field(..., ge=0.0, le=1.0)
    similar_incidents_referenced: float = Field(..., ge=0.0, le=1.0)
    passed: bool
    revision_brief: str | None = None
    revision_number: int = 0

    @model_validator(mode="after")
    def revision_brief_consistent_with_passed(self) -> EvaluationScore:
        if self.passed and self.revision_brief is not None:
            raise ValueError("revision_brief must be None when passed is True")
        if not self.passed and self.revision_brief is None:
            raise ValueError("revision_brief is required when passed is False")
        return self
