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
from rag_calorvia.etl.translate import search_text

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


def language_of(chunk):
    return chunk.get("language") or "fr"


def score_in_languages(model, question, chunks, versions, indexes):
    """[(index, score)] of these chunks, each against the version of the question in its language."""
    versions = {**versions, "fr": question}
    groups = {}
    for i in indexes:
        groups.setdefault(query_for(chunks[i], versions), []).append(i)
    scored = []
    for query, members in groups.items():   # one call per language present
        scored += [(members[j], s) for j, s in score(model, query, [chunks[i]["text"] for i in members])]
    return scored


def rerank(question, chunks, config, versions=None, translate=None):
    """The [search] top_k chunks the reranker finds most relevant, best first, with their rerank_score.

    translate (step 30d, with [reranker] translate_window = N): a function {languages} -> versions, called only when
    a non-French chunk is in the French ranking's top N. Then the non-French candidates are scored again against the
    question in their language; the French ones keep their score. Otherwise no translation is made at all.
    """
    model = config["reranker"]["model"]
    top_k = config["search"]["top_k"]
    if model == NO_RERANKER or not chunks:
        return chunks[:top_k]
    # The full chunk text, context line and headings included: they tell the reranker which document and which date
    window = config["reranker"].get("translate_window")
    if translate is not None and window:
        scored = sorted(score(model, question, [search_text(chunk) for chunk in chunks]), key=lambda p: p[1], reverse=True)
        if any(language_of(chunks[i]) != "fr" for i, _ in scored[:window]):
            versions = translate(sorted({language_of(c) for c in chunks} - {"fr"}))
            others = [i for i, _ in scored if query_for(chunks[i], {**versions, "fr": question}) != question]
            scored = [(i, s) for i, s in scored if i not in set(others)]
            scored += score_in_languages(model, question, chunks, versions, others)
    elif config["reranker"].get("query_language", "question") != "chunk" or not versions or len(versions) < 2:
        scored = score(model, question, [search_text(chunk) for chunk in chunks])
    else:
        scored = score_in_languages(model, question, chunks, versions, range(len(chunks)))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [{**chunks[i], "rerank_score": s} for i, s in scored[:top_k]]
