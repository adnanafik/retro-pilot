# Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the complete data contract (all Pydantic models), tool registry with permission tiers, read/write tools, shared utilities, and the AgentLoop execution engine.

**Architecture:** All inter-agent data is typed Pydantic v2 models — no raw dicts cross boundaries. The AgentLoop in `agents/base_agent.py` is the generic tool-use loop engine; every specialist agent will extend `BaseAgent` and run through it. The `ToolRegistry` in `tools/registry.py` gates tool access by permission tier so agents cannot call tools outside their blast-radius ceiling.

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, sentence-transformers (declared, not yet used), anthropic SDK, pytest, ruff, hatchling

**Reference:** Pattern source — `/Users/adnankhan/dev/ops-pilot`. Do NOT copy code; re-implement with retro-pilot types.

---

## File Map

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Project metadata, dependencies, pytest/ruff config |
| `Dockerfile` | Multi-stage: base, test, app |
| `docker-compose.yml` | `test` service + `retro-pilot-demo` service |
| `shared/__init__.py` | Empty package marker |
| `shared/models.py` | All Pydantic models: Incident, Evidence, Timeline, RootCause, ActionItem, PostMortem, EvaluationScore + sub-models |
| `shared/config.py` | YAML config loader with env-var substitution and Pydantic validation |
| `shared/context_budget.py` | Token estimation + Strategy A compaction |
| `shared/trust_context.py` | AuditLog (JSONL, atomic, per-day rotation) + ExplanationGenerator dataclass |
| `shared/tenant_context.py` | Per-deployment isolation dataclass + rate limiter stub |
| `shared/state_store.py` | JSON state persistence with atomic writes |
| `tools/__init__.py` | Empty package marker |
| `tools/registry.py` | ToolRegistry: register, get_tools by permission tier |
| `tools/read_tools.py` | GetLogsTool, GetMetricsTool, GetGitHistoryTool, GetSlackThreadTool, GetServiceMapTool |
| `tools/write_tools.py` | SavePostmortemTool, NotifyTool (REQUIRES_CONFIRMATION) |
| `agents/__init__.py` | Empty package marker |
| `agents/base_agent.py` | BaseAgent abstract class + AgentLoop tool-use engine |
| `tests/__init__.py` | Empty package marker |
| `tests/test_models.py` | Model validation, field constraints, literal checks |
| `tests/test_registry.py` | Permission tiers, watermark filter, duplicate detection |
| `tests/test_tools.py` | Tool schema shape, demo execution |
| `tests/test_base_agent.py` | AgentLoop: end_turn, turn limit, tool execution, compaction |

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `shared/__init__.py`, `tools/__init__.py`, `agents/__init__.py`, `tests/__init__.py`, `knowledge/__init__.py`, `evaluator/__init__.py`, `demo/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "retro-pilot"
version = "0.1.0"
description = "Autonomous incident post-mortem system — learns from failures, builds institutional memory"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
    "anthropic>=0.40.0",
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.29.0",
    "pydantic>=2.7.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0.0",
    "chromadb>=0.5.0",
    "sentence-transformers>=3.0.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=5.0.0",
    "ruff>=0.4.0",
]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "C4", "SIM"]
ignore = ["E501"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--cov=agents --cov=shared --cov=tools --cov=evaluator --cov-report=term-missing"

[tool.coverage.run]
omit = ["tests/*", "demo/*", "docs/*"]

[tool.hatch.build.targets.wheel]
packages = ["agents", "shared", "tools", "knowledge", "evaluator"]
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
FROM python:3.11-slim AS base

WORKDIR /app

COPY pyproject.toml README.md ./
RUN mkdir -p agents shared tools knowledge evaluator demo scripts && \
    touch agents/__init__.py shared/__init__.py tools/__init__.py \
          knowledge/__init__.py evaluator/__init__.py demo/__init__.py && \
    pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir -e ".[dev]"

COPY agents/ agents/
COPY shared/ shared/
COPY tools/ tools/
COPY knowledge/ knowledge/
COPY evaluator/ evaluator/
COPY demo/ demo/
COPY scripts/ scripts/

RUN mkdir -p audit chroma_db

ENV PYTHONUNBUFFERED=1

FROM base AS test
COPY tests/ tests/
CMD ["pytest", "--tb=short", "-q"]

FROM base AS app
ENV DEMO_MODE=true
EXPOSE 8000
CMD ["uvicorn", "demo.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Create docker-compose.yml**

```yaml
services:
  test:
    build:
      context: .
      target: test
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-demo-mode-no-key-needed}
      - DEMO_MODE=true
    profiles:
      - test

  retro-pilot-demo:
    build:
      context: .
      target: app
    env_file: .env
    ports:
      - "8000:8000"
    environment:
      - DEMO_MODE=${DEMO_MODE:-true}
    volumes:
      - ./chroma_db:/app/chroma_db
    restart: unless-stopped
