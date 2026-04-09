Run the weekly knowledge consolidation job to detect recurring patterns.

Usage: /consolidate

Execute: python3.11 -c "
from pathlib import Path; from shared.models import PostMortem
from knowledge.vector_store import VectorStore; from knowledge.consolidator import Consolidator
store = VectorStore()
postmortems = []
for f in Path('postmortems').glob('*.json'):
    try: postmortems.append(PostMortem.model_validate_json(f.read_text()))
    except Exception as e: print(f'Skipping {f}: {e}')
patterns = Consolidator(store).run(postmortems)
print(f'Found {len(patterns)} pattern(s).')
for p in patterns: print(f'\n{p[\"pattern_summary\"]}')
"
