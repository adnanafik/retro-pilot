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
            text = self.path.read_text().strip()
            if text:
                self._data = json.loads(text)

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