```

- [ ] **Step 4: Create package markers**

```bash
touch shared/__init__.py tools/__init__.py agents/__init__.py \
      tests/__init__.py knowledge/__init__.py evaluator/__init__.py \
      demo/__init__.py scripts/__init__.py
```

- [ ] **Step 5: Verify install**

```bash
pip install -e ".[dev]"
python -c "import shared, tools, agents, knowledge, evaluator"
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml Dockerfile docker-compose.yml shared/__init__.py tools/__init__.py agents/__init__.py tests/__init__.py knowledge/__init__.py evaluator/__init__.py demo/__init__.py scripts/__init__.py
git commit -m "chore: project scaffold — pyproject, Docker, package structure"
```

---

## Task 2: Shared Models

**Files:**
- Create: `shared/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_models.py
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from shared.models import (
    Incident, Evidence, LogEntry, MetricSnapshot, GitEvent, SlackMessage,
    TimelineEvent, Timeline, RootCause, ActionItem, PostMortem, EvaluationScore,
)

NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


def make_incident(**overrides) -> dict:
    base = {
        "id": "INC-2026-0001",
        "title": "Redis pool exhaustion in auth-service",
        "severity": "SEV1",
        "started_at": NOW,
        "resolved_at": datetime(2026, 1, 15, 14, 47, 0, tzinfo=timezone.utc),
        "affected_services": ["auth-service", "payment-service"],
        "involved_repos": ["acme/auth-service"],
        "slack_channel": "#incident-2026-0001",
        "metrics_namespace": None,
        "reported_by": "oncall-engineer",
    }
    return {**base, **overrides}


def test_incident_valid():
    inc = Incident(**make_incident())
    assert inc.severity == "SEV1"
    assert inc.id == "INC-2026-0001"


def test_incident_invalid_severity():
    with pytest.raises(ValidationError):
        Incident(**make_incident(severity="SEV5"))


def test_evidence_gaps_default_empty():
    ev = Evidence(
        logs=[], metrics=[], git_events=[], slack_messages=[],
        collected_at=NOW, gaps=[]
    )
    assert ev.gaps == []


def test_timeline_event_significance_literal():
    with pytest.raises(ValidationError):
        TimelineEvent(
            timestamp=NOW, description="x", source="log", significance="extreme"
        )


def test_root_cause_confidence_literal():
    with pytest.raises(ValidationError):
        RootCause(
            primary="x", contributing_factors=[], trigger="y",
            blast_radius="low", confidence="VERY_HIGH", evidence_refs=[]
        )


def test_action_item_all_fields():
    ai = ActionItem(
        title="Add pool saturation alert",
        owner_role="Platform team",
        deadline_days=14,
        priority="P1",
        type="detection",
        acceptance_criteria="Alert fires when pool utilisation > 80% for 5 min",
    )
    assert ai.priority == "P1"


def test_postmortem_draft_default_true():
    inc = Incident(**make_incident())
    rc = RootCause(
        primary="Pool exhausted", contributing_factors=[], trigger="traffic spike",
        blast_radius="high", confidence="HIGH", evidence_refs=[]
    )
    tl = Timeline(
        events=[], first_signal_at=NOW, detection_lag_minutes=12,
        resolution_duration_minutes=47
    )
    pm = PostMortem(
        incident=inc,
        executive_summary="Short summary.",
        timeline=tl,
        root_cause=rc,
        action_items=[],
        lessons_learned=[],
        similar_incidents=[],
        generated_at=NOW,
    )
    assert pm.draft is True
    assert pm.revision_count == 0


def test_evaluation_score_pass_threshold():
    score = EvaluationScore(
        total=0.91,
        timeline_completeness=0.90,
        root_cause_clarity=0.95,
        action_item_quality=0.90,
        executive_summary_clarity=0.85,
        similar_incidents_referenced=0.90,
        passed=True,
        revision_brief=None,
        revision_number=1,
    )
    assert score.passed is True
    assert score.revision_brief is None


def test_evaluation_score_fail_has_brief():
    score = EvaluationScore(
        total=0.72,
        timeline_completeness=0.60,
        root_cause_clarity=0.70,
        action_item_quality=0.80,
        executive_summary_clarity=0.75,
        similar_incidents_referenced=0.70,
        passed=False,
        revision_brief="Timeline missing detection lag. Action item 2 has no acceptance_criteria.",
        revision_number=1,
    )
    assert score.passed is False
    assert score.revision_brief is not None
