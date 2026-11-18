"""Write each document's allowed roles on its chunks in every Qdrant collection (step 28, D77). Idempotent.

    uv run python scripts/apply_document_roles.py

Metadata only: nothing is chunked or embedded again. Run it after changing the documents of policy/roles.yaml.
A chunk that gets no value stays invisible to every role.
"""
from qdrant_client import models

from rag_calorvia.etl.index import ACCESS_FIELD, get_qdrant
from rag_calorvia.rag.permissions import allowed_roles


def document_filter(path):
    return models.Filter(must=[models.FieldCondition(key="document", match=models.MatchValue(value=path))])


def documents_of(qdrant, name):
    paths, offset = set(), None
    while True:
        points, offset = qdrant.scroll(name, limit=1000, offset=offset, with_payload=["document"])
        paths |= {p.payload["document"] for p in points}
        if offset is None:
            return paths


def main():
    qdrant = get_qdrant()
    for collection in (c.name for c in qdrant.get_collections().collections):
        qdrant.create_payload_index(collection, ACCESS_FIELD, models.PayloadSchemaType.KEYWORD, wait=True)
        paths = documents_of(qdrant, collection)
        for path in sorted(paths):
            qdrant.set_payload(collection, {ACCESS_FIELD: allowed_roles(path)}, points=document_filter(path), wait=True)
        missing = qdrant.count(collection, exact=True, count_filter=models.Filter(
            must=[models.IsEmptyCondition(is_empty=models.PayloadField(key=ACCESS_FIELD))])).count
        print(f"{collection}: {len(paths)} documents, {missing} chunks readable by no role")


if __name__ == "__main__":
    main()
