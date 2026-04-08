# retro-pilot Phase Build Design

**Date:** 2026-04-08  
**Status:** Approved  
**Approach:** Architectural layers (5 phases, 1 branch + PR per phase)

---

## Context

retro-pilot is a greenfield repo. The CLAUDE.md defines a strict 22-step build order.
ops-pilot (`/Users/adnankhan/dev/ops-pilot`) is the companion repo — read for pattern
reference only, no direct code copying.

---

## Phase Overview

| Phase | Branch | PR Title | Build Steps |
|-------|--------|----------|-------------|
| 1 | `phase/1-foundation` | feat: foundation — models, tool registry, base agent loop | 1–4 |
| 2 | `phase/2-knowledge` | feat: knowledge layer — ChromaDB vector store, embedder, evaluator (LLM-as-judge) | 5–8 |
| 3 | `phase/3-agents` | feat: agent pipeline — orchestrator, 6 specialist agents, revision loop | 9–14 |
| 4 | `phase/4-tests` | test: full pytest suite — ≥85% coverage on agents and evaluator | 15 |
| 5 | `phase/5-demo-ci` | feat: demo, CI, docs — portfolio-ready delivery | 16–22 |

---

## Phase 1 — Foundation (`phase/1-foundation`)

**Story:** Define the entire data contract and execution engine before any agents exist.

**Files:**
```
pyproject.toml
Dockerfile
docker-compose.yml
shared/models.py          # All Pydantic models: Incident, Evidence, Timeline, RootCause,
                          #   ActionItem, PostMortem, EvaluationScore + sub-models
shared/config.py          # YAML config + env-var substitution + validation
shared/context_budget.py  # Token estimation + Strategy A compaction
shared/trust_context.py   # AuditLog (JSONL, atomic writes, per-day rotation) + ExplanationGenerator
shared/tenant_context.py  # Per-deployment isolation + sliding window rate limiter
shared/state_store.py     # JSON state persistence (dedup across restarts)
tools/registry.py         # ToolRegistry with permission tiers: READ_ONLY, WRITE,
                          #   REQUIRES_CONFIRMATION, DANGEROUS
tools/read_tools.py       # GetLogsTool, GetMetricsTool, GetGitHistoryTool,
                          #   GetSlackThreadTool, GetServiceMapTool
tools/write_tools.py      # SavePostmortemTool, NotifyTool (REQUIRES_CONFIRMATION)
agents/base_agent.py      # AgentLoop execution engine (tool-use loop, not single prompts)
```

**PR gates:** Models import cleanly. ToolRegistry permission tiers are unit-testable.
AgentLoop runs a minimal mock tool-use cycle without error.

---

## Phase 2 — Knowledge Layer (`phase/2-knowledge`)

**Story:** The two architectural features unique to retro-pilot — semantic similarity and
LLM-as-judge — exist and work in isolation before the agent pipeline is built.

**Files:**
```
knowledge/embedder.py       # sentence-transformers all-MiniLM-L6-v2 wrapper
knowledge/vector_store.py   # ChromaDB (local persistent) — embed, store, retrieve
                            #   top-3 by cosine similarity > 0.65, returns full PostMortem
knowledge/consolidator.py   # Weekly job: finds similarity > 0.90, merges lessons +
                            #   action items into pattern records
evaluator/rubric.py         # Structured scoring rubric — 5 dimensions, weighted 0.0→1.0
evaluator/scorer.py         # Rubric → EvaluationScore, generates specific revision_brief
agents/evaluator_agent.py   # LLM-as-judge: scores PostMortem draft, returns EvaluationScore
```

**Rubric dimensions (weights):**
- Timeline completeness (0.20)
- Root cause clarity (0.25)
- Action item quality (0.25)
- Executive summary clarity (0.15)
- Similar incidents referenced (0.15)

**Pass threshold:** total >= 0.80

**PR gates:** Embedder produces consistent vectors. Vector store round-trips (embed →
store → retrieve → similarity filter). Scorer returns correct pass/fail on known
fixture inputs.

---

## Phase 3 — Agent Pipeline (`phase/3-agents`)

**Story:** Full orchestration flow wired together — parallel evidence workers, typed
model passing between all agents, and the 3-cycle revision loop.