```

- [ ] **Step 2: Run test — expect import failure**

```bash
pytest tests/test_models.py -v
```
Expected: `ModuleNotFoundError: No module named 'shared.models'`

- [ ] **Step 3: Implement shared/models.py**

```python
"""Pydantic models shared across all retro-pilot agents.

All inter-agent communication uses these typed models — no raw dicts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    detection_lag_minutes: int
    resolution_duration_minutes: int


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
    deadline_days: int
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
    revision_count: int = 0


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
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/test_models.py -v
```
Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add shared/models.py tests/test_models.py
git commit -m "feat: shared/models.py — all Pydantic v2 domain models"
```

---

## Task 3: Tool Registry

**Files:**
- Create: `tools/registry.py`
- Create: `tests/test_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_registry.py
import pytest
from tools.registry import Permission, Tool, ToolRegistry


class FakeReadTool(Tool):
    @property
    def name(self) -> str: return "fake_read"
    @property
    def description(self) -> str: return "A read-only fake tool"
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}
    @property
    def permission(self) -> Permission: return Permission.READ_ONLY
    def execute(self, **kwargs) -> str: return "read result"


class FakeWriteTool(Tool):
    @property
    def name(self) -> str: return "fake_write"
    @property
    def description(self) -> str: return "A write fake tool"
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}
    @property
    def permission(self) -> Permission: return Permission.WRITE
    def execute(self, **kwargs) -> str: return "write result"


class FakeDangerousTool(Tool):
    @property
    def name(self) -> str: return "fake_dangerous"
    @property
    def description(self) -> str: return "Dangerous tool"
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}
    @property
    def permission(self) -> Permission: return Permission.DANGEROUS
    def execute(self, **kwargs) -> str: return "danger!"


class FakeConfirmTool(Tool):
    @property
    def name(self) -> str: return "fake_confirm"
    @property
    def description(self) -> str: return "Confirmation tool"
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}
    @property
    def permission(self) -> Permission: return Permission.REQUIRES_CONFIRMATION
    def execute(self, **kwargs) -> str: return "confirmed"


def make_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(FakeReadTool())
    r.register(FakeWriteTool())
    r.register(FakeDangerousTool())
    r.register(FakeConfirmTool())
    return r


def test_read_only_ceiling_returns_only_read():
    r = make_registry()
    tools = r.get_tools(max_permission=Permission.READ_ONLY)
    names = [t.name for t in tools]
    assert "fake_read" in names
    assert "fake_write" not in names
    assert "fake_dangerous" not in names
    assert "fake_confirm" not in names


def test_write_ceiling_includes_read_and_write():
    r = make_registry()
    tools = r.get_tools(max_permission=Permission.WRITE)
    names = [t.name for t in tools]
    assert "fake_read" in names
    assert "fake_write" in names
    assert "fake_dangerous" not in names


def test_include_dangerous_adds_both_dangerous_tiers():
    r = make_registry()
    tools = r.get_tools(max_permission=Permission.WRITE, include_dangerous=True)
    names = [t.name for t in tools]
    assert "fake_dangerous" in names
    assert "fake_confirm" in names


def test_duplicate_registration_raises():
    r = ToolRegistry()
    r.register(FakeReadTool())
    with pytest.raises(ValueError, match="already registered"):
        r.register(FakeReadTool())


def test_len_matches_registered_count():
    r = make_registry()
    assert len(r) == 4


def test_to_api_dict_has_required_keys():
    tool = FakeReadTool()
    api = tool.to_api_dict()
    assert api["name"] == "fake_read"
    assert "description" in api
    assert "input_schema" in api
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_registry.py -v
```
Expected: `ModuleNotFoundError: No module named 'tools.registry'`

- [ ] **Step 3: Implement tools/registry.py**

```python
"""Tool registry for retro-pilot agent loops.

Central catalog of all available tools with permission-tier filtering.
Agents query the registry to get a scoped tool list matching their
blast-radius ceiling. Execution and confirmation logic stays in AgentLoop.

Permission tiers:
  READ_ONLY, WRITE      — linear watermark: READ_ONLY ≤ WRITE
  DANGEROUS, REQUIRES_CONFIRMATION — orthogonal; excluded by default,
                                     opt-in via include_dangerous=True
"""
from __future__ import annotations

import abc
from enum import StrEnum


class Permission(StrEnum):
    READ_ONLY             = "read_only"
    WRITE                 = "write"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    DANGEROUS             = "dangerous"


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
    def input_schema(self) -> dict: ...

    @property
    @abc.abstractmethod
    def permission(self) -> Permission: ...

    @abc.abstractmethod
    def execute(self, **kwargs) -> str: ...

    def to_api_dict(self) -> dict:
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
            raise ValueError(
                f"Tool '{tool.name}' is already registered."
            )
        self._tools[tool.name] = tool

    def get_tools(
        self,
        max_permission: Permission = Permission.READ_ONLY,
        include_dangerous: bool = False,
    ) -> list[Tool]:
        max_tier = _TIER_ORDER.get(max_permission, 0)
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
```

- [ ] **Step 4: Run tests — all pass**

```bash
pytest tests/test_registry.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/registry.py tests/test_registry.py
git commit -m "feat: tools/registry.py — ToolRegistry with permission tier filtering"
```

---

## Task 4: Read & Write Tools

**Files:**
- Create: `tools/read_tools.py`
- Create: `tools/write_tools.py`
- Create: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tools.py
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
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_tools.py -v
```
Expected: `ModuleNotFoundError: No module named 'tools.read_tools'`

- [ ] **Step 3: Implement tools/read_tools.py**

```python
"""Read-only tools for retro-pilot evidence collection.

