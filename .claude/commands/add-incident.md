Manually add a completed post-mortem to the knowledge base.

Usage: /add-incident path/to/postmortem.json

Execute: python3.11 -c "
from shared.models import PostMortem; from knowledge.vector_store import VectorStore
pm = PostMortem.model_validate_json(open('$ARGUMENTS').read())
store = VectorStore()
store.store(pm)
print(f'Added {pm.incident.id} to knowledge base.')
"
