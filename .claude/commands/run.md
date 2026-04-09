Run the post-mortem pipeline for a resolved incident.

Usage: /run --incident-id INC-XXXX --title "..." --severity SEV1|SEV2|SEV3|SEV4 --started-at ISO8601 --resolved-at ISO8601 --services svc1 svc2 --slack-channel "#channel" --reported-by name [--demo-mode]

Execute: python scripts/run_postmortem.py $ARGUMENTS
