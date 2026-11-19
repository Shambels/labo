"""Reranking: the search candidates -> the [search] top_k best, scored by a cross-encoder.

Step 30: [reranker] query_language = "chunk" scores each candidate against the version of the question in the
chunk's language (the translations of [search] translate), French for any other language. Found in step 5 (Q024): the
Dutch question brought a Dutch contract's price chunk into the candidates, then the reranker, comparing it with the
French question, ranked it 11th. The scores of the different versions are merged into one ranking: a cross-encoder's
score is a relevance estimate for a (question, passage) pair, comparable across phrasings of the same question only
approximately, which is what the experiment measures.
"""
from functools import cache

import requests

from rag_calorvia.config import settings

NO_RERANKER = "none"  # [reranker] model = "none": keep the search order, to measure what the reranker brings


@cache
def get_session():
    """One HTTP session for every call: the connection to the server is reused."""
    return requests.Session()


def score(model, query, texts):
    """[(index in texts, relevance score)] for every text, against one query."""
    response = get_session().post(
        settings.rerank_url,
        json={"model": model, "query": query, "documents": texts, "top_n": len(texts)},
        timeout=60,
    )
    response.raise_for_status()
    return [(result["index"], result["relevance_score"]) for result in response.json()["results"]]


def query_for(chunk, versions):
    """The version of the question in the chunk's language, else the French one."""
    return versions.get(chunk.get("language"), versions["fr"])


def rerank(question, chunks, config, versions=None):
    """The [search] top_k chunks the reranker finds most relevant, best first, with their rerank_score."""
    model = config["reranker"]["model"]
    top_k = config["search"]["top_k"]
    if model == NO_RERANKER or not chunks:
        return chunks[:top_k]
    # The full chunk text, context line and headings included: they tell the reranker which document and which date
    if config["reranker"].get("query_language", "question") != "chunk" or not versions or len(versions) < 2:
        scored = score(model, question, [chunk["text"] for chunk in chunks])
    else:
        versions = {**versions, "fr": question}
        groups = {}
        for i, chunk in enumerate(chunks):
            groups.setdefault(query_for(chunk, versions), []).append(i)
        scored = []
        for query, indexes in groups.items():   # one call per language present among the candidates
            scored += [(indexes[j], s) for j, s in score(model, query, [chunks[i]["text"] for i in indexes])]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [{**chunks[i], "rerank_score": s} for i, s in scored[:top_k]]
