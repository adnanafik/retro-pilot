# Post-Mortem Review UI — Design Spec

**Date:** 2026-04-09
**Phase:** 6

---

## Goal

Add a "Review" tab to the existing demo UI so engineers can browse generated post-mortems, read the full detail, and record an approval, change-request, or rejection — with reviewer name persisted server-side. Works out-of-the-box with mock data; upgrading to live ChromaDB data requires a one-line change in the FastAPI route.

---

## Architecture

New "Review" tab inside `demo/static/index.html` — same page, toggled by tab click. The existing FastAPI server (`demo/app.py`) gains three new routes. Mock post-mortems live in `demo/mock_postmortems.json` (3 entries, one per existing scenario). Review actions persist to `demo/reviews.json` (created automatically on first write). Effective status is derived at query time from the most recent review entry for each post-mortem (defaulting to `draft` if none exists).

To go live: replace the `mock_postmortems.json` read in `GET /postmortems` with a ChromaDB query — no other changes needed.

---

## New Files

| File | Purpose |
|------|---------|
| `demo/mock_postmortems.json` | 3 mock post-mortems (redis-cascade: draft, deploy-regression: approved, certificate-expiry: needs_changes) with full evaluator scores |
| `demo/reviews.json` | Append-only log of review actions; auto-created on first write |
| `tests/test_review_api.py` | pytest tests for all three new endpoints |

---

## Modified Files

| File | Change |
|------|--------|
| `demo/app.py` | Add 3 new FastAPI routes |
| `demo/static/index.html` | Add "Review" tab, list view, detail view, action bar |

---

## API Endpoints

### `GET /postmortems`
Returns list of post-mortems with derived status.

Query params:
- `status` — one of `draft | approved | needs_changes | rejected | all` (default `all`)
- `severity` — one of `SEV1 | SEV2 | SEV3 | SEV4 | all` (default `all`)

Response (array):
```json
[
  {
    "id": "INC-2026-0142",
    "title": "Redis Connection Pool Exhaustion",
    "severity": "SEV1",
    "started_at": "2026-01-15T14:00:00Z",
    "resolution_duration_minutes": 47,
    "evaluator_total": 0.91,
    "status": "draft",
    "last_reviewer": null,
    "last_reviewed_at": null
  }
]
```

### `GET /postmortems/{id}`
Returns full post-mortem detail + review history.

Response:
```json
{
  "postmortem": { /* full PostMortem fields */ },
  "evaluator_scores": {
    "total": 0.91,
    "timeline_completeness": 0.90,
    "root_cause_clarity": 0.95,
    "action_item_quality": 0.88,
    "executive_summary_clarity": 0.93,
    "similar_incidents_referenced": 0.85
  },
  "review_history": [
    {
      "action": "request_changes",
      "reviewer": "Alice",
      "comment": "Root cause needs more detail.",
      "timestamp": "2026-01-15T16:00:00Z"
    }
  ],
  "status": "needs_changes"
}
```

404 if `id` not found.

### `POST /postmortems/{id}/review`
Records a review action.

Request body:
```json
{
  "action": "approve",
  "reviewer": "Alice",
  "comment": "Looks good."
}
```

- `action`: required, one of `approve | request_changes | reject`
- `reviewer`: required, non-empty string
- `comment`: optional string (required when action is `request_changes`)

Returns 422 if `reviewer` is empty or `comment` missing when action is `request_changes`.
Returns 404 if `id` not found.

Response on success:
```json
{ "status": "approved", "recorded_at": "2026-01-15T16:05:00Z" }
```

---

## Mock Data Shape (`demo/mock_postmortems.json`)

Three entries — one per existing scenario:

| ID | Title | Severity | Status | Evaluator Total |
|----|-------|----------|--------|----------------|
| INC-2026-0142 | Redis Connection Pool Exhaustion | SEV1 | draft | 0.74 (pre-revision) |
| INC-2026-0156 | Deploy Regression — Token Validation | SEV2 | approved | 0.91 |
| INC-2026-0171 | Certificate Expiry in Service Mesh | SEV2 | needs_changes | 0.68 |