**Files:**
```
agents/evidence_collector.py   # Parallel sub-agents: LogWorker, MetricsWorker,
                               #   GitWorker, SlackWorker (each READ_ONLY scoped)
agents/timeline_builder.py     # Evidence → Timeline; correlates across sources,
                               #   identifies first_signal_at, detection_lag
agents/root_cause_analyst.py   # Evidence + Timeline + similar_incidents → RootCause;
                               #   primary vs contributing vs trigger distinction
agents/action_item_generator.py # RootCause + similar_incidents → list[ActionItem];
                               #   checks if prior incident action items were completed
agents/postmortem_writer.py    # Assembles all outputs → PostMortem; writes
                               #   executive_summary (≤3 sentences), lessons_learned
agents/orchestrator_agent.py   # Top-level coordinator; runs full sequence + revision loop
                               #   (max 3 cycles); saves to ChromaDB on pass
scripts/run_postmortem.py      # CLI entry point: triggered after incident resolution
```

**Orchestration sequence:**
```
Incident
  → ChromaDB (retrieve similar_incidents)
  → EvidenceCollector (parallel workers)
  → TimelineBuilder
  → RootCauseAnalyst
  → ActionItemGenerator
  → PostMortemWriter
  → EvaluatorAgent → [pass] ChromaDB save + NotifyTool
                   → [fail, <3 cycles] PostMortemWriter revision → re-evaluate
                   → [fail, 3 cycles] save draft=True, flag for human review
```

**PR gates:** Orchestrator completes a full dry run with mock tools (DEMO_MODE=true).
Revision loop correctly terminates at 3 cycles. All inter-agent data uses typed Pydantic
models — no raw dicts cross boundaries.

---

## Phase 4 — Tests (`phase/4-tests`)

**Story:** ≥85% coverage on agent and evaluator logic. All tests green before demo work starts.

**Files:**
```
tests/conftest.py                    # Fixtures: sample_incident, mock_backend,
                                     #   mock_chroma, mock_embedder
tests/fixtures/                      # Sample incident data, log snippets, metrics
tests/test_orchestrator.py
tests/test_evaluator.py              # Most important — rubric scoring coverage
tests/test_vector_store.py           # embed, store, retrieve, similarity ranking
tests/test_timeline_builder.py
tests/test_root_cause_analyst.py
tests/test_action_item_generator.py
```

**PR gates:** `docker compose run --rm test` exits 0. Coverage report shows ≥85% on
`agents/` and `evaluator/`. No phase 5 work begins until this PR is merged.

---

## Phase 5 — Demo + CI + Polish (`phase/5-demo-ci`)

**Story:** Portfolio-ready. Zero-cost demo. GitHub Pages works. CI green. README tells the full story.

**Files:**
```
demo/scenarios/redis_cascade.json      # SEV1 — Redis connection pool exhaustion
demo/scenarios/deploy_regression.json  # SEV2 — silent dependency regression
demo/scenarios/certificate_expiry.json # SEV2 — TLS cert expiry in service mesh
demo/app.py                            # FastAPI SSE server, DEMO_MODE streaming
demo/static/index.html                 # Vanilla JS UI — agent pipeline + results panels
docs/index.html                        # GitHub Pages static version
docs/scenarios/                        # Same 3 JSON files served statically
.claude/commands/run.md
.claude/commands/evaluate.md
.claude/commands/search.md
.claude/commands/add-incident.md
.claude/commands/consolidate.md
.github/workflows/retro-pilot-ci.yml   # pytest + ruff + type checks
README.md                              # Portfolio-quality; Mermaid diagram; ops-pilot link
retro-pilot.example.yml               # Fully documented config template
```

**Each scenario JSON includes full agent output sequence:**
orchestrator → evidence → timeline → root_cause → action_items →
postmortem_draft → evaluation_score (with ≥1 revision cycle) → postmortem_final →
knowledge_base_entry

**PR gates:** `DEMO_MODE=true` runs all 3 scenarios without API calls. GitHub Pages
index.html works by opening the file locally. CI workflow passes on the PR.

---

## Key Constraints

- ops-pilot patterns are referenced, never copied
- All inter-agent data uses Pydantic v2 models — no raw dicts
- draft=True on all PostMortem output until human approves
- Revision loop hard cap: 3 cycles (configurable in retro-pilot.yml)
- DEMO_MODE=true default for GitHub Pages and docker compose demo