All tools here are READ_ONLY — they fetch data, never mutate state.
In DEMO_MODE (demo_mode=True kwarg), they return synthetic data without
making external API calls.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from tools.registry import Permission, Tool


class GetLogsTool(Tool):
    """Fetch log entries for a service within a time window.

    Returns relevant log lines around the incident window. Fetches only
    pertinent sections — not entire log files. Use start_time/end_time
    to scope the window; ±30 minutes around the incident is typical.
    """

    @property
    def name(self) -> str: return "get_logs"

    @property
    def description(self) -> str:
        return (
            "Fetch log entries for a named service within a time window. "
            "Returns log lines as a JSON array of {timestamp, level, service, message} objects. "
            "Scope the window tightly — the tool returns at most 200 lines."
        )

    @property
    def input_schema(self) -> dict:
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
    def permission(self) -> Permission: return Permission.READ_ONLY

    def execute(self, *, service: str, start_time: str, end_time: str,
                level_filter: str = "ALL", demo_mode: bool = False, **_) -> str:
        if demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true":
            return json.dumps([
                {"timestamp": start_time, "level": "ERROR",
                 "service": service, "message": f"Connection pool exhausted for {service}"},
                {"timestamp": end_time, "level": "WARN",
                 "service": service, "message": f"Timeout waiting for pool slot in {service}"},
            ])
        # Real implementation: call logging backend (CloudWatch, Datadog, etc.)
        # Injected via config in future phases.
        return json.dumps({"error": "No log backend configured. Set DEMO_MODE=true for demo."})


class GetMetricsTool(Tool):
    """Fetch time-series metrics for a namespace/metric around the incident."""

    @property
    def name(self) -> str: return "get_metrics"

    @property
    def description(self) -> str:
        return (
            "Fetch time-series metric data for a given namespace and metric name. "
            "Returns an array of {timestamp, metric_name, value, unit} snapshots. "
            "Use the incident window ±30 minutes to capture ramp-up and recovery."
        )

    @property
    def input_schema(self) -> dict:
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
    def permission(self) -> Permission: return Permission.READ_ONLY

    def execute(self, *, namespace: str, metric_name: str,
                start_time: str, end_time: str,
                period_seconds: int = 60, demo_mode: bool = False, **_) -> str:
        if demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true":
            return json.dumps([
                {"timestamp": start_time, "metric_name": metric_name,
                 "value": 82.0, "unit": "Percent"},
                {"timestamp": end_time, "metric_name": metric_name,
                 "value": 100.0, "unit": "Percent"},
            ])
        return json.dumps({"error": "No metrics backend configured. Set DEMO_MODE=true for demo."})


class GetGitHistoryTool(Tool):
    """Fetch recent commits, deploys, and merged PRs for a repo."""

    @property
    def name(self) -> str: return "get_git_history"

    @property
    def description(self) -> str:
        return (
            "Fetch commits, deployments, and merged PRs for a repository in the "
            "last N hours. Returns an array of git events sorted by timestamp descending. "
            "Use this to identify what changed before the incident."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/repo slug, e.g. 'acme/auth-service'"},
                "since_hours": {"type": "integer", "description": "Look back N hours. Default 24."},
            },
            "required": ["repo"],
        }

    @property
    def permission(self) -> Permission: return Permission.READ_ONLY

    def execute(self, *, repo: str, since_hours: int = 24,
                demo_mode: bool = False, **_) -> str:
        if demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true":
            return json.dumps([
                {"timestamp": "2026-01-15T13:55:00Z", "commit_sha": "abc1234",
                 "author": "dev@acme.com", "message": "No code changes",
                 "repo": repo, "type": "deploy"},
            ])
        return json.dumps({"error": "No git backend configured. Set DEMO_MODE=true for demo."})


class GetSlackThreadTool(Tool):
    """Fetch the Slack thread from an incident channel."""

    @property
    def name(self) -> str: return "get_slack_thread"

    @property
    def description(self) -> str:
        return (
            "Fetch messages from a Slack channel incident thread. "
            "Returns messages sorted chronologically. Useful for understanding "
            "timeline of human response and communications during the incident."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Slack channel name, e.g. '#incident-2026-0001'"},
                "limit": {"type": "integer", "description": "Max messages to return. Default 100."},
            },
            "required": ["channel"],
        }

    @property
    def permission(self) -> Permission: return Permission.READ_ONLY

    def execute(self, *, channel: str, limit: int = 100,
                demo_mode: bool = False, **_) -> str:
        if demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true":
            return json.dumps([
                {"timestamp": "2026-01-15T14:12:00Z", "author": "oncall",
                 "text": f"Incident declared in {channel}. Investigating auth-service errors.",
                 "thread_ts": None},
            ])
        return json.dumps({"error": "No Slack backend configured. Set DEMO_MODE=true for demo."})


