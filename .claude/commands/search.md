Semantic search across the post-mortem knowledge base.

Usage: /search "query about the incident type"

Execute: python3.11 -c "
from knowledge.vector_store import VectorStore
store = VectorStore()
results = store.retrieve('$ARGUMENTS')
for pm in results:
    print(f'{pm.incident.id}: {pm.incident.title}')
    print(f'  Root cause: {pm.root_cause.primary}')
    print()
"
