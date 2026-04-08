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
        self._data: dict[str, dict[str, dict]] = {}
        if self.path.exists():
            raw = self.path.read_text().strip()
            if raw:
                self._data = json.loads(raw)

    def set(self, incident_id: str, namespace: str, value: dict) -> None:
        if incident_id not in self._data:
            self._data[incident_id] = {}
        self._data[incident_id][namespace] = value
        self._flush()

    def get(self, incident_id: str, namespace: str) -> dict | None:
        return self._data.get(incident_id, {}).get(namespace)

    def get_all(self, incident_id: str) -> dict[str, dict]:
        return dict(self._data.get(incident_id, {}))

    def delete(self, incident_id: str, namespace: str) -> None:
        if incident_id in self._data:
            self._data[incident_id].pop(namespace, None)
            if not self._data[incident_id]:
                del self._data[incident_id]
        self._flush()

    def _flush(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=self.path.parent, delete=False, suffix=".tmp"
        ) as tmp:
            json.dump(self._data, tmp, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, self.path)