class GetServiceMapTool(Tool):
    """Fetch the dependency map for a service."""

    @property
    def name(self) -> str: return "get_service_map"

    @property
    def description(self) -> str:
        return (
            "Fetch upstream and downstream dependencies for a service. "
            "Returns a list of {service, relationship} pairs. "
            "Use this to understand blast radius and cascade paths."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name to look up"},
            },
            "required": ["service"],
        }

    @property
    def permission(self) -> Permission: return Permission.READ_ONLY

    def execute(self, *, service: str, demo_mode: bool = False, **_) -> str:
        if demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true":
            return json.dumps({
                "service": service,
                "upstream": [],
                "downstream": ["payment-service", "session-service"],
            })
        return json.dumps({"error": "No service map backend configured. Set DEMO_MODE=true."})
```

- [ ] **Step 4: Implement tools/write_tools.py**

```python
"""Write tools for retro-pilot — both REQUIRES_CONFIRMATION.

These tools mutate state (save a post-mortem, send a notification).
They require explicit confirmation before execution in a live environment.
In DEMO_MODE they simulate the action without side effects.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from tools.registry import Permission, Tool


class SavePostmortemTool(Tool):
    """Save a completed post-mortem to persistent storage.

    Writes to ./postmortems/{incident_id}.json. In DEMO_MODE simulates
    the write without touching the filesystem.
    REQUIRES_CONFIRMATION — never saves without explicit operator approval.
    """

    @property
    def name(self) -> str: return "save_postmortem"

    @property
    def description(self) -> str:
        return (
            "Save a completed post-mortem document to persistent storage. "
            "Call this only after the evaluator has passed the draft (score >= 0.80). "
            "Requires operator confirmation before executing."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "incident_id": {"type": "string", "description": "e.g. 'INC-2026-0001'"},
                "postmortem_json": {"type": "string", "description": "JSON-serialised PostMortem"},
            },
            "required": ["incident_id", "postmortem_json"],
        }

    @property
    def permission(self) -> Permission: return Permission.REQUIRES_CONFIRMATION

    def execute(self, *, incident_id: str, postmortem_json: str,
                demo_mode: bool = False, **_) -> str:
        if demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true":
            return json.dumps({"status": "demo", "incident_id": incident_id,
                               "message": "Post-mortem save simulated (DEMO_MODE)"})
        out = Path("postmortems") / f"{incident_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(postmortem_json)
        return json.dumps({"status": "saved", "path": str(out)})


class NotifyTool(Tool):
    """Send an incident notification to a Slack channel.

    REQUIRES_CONFIRMATION — never sends without explicit operator approval.
    """

    @property
    def name(self) -> str: return "notify"

    @property
    def description(self) -> str:
        return (
            "Send a post-mortem completion notification to a Slack channel. "
            "Use after the post-mortem has been saved. Requires operator confirmation."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Slack channel, e.g. '#postmortems'"},
                "message": {"type": "string", "description": "Notification message text"},
                "incident_id": {"type": "string"},
            },
            "required": ["channel", "message", "incident_id"],
        }

    @property
    def permission(self) -> Permission: return Permission.REQUIRES_CONFIRMATION

    def execute(self, *, channel: str, message: str, incident_id: str,
                demo_mode: bool = False, **_) -> str:
        if demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true":
            return json.dumps({"status": "demo", "channel": channel,
                               "message": "Notification simulated (DEMO_MODE)"})
        # Real implementation: call Slack Web API
        return json.dumps({"error": "No Slack backend configured. Set DEMO_MODE=true."})
```

- [ ] **Step 5: Run tests — all pass**

```bash
pytest tests/test_tools.py -v
```
Expected: all 10 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/read_tools.py tools/write_tools.py tests/test_tools.py
git commit -m "feat: read and write tools with DEMO_MODE support"
```

---

## Task 5: Shared Utilities

**Files:**
- Create: `shared/config.py`
- Create: `shared/context_budget.py`
- Create: `shared/trust_context.py`
- Create: `shared/tenant_context.py`
- Create: `shared/state_store.py`

These are utility modules with low test complexity. Write minimal tests to confirm key contracts, then implement.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_shared_utils.py
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
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_shared_utils.py -v
```
Expected: `ModuleNotFoundError: No module named 'shared.context_budget'`

- [ ] **Step 3: Implement shared/context_budget.py**

```python
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
            if isinstance(obj, str): return len(obj)
            if isinstance(obj, dict): return sum(_count(v) for v in obj.values())
            if isinstance(obj, list): return sum(_count(i) for i in obj)
            return 0
        return _count(messages) // 4
```

- [ ] **Step 4: Implement shared/state_store.py**

```python
"""JSON-backed state persistence for retro-pilot.

