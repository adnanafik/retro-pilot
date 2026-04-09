Score an existing post-mortem JSON file against the rubric.

Usage: /evaluate path/to/postmortem.json

Execute: python3.11 -c "
import json; from shared.models import PostMortem; from evaluator.scorer import score_postmortem
pm = PostMortem.model_validate_json(open('$ARGUMENTS').read())
score = score_postmortem(pm)
print(f'Score: {score.total:.2f} | Passed: {score.passed}')
if score.revision_brief: print(f'Issues: {score.revision_brief}')
"
