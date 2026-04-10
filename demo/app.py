"""FastAPI SSE server for retro-pilot demo.

DEMO_MODE=true (default): serves pre-recorded scenario JSON with
simulated SSE streaming — no API calls, no credentials required.

DEMO_MODE=false + ANTHROPIC_API_KEY: live agent execution.

Endpoints:
  GET /scenarios                         — list available scenarios
  GET /run/{scenario_id}                 — stream agent steps as SSE events
  GET /scenario/{scenario_id}            — return full scenario JSON
  GET /health                            — health check
  GET /postmortems                       — list post-mortems with status/severity filters
  GET /postmortems/{incident_id}         — get post-mortem detail with review history
  POST /postmortems/{incident_id}/review — record a review action (approve/request_changes/reject)
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

app = FastAPI(title="retro-pilot demo", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
STATIC_DIR = Path(__file__).parent / "static"
MOCK_POSTMORTEMS_FILE = Path(__file__).parent / "mock_postmortems.json"
REVIEWS_FILE = Path(__file__).parent / "reviews.json"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ReviewRequest(BaseModel):
    action: Literal["approve", "request_changes", "reject"]
    reviewer: str
    comment: str | None = None


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
    start = datetime.fromisoformat(incident["started_at"])
    end = datetime.fromisoformat(incident["resolved_at"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return int((end - start).total_seconds() / 60)


_ACTION_TO_STATUS = {
    "approve": "approved",
    "request_changes": "needs_changes",
    "reject": "rejected",
}


def _load_postmortems() -> list[dict]:
    if not MOCK_POSTMORTEMS_FILE.exists():
        return []
    return json.loads(MOCK_POSTMORTEMS_FILE.read_text())


def _load_reviews() -> list[dict]:
    if not REVIEWS_FILE.exists():
        return []
    return json.loads(REVIEWS_FILE.read_text())


def _derive_status(incident_id: str, reviews: list[dict]) -> str:
    matching = [r for r in reviews if r["incident_id"] == incident_id]
    if not matching:
        return "draft"
    latest = max(matching, key=lambda r: r["timestamp"])
    return _ACTION_TO_STATUS.get(latest["action"], latest["action"])


@app.get("/postmortems")
async def list_postmortems(status: str = "all", severity: str = "all") -> list[dict]:
    postmortems = _load_postmortems()
    reviews = _load_reviews()
    # Pre-group reviews by incident_id to avoid O(n²) scan
    reviews_by_id: dict[str, list[dict]] = {}
    for r in reviews:
        reviews_by_id.setdefault(r["incident_id"], []).append(r)
    result = []
    for pm in postmortems:
        inc = pm["incident"]
        inc_reviews = sorted(reviews_by_id.get(inc["id"], []), key=lambda r: r["timestamp"])
        latest = inc_reviews[-1] if inc_reviews else None
        derived_status = _ACTION_TO_STATUS.get(latest["action"], latest["action"]) if latest else "draft"
        if status != "all" and derived_status != status:
            continue
        if severity != "all" and inc["severity"] != severity:
            continue
        result.append({
            "id": inc["id"],
            "title": inc["title"],
            "severity": inc["severity"],
            "started_at": inc["started_at"],
            "resolution_duration_minutes": pm["resolution_duration_minutes"],
            "evaluator_total": pm["evaluator_scores"]["total"],
            "status": derived_status,
            "last_reviewer": latest["reviewer"] if latest else None,
            "last_reviewed_at": latest["timestamp"] if latest else None,
        })
    result.sort(key=lambda x: x["started_at"], reverse=True)
    return result


@app.get("/postmortems/{incident_id}", response_model=None)
async def get_postmortem(incident_id: str) -> dict | JSONResponse:
    postmortems = _load_postmortems()
    reviews = _load_reviews()
    pm = next((p for p in postmortems if p["incident"]["id"] == incident_id), None)
    if pm is None:
        return JSONResponse({"error": f"Post-mortem '{incident_id}' not found"}, status_code=404)
    matching_reviews = sorted(
        [r for r in reviews if r["incident_id"] == incident_id],
        key=lambda r: r["timestamp"],
    )
    return {
        "postmortem": pm,
        "review_history": matching_reviews,
        "status": _derive_status(incident_id, reviews),
    }


@app.post("/postmortems/{incident_id}/review", response_model=None)
async def review_postmortem(incident_id: str, body: ReviewRequest) -> dict | JSONResponse:
    if not body.reviewer.strip():
        raise HTTPException(status_code=422, detail="Reviewer name is required")
    if body.action == "request_changes" and not (body.comment and body.comment.strip()):
        raise HTTPException(status_code=422, detail="Comment is required when requesting changes")
    postmortems = _load_postmortems()
    if not any(p["incident"]["id"] == incident_id for p in postmortems):
        return JSONResponse({"error": f"Post-mortem '{incident_id}' not found"}, status_code=404)
    reviews = _load_reviews()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry: dict = {
        "review_id": str(uuid.uuid4()),
        "incident_id": incident_id,
        "action": body.action,
        "reviewer": body.reviewer.strip(),
        "comment": body.comment.strip() if body.comment else None,
        "timestamp": now,
    }
    reviews.append(entry)
    REVIEWS_FILE.write_text(json.dumps(reviews, indent=2))
    new_status = _ACTION_TO_STATUS.get(entry["action"], entry["action"])
    return {"status": new_status, "recorded_at": now}
