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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    """Appends tool-call records to a per-day JSONL file atomically."""

    def __init__(self, base_dir: Path | str = Path("audit")) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self) -> Path:
        date = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        return self.base_dir / f"audit-{date}.jsonl"

    def record(self, *, incident_id: str, tool_name: str,
               inputs: dict[str, Any], result: str, actor: str = "agent") -> None:
        record = {
            "ts": datetime.now(tz=UTC).isoformat(),
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
    """Generates pre-action explanations for REQUIRES_CONFIRMATION tools."""

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
