#!/usr/bin/env python3
"""Entry point: trigger a post-mortem for a resolved incident.

Usage:
  python scripts/run_postmortem.py --incident-id INC-2026-0001 \
    --title "Redis pool exhaustion" --severity SEV1 \
    --started-at 2026-01-15T14:00:00Z \
    --resolved-at 2026-01-15T14:47:00Z \
    --services auth-service payment-service \
    --repos acme/auth-service \
    --slack-channel "#incident-2026-0001" \
    --reported-by oncall
"""
from __future__ import annotations

import argparse
import logging
import os
import pathlib
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run post-mortem for a resolved incident")
    p.add_argument("--incident-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--severity", choices=["SEV1", "SEV2", "SEV3", "SEV4"], required=True)
    p.add_argument("--started-at", required=True, help="ISO 8601 datetime")
    p.add_argument("--resolved-at", required=True, help="ISO 8601 datetime")
    p.add_argument("--services", nargs="+", required=True)
    p.add_argument("--repos", nargs="+", default=[])
    p.add_argument("--slack-channel", required=True)
    p.add_argument("--reported-by", required=True)
    p.add_argument("--metrics-namespace", default=None)
    p.add_argument("--demo-mode", action="store_true",
                   help="Run in demo mode without API calls")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.demo_mode:
        os.environ["DEMO_MODE"] = "true"

    from agents.orchestrator_agent import OrchestratorAgent
    from shared.models import Incident

    incident = Incident(
        id=args.incident_id,
        title=args.title,
        severity=args.severity,
        started_at=datetime.fromisoformat(args.started_at.replace("Z", "+00:00")),
        resolved_at=datetime.fromisoformat(args.resolved_at.replace("Z", "+00:00")),
        affected_services=args.services,
        involved_repos=args.repos,
        slack_channel=args.slack_channel,
        metrics_namespace=args.metrics_namespace,
        reported_by=args.reported_by,
    )

    demo = args.demo_mode or os.environ.get("DEMO_MODE", "").lower() == "true"
    orchestrator = OrchestratorAgent(demo_mode=demo)

    logger.info("Starting post-mortem for %s", incident.id)
    postmortem = orchestrator.run(incident)

    output_path = f"postmortems/{incident.id}.json"
    pathlib.Path("postmortems").mkdir(exist_ok=True)
    pathlib.Path(output_path).write_text(postmortem.model_dump_json(indent=2))

    logger.info("Post-mortem written to %s (draft=%s)", output_path, postmortem.draft)
    print(f"\nPost-mortem for {incident.id}:")
    print(f"  Executive summary: {postmortem.executive_summary}")
    print(f"  Root cause: {postmortem.root_cause.primary}")
    print(f"  Action items: {len(postmortem.action_items)}")
    print(f"  Revision count: {postmortem.revision_count}")
    print(f"  Draft: {postmortem.draft}")
    print(f"\nFull output: {output_path}")


if __name__ == "__main__":
    main()
