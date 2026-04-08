"""Write tools for retro-pilot — both REQUIRES_CONFIRMATION.

These tools mutate state (save a post-mortem, send a notification).
They require explicit confirmation before execution in a live environment.
In DEMO_MODE they simulate the action without side effects.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.read_tools import _demo_active
from tools.registry import Permission, Tool

_POSTMORTEMS_DIR = Path(__file__).resolve().parent.parent / "postmortems"


class SavePostmortemTool(Tool):
    """Save a completed post-mortem to persistent storage.

    Writes to ./postmortems/{incident_id}.json. In DEMO_MODE simulates
    the write without touching the filesystem.
    REQUIRES_CONFIRMATION — never saves without explicit operator approval.
    """

    @property
    def name(self) -> str:
        return "save_postmortem"

    @property
    def description(self) -> str:
        return (
            "Save a completed post-mortem document to persistent storage. "
            "Call this only after the evaluator has passed the draft (score >= 0.80). "
            "Requires operator confirmation before executing."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "incident_id": {"type": "string", "description": "e.g. 'INC-2026-0001'"},
                "postmortem_json": {"type": "string", "description": "JSON-serialised PostMortem"},
            },
            "required": ["incident_id", "postmortem_json"],
        }

    @property
    def permission(self) -> Permission:
        return Permission.REQUIRES_CONFIRMATION

    def execute(
        self,
        *,
        incident_id: str,
        postmortem_json: str,
        demo_mode: bool = False,
        **_: Any,
    ) -> str:
        if _demo_active(demo_mode):
            return json.dumps({
                "status": "demo",
                "incident_id": incident_id,
                "message": "Post-mortem save simulated (DEMO_MODE)",
            })
        try:
            json.loads(postmortem_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"postmortem_json is not valid JSON: {exc}") from exc
        out = _POSTMORTEMS_DIR / f"{incident_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(postmortem_json)
        return json.dumps({"status": "saved", "path": str(out)})


class NotifyTool(Tool):
    """Send an incident notification to a Slack channel.

    REQUIRES_CONFIRMATION — never sends without explicit operator approval.
    """

    @property
    def name(self) -> str:
        return "notify"

    @property
    def description(self) -> str:
        return (
            "Send a post-mortem completion notification to a Slack channel. "
            "Use after the post-mortem has been saved. Requires operator confirmation."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
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
    def permission(self) -> Permission:
        return Permission.REQUIRES_CONFIRMATION

    def execute(
        self,
        *,
        channel: str,
        message: str,
        incident_id: str,
        demo_mode: bool = False,
        **_: Any,
    ) -> str:
        if _demo_active(demo_mode):
            return json.dumps({
                "status": "demo",
                "channel": channel,
                "message": "Notification simulated (DEMO_MODE)",
            })
        return json.dumps({"error": "No Slack backend configured. Set DEMO_MODE=true."})