Stores agent outputs keyed by incident_id:namespace. Thread-safe for
single-process use — writes are atomic via temp-file rename.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class StateStore:
    def __init__(self, path: str = "retro_pilot_state.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text())

    def set(self, incident_id: str, namespace: str, value: dict) -> None:
        self._data[f"{incident_id}:{namespace}"] = value
        self._flush()

    def get(self, incident_id: str, namespace: str) -> dict | None:
        return self._data.get(f"{incident_id}:{namespace}")

    def get_all(self, incident_id: str) -> dict[str, dict]:
        prefix = f"{incident_id}:"
        return {k[len(prefix):]: v for k, v in self._data.items() if k.startswith(prefix)}

    def delete(self, incident_id: str, namespace: str) -> None:
        self._data.pop(f"{incident_id}:{namespace}", None)
        self._flush()

    def _flush(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=self.path.parent, delete=False, suffix=".tmp"
        ) as tmp:
            json.dump(self._data, tmp, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, self.path)
```

- [ ] **Step 5: Implement shared/trust_context.py**

```python
"""TrustContext — audit log and explanation generator.

AuditLog: appends one JSONL record per tool call, per-day file rotation,
atomic writes. ExplanationGenerator: produces pre-action explanations for
REQUIRES_CONFIRMATION tools.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    """Appends tool-call records to a per-day JSONL file atomically."""

    def __init__(self, base_dir: Path | str = Path("audit")) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self) -> Path:
        date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        return self.base_dir / f"audit-{date}.jsonl"

    def record(self, *, incident_id: str, tool_name: str,
               inputs: dict[str, Any], result: str, actor: str = "agent") -> None:
        record = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "incident_id": incident_id,
            "tool": tool_name,
            "inputs": inputs,
            "result_preview": result[:200],
            "actor": actor,
        }
        log_path = self._log_path()
        with tempfile.NamedTemporaryFile(
            mode="w", dir=self.base_dir, delete=False, suffix=".tmp"
        ) as tmp:
            if log_path.exists():
                tmp.write(log_path.read_text())
            tmp.write(json.dumps(record) + "\n")
            tmp_path = tmp.name
        os.replace(tmp_path, log_path)


class ExplanationGenerator:
    """Generates pre-action explanations for REQUIRES_CONFIRMATION tools.

    In DEMO_MODE returns a canned explanation without LLM calls.
    """

    def __init__(self, backend: Any = None, model: str = "claude-sonnet-4-6") -> None:
        self._backend = backend
        self._model = model

    def explain(self, tool_name: str, inputs: dict[str, Any],
                incident_id: str) -> str:
        if os.environ.get("DEMO_MODE", "").lower() == "true" or self._backend is None:
            return (
                f"[DEMO] About to execute '{tool_name}' for incident {incident_id} "
                f"with inputs: {json.dumps(inputs, indent=2)}"
            )
        prompt = (
            f"You are about to execute tool '{tool_name}' for incident {incident_id}.\n"
            f"Inputs: {json.dumps(inputs, indent=2)}\n"
            "Explain in 1-2 sentences what this action will do and why it's appropriate."
        )
        return self._backend.complete(
            system="You generate pre-action explanations for human review.",
            user=prompt,
            model=self._model,
            max_tokens=256,
        )


@dataclass
class TrustContext:
    audit_log: AuditLog = field(default_factory=AuditLog)
    explanation_generator: ExplanationGenerator = field(
        default_factory=ExplanationGenerator
    )
```

- [ ] **Step 6: Implement shared/tenant_context.py**

```python
"""TenantContext — per-deployment isolation and rate limiting."""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter (resets on process restart)."""

    def __init__(self, max_calls_per_hour: int = 0) -> None:
        self._max = max_calls_per_hour
        self._window: deque[float] = deque()

    def check_and_consume(self) -> bool:
        if self._max == 0:
            return True
        now = time.time()
        cutoff = now - 3600
        while self._window and self._window[0] < cutoff:
            self._window.popleft()
        if len(self._window) >= self._max:
            return False
        self._window.append(now)
        return True

    @property
    def calls_in_window(self) -> int:
        now = time.time()
        cutoff = now - 3600
        return sum(1 for t in self._window if t >= cutoff)


@dataclass
class TenantContext:
    tenant_id: str = "default"
    rate_limiter: SlidingWindowRateLimiter = field(
        default_factory=SlidingWindowRateLimiter
    )
```

- [ ] **Step 7: Implement shared/config.py**

```python
"""retro-pilot configuration loader.

Reads retro-pilot.yml, substitutes ${ENV_VAR} references, validates
with Pydantic. Environment variables always override file values.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


def _substitute_env(text: str) -> str:
    """Replace ${VAR_NAME} with os.environ.get(VAR_NAME, '')."""
    return re.sub(
        r"\$\{([^}]+)\}",
        lambda m: os.environ.get(m.group(1), ""),
        text,
    )


class LLMConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_tokens: int = Field(default=4096, ge=256)
    max_turns: int = Field(default=10, ge=1)


class EvaluatorConfig(BaseModel):
    pass_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    max_revision_cycles: int = Field(default=3, ge=1)


class RetroPilotConfig(BaseModel):
    tenant_id: str = "default"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    evaluator: EvaluatorConfig = Field(default_factory=EvaluatorConfig)
    demo_mode: bool = False
    chroma_db_path: str = "./chroma_db"
    postmortems_path: str = "./postmortems"


def load_config(path: str | Path = "retro-pilot.yml") -> RetroPilotConfig:
    p = Path(path)
    if not p.exists():
        return RetroPilotConfig()
    raw = _substitute_env(p.read_text())
    data = yaml.safe_load(raw) or {}
    return RetroPilotConfig(**data)
```

- [ ] **Step 8: Run tests — all pass**

```bash
pytest tests/test_shared_utils.py -v
```
Expected: all 6 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add shared/config.py shared/context_budget.py shared/trust_context.py \
        shared/tenant_context.py shared/state_store.py tests/test_shared_utils.py
git commit -m "feat: shared utilities — config, context budget, trust/tenant context, state store"
```

---

## Task 6: Base Agent & AgentLoop

**Files:**
- Create: `agents/base_agent.py`
- Create: `tests/test_base_agent.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_base_agent.py
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from pydantic import BaseModel
from agents.base_agent import AgentLoop, BaseAgent, LoopOutcome
from tools.registry import Permission, Tool


class SimpleOutput(BaseModel):
    answer: str
    confidence: str = "HIGH"


class EchoTool(Tool):
    @property
    def name(self) -> str: return "echo"
    @property
    def description(self) -> str: return "Echo the input"
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    @property
    def permission(self) -> Permission: return Permission.READ_ONLY
    def execute(self, **kwargs) -> str: return f"echo: {kwargs.get('text', '')}"


def make_mock_backend(tool_calls: list[dict] | None = None):
    """Returns a mock LLM backend.

    tool_calls: list of {"name": str, "input": dict} to return on first call.
                Empty list or None → model ends turn immediately.
    """
    backend = MagicMock()

    def side_effect_factory(calls_remaining: list):
        def side_effect(**kwargs):
            if calls_remaining:
                call = calls_remaining.pop(0)
                response = MagicMock()
                response.content = [
                    MagicMock(type="tool_use", id="tu_1",
                              name=call["name"], input=call["input"])
                ]
                response.stop_reason = "tool_use"
                return response
            else:
                response = MagicMock()
                response.content = [MagicMock(type="text", text="done")]
                response.stop_reason = "end_turn"
                return response
        return side_effect

    remaining = list(tool_calls or [])
    backend.complete_with_tools.side_effect = side_effect_factory(remaining)

    # Extraction call (complete, not complete_with_tools)
    backend.complete.return_value = '{"answer": "Redis pool exhausted", "confidence": "HIGH"}'
    return backend


@pytest.mark.asyncio
async def test_loop_end_turn_immediately():
    backend = make_mock_backend(tool_calls=[])
    loop = AgentLoop(
        tools=[EchoTool()],
        backend=backend,
        domain_system_prompt="You are a test agent.",
        response_model=SimpleOutput,
        model="claude-sonnet-4-6",
    )
    result = await loop.run(
        messages=[{"role": "user", "content": "analyse this"}],
        incident_id="INC-001",
    )
    assert result.outcome == LoopOutcome.COMPLETED
    assert result.extracted.answer == "Redis pool exhausted"
    assert result.turns_used == 1


@pytest.mark.asyncio
async def test_loop_executes_tool_then_ends():
    backend = make_mock_backend(
        tool_calls=[{"name": "echo", "input": {"text": "hello"}}]
    )
    loop = AgentLoop(
        tools=[EchoTool()],
        backend=backend,
        domain_system_prompt="You are a test agent.",
        response_model=SimpleOutput,
        model="claude-sonnet-4-6",
    )
    result = await loop.run(
        messages=[{"role": "user", "content": "analyse this"}],
        incident_id="INC-001",
    )
    assert result.outcome == LoopOutcome.COMPLETED
    assert result.turns_used == 2  # 1 tool call turn + 1 end turn


@pytest.mark.asyncio
async def test_loop_respects_max_turns():
    # Always returns a tool call — should hit turn limit
    backend = MagicMock()
    always_tool = MagicMock()
    always_tool.content = [
        MagicMock(type="tool_use", id="tu_1", name="echo", input={"text": "x"})
    ]
    always_tool.stop_reason = "tool_use"
    backend.complete_with_tools.return_value = always_tool
    backend.complete.return_value = '{"answer": "partial", "confidence": "LOW"}'

    loop = AgentLoop(
        tools=[EchoTool()],
        backend=backend,
        domain_system_prompt="You are a test agent.",
        response_model=SimpleOutput,
        model="claude-sonnet-4-6",
        max_turns=3,
    )
    result = await loop.run(
        messages=[{"role": "user", "content": "analyse this"}],
        incident_id="INC-001",
    )
    assert result.outcome == LoopOutcome.TURN_LIMIT
    assert result.turns_used == 3


def test_base_agent_name_derived_from_class():
    class MySpecialistAgent(BaseAgent):
        def run(self, *args, **kwargs): pass
        def describe(self) -> str: return "test"

    agent = MySpecialistAgent()
    assert agent.name == "my_specialist_agent"
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/test_base_agent.py -v
```
Expected: `ModuleNotFoundError: No module named 'agents.base_agent'`

- [ ] **Step 3: Implement agents/base_agent.py**

```python
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
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from shared.context_budget import ContextBudget

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


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
        tools: list,  # list[Tool]
        backend: Any,
        domain_system_prompt: str,
        response_model: type[T],
        model: str,
        max_turns: int = 10,
        max_tokens: int = 4096,
        context_budget: ContextBudget | None = None,
    ) -> None:
        self._tools: dict[str, Any] = {t.name: t for t in tools}
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
                extracted = await self._extract(history)
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
                else:
                    try:
                        content = tool.execute(**tu.input)
                        is_error = False
                    except Exception as exc:
                        content = f"Tool error: {exc}"
                        is_error = True
                        failed_tools.append(tu.name)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": content,
                    "is_error": is_error,
                })

            history.append({"role": "user", "content": tool_results})

            # If every registered tool has failed, abort
            if failed_tools and all(
                n in failed_tools for n in self._tools
            ):
                extracted = await self._extract(history)
                return LoopResult(
                    outcome=LoopOutcome.TOOL_FAILURE,
                    extracted=extracted,
                    turns_used=turn + 1,
                    failed_tools=failed_tools,
                    last_assistant_text=last_text,
                )

        # Turn limit
        extracted = await self._extract(history)
        return LoopResult(
            outcome=LoopOutcome.TURN_LIMIT,
            extracted=extracted,
            turns_used=self._max_turns,
            failed_tools=failed_tools,
            last_assistant_text=last_text,
        )

    async def _extract(self, history: list[dict]) -> T:
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

    def __init__(self, backend: Any = None, model: str | None = None) -> None:
        self.backend = backend
        self.model = model or self.DEFAULT_MODEL

    @abc.abstractmethod
    def run(self, *args, **kwargs): ...

    @abc.abstractmethod
    def describe(self) -> str: ...

    @property
    def name(self) -> str:
        cls = type(self).__name__
        return re.sub(r"(?<!^)(?=[A-Z])", "_", cls).lower()
```

- [ ] **Step 4: Run tests — all pass**

```bash
pytest tests/test_base_agent.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Run full Phase 1 suite**

```bash
pytest tests/ -v --tb=short
```
Expected: all tests PASS. Check coverage report for `shared/`, `tools/`, `agents/`.

- [ ] **Step 6: Lint**

```bash
ruff check shared/ tools/ agents/ tests/
```
Fix any errors before committing.

- [ ] **Step 7: Commit**

```bash
git add agents/base_agent.py tests/test_base_agent.py
git commit -m "feat: agents/base_agent.py — BaseAgent + AgentLoop tool-use engine"
```

---

## Phase 1 Completion Gate

- [ ] **Create branch, run full suite, push, open PR**

```bash
git checkout -b phase/1-foundation main
# cherry-pick or rebase all phase 1 commits onto this branch
# OR: all commits above were already on a feature branch

pytest tests/ -v --tb=short
# Expected: all tests pass

git push -u origin phase/1-foundation
gh pr create \
  --title "feat: foundation — models, tool registry, base agent loop" \
  --body "$(cat <<'EOF'
## Summary

- All Pydantic v2 domain models defined in `shared/models.py`
- `ToolRegistry` with `READ_ONLY / WRITE / REQUIRES_CONFIRMATION / DANGEROUS` permission tiers
- Five read tools + two write tools, all DEMO_MODE-safe
- Shared utilities: config loader, context budget (Strategy A compaction), trust/tenant context, state store
- `AgentLoop` tool-use engine + abstract `BaseAgent` in `agents/base_agent.py`

## Test plan

- [ ] `pytest tests/` passes
- [ ] `docker compose run --rm test` exits 0
- [ ] `ruff check` clean
- [ ] All Pydantic models reject invalid literals
- [ ] ToolRegistry watermark filter verified
- [ ] AgentLoop end_turn, tool execution, and turn-limit paths all covered
EOF
)"
```
