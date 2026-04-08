"""FastAPI SSE server for retro-pilot demo.

DEMO_MODE=true (default): serves pre-recorded scenario JSON with
simulated SSE streaming — no API calls, no credentials required.

DEMO_MODE=false + ANTHROPIC_API_KEY: live agent execution.

Endpoints:
  GET /scenarios            — list available scenarios
  GET /run/{scenario_id}    — stream agent steps as SSE events
  GET /scenario/{scenario_id} — return full scenario JSON
  GET /health               — health check
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

app = FastAPI(title="retro-pilot demo", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
STATIC_DIR = Path(__file__).parent / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_model=None)
async def root() -> FileResponse | JSONResponse:
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"message": "retro-pilot demo API"})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "demo_mode": os.environ.get("DEMO_MODE", "true")}


@app.get("/scenarios")
async def list_scenarios() -> dict[str, list[dict[str, str | int]]]:
    scenarios = []
    for f in sorted(SCENARIOS_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        scenarios.append({
            "id": data["id"],
            "label": data["label"],
            "incident_id": data["incident"]["id"],
            "severity": data["incident"]["severity"],
            "duration_minutes": _calc_duration(data["incident"]),
        })
    return {"scenarios": scenarios}


@app.get("/run/{scenario_id}", response_model=None)
async def stream_scenario(scenario_id: str) -> EventSourceResponse | JSONResponse:
    scenario_file = SCENARIOS_DIR / f"{scenario_id}.json"
    if not scenario_file.exists():
        return JSONResponse({"error": f"Scenario '{scenario_id}' not found"}, status_code=404)

    data = json.loads(scenario_file.read_text())

    async def event_generator():  # type: ignore[return]
        # Send incident info first
        yield {
            "event": "incident",
            "data": json.dumps(data["incident"]),
        }
        await asyncio.sleep(0.3)

        # Send similar incidents
        yield {
            "event": "similar_incidents",
            "data": json.dumps(data.get("similar_incidents_retrieved", [])),
        }
        await asyncio.sleep(0.5)

        # Stream pipeline steps
        for step in data.get("pipeline_steps", []):
            yield {
                "event": "step",
                "data": json.dumps(step),
            }
            delay = 0.4 if step.get("status") == "running" else 0.8
            await asyncio.sleep(delay)

        # Send final post-mortem
        yield {
            "event": "postmortem",
            "data": json.dumps(data.get("postmortem_final", {})),
        }
        await asyncio.sleep(0.2)

        yield {
            "event": "done",
            "data": json.dumps({"scenario_id": scenario_id}),
        }

    return EventSourceResponse(event_generator())


@app.get("/scenario/{scenario_id}", response_model=None)
async def get_scenario(scenario_id: str) -> dict | JSONResponse:
    scenario_file = SCENARIOS_DIR / f"{scenario_id}.json"
    if not scenario_file.exists():
        return JSONResponse({"error": f"Scenario '{scenario_id}' not found"}, status_code=404)
    return json.loads(scenario_file.read_text())


def _calc_duration(incident: dict[str, str]) -> int:
    from datetime import datetime, timezone
    start = datetime.fromisoformat(incident["started_at"])
    end = datetime.fromisoformat(incident["resolved_at"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return int((end - start).total_seconds() / 60)