Each entry includes: full `incident` fields, `executive_summary`, `root_cause` (primary + contributing factors + trigger + blast_radius + confidence), `action_items` (3–4 items each), `timeline` (5 events), `lessons_learned`, `evaluator_scores` per dimension, `revision_count`, `generated_at`.

`demo/reviews.json` pre-populated with matching review entries so the derived status matches the above table on first load.

---

## UI — Review Tab

### Tab Bar
```
[ Pipeline ]  [ Review ]
```
Tab bar replaces the current "retro-pilot" header area. Active tab is underlined. Switching tabs shows/hides the respective panels with no page reload.

### List View (left panel, ~320px)
- Filter bar at top: two `<select>` dropdowns — Status (All / Draft / Approved / Needs Changes / Rejected) and Severity (All / SEV1 / SEV2 / SEV3)
- Each card shows:
  - Severity badge (same color coding as pipeline tab: SEV1=red, SEV2=orange)
  - Incident title
  - Date (formatted: "Jan 15, 2026")
  - Evaluator score badge (e.g. `0.91`) — green ≥0.80, amber 0.60–0.79, red <0.60
  - Status badge — draft=grey, approved=green, needs_changes=amber, rejected=red
  - Reviewer name (if reviewed): small grey text "Reviewed by Alice"
- Cards are sorted newest-first by `started_at`
- Clicking a card opens the detail view and highlights the selected card

### Detail View (main panel)
Replaces the pipeline panel when a card is selected. Sections:

**Header**
- Incident title, severity badge, duration ("47 min outage"), affected services (comma list)

**Evaluator Score Breakdown**
- 5 horizontal score bars (labelled): Timeline Completeness, Root Cause Clarity, Action Item Quality, Executive Summary Clarity, Similar Incidents Referenced
- Total score prominent at top-right, pass/fail indicator (≥0.80 = Passed)

**Executive Summary**
- Plain text block

**Root Cause**
- Primary (bold), Contributing Factors (bullet list), Trigger, Blast Radius, Confidence badge

**Action Items**
- Table: Title | Owner | Deadline | Priority | Type | Acceptance Criteria

**Timeline**
- Condensed list of up to 5 most significant events: timestamp, description, source badge

**Lessons Learned**
- Bullet list

**Review History**
- Chronological list: action badge (Approved/Changes Requested/Rejected) + reviewer name + timestamp + comment (if any)
- Empty state: "No reviews yet"

**Action Bar** (pinned to bottom of detail view)
- Text input: "Your name" (required)
- Textarea: "Comment" (required for Request Changes, optional for others), placeholder text varies by action
- Three buttons: "Approve" (green), "Request Changes" (amber), "Reject" (red)
- Inline validation: red border + error text if reviewer name empty on submit
- On success: review history updates immediately, status badge in list updates

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Reviewer name empty on submit | Inline error "Reviewer name is required", no request sent |
| Comment missing for Request Changes | Inline error "Comment is required when requesting changes" |
| Network error on load | "Failed to load post-mortems. [Retry]" link |
| Network error on review submit | "Failed to save review. Try again." toast |
| Unknown ID (404) | Detail view shows "Post-mortem not found" |
| `reviews.json` missing | Created automatically on first POST |

---

## Tests (`tests/test_review_api.py`)

1. `GET /postmortems` returns all 3 mock entries
2. `?status=draft` returns only draft entries
3. `?severity=SEV1` returns only SEV1 entries
4. `POST /postmortems/{id}/review` with `approve` persists to reviews.json and derived status becomes `approved`
5. Approving an already-approved post-mortem is idempotent (status stays `approved`)
6. Missing `reviewer` returns 422
7. `request_changes` without `comment` returns 422
8. Unknown `id` returns 404
9. `GET /postmortems/{id}` returns review history in chronological order
10. `GET /postmortems/{id}` returns 404 for unknown id

---

## Out of Scope

- Authentication / multi-user sessions (reviewer name is free text, no login)
- Editing post-mortem content through the UI (review only, not edit)
- Pagination (3 mock entries; real deployment can add later)
- GitHub Pages static version of the review tab (requires a backend; static version remains pipeline-only)
