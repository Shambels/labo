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
    scored.sort(key=sort_key(config["reranker"].get("saturation")))
    ranked = [{**chunks[i], "rerank_score": s} for i, s in scored]
    if config["reranker"].get("recent_slots"):
        return with_recent(ranked, top_k, config["reranker"])
    return above_floor(ranked[:top_k], config["reranker"])


def sort_key(saturation=None):
    """Best score first. [reranker] saturation (step 40): scores at or above it count as equal, and those chunks keep
    the search's order (an index into the candidates, which come best first).

    Since step 34's issuer, a question naming "Calorvia" gives many chunks 0.999+ (Q133: the whole top 5); the
    differences between them are noise in the fourth decimal, and the order of the extracts was left to chance."""
    if saturation is None:
        return lambda pair: -pair[1]
    return lambda pair: (-min(pair[1], saturation), pair[0])


def above_floor(top, options):
    """[reranker] min_score (step 40): beyond the first `min_score_from` chunks (5), only those scoring at least
    min_score are kept. Run 187 gave 10 chunks to every question; ranks 6 to 10 scored 0.14 to 0.48 at the median, and
    at 0.1 the cut keeps 8.25 on average and loses one evidence snippet of the 127 questions (Q149's)."""
    floor = options.get("min_score")
    if floor is None:
        return top
    keep = options.get("min_score_from", 5)
    return top[:keep] + [chunk for chunk in top[keep:] if chunk["rerank_score"] >= floor]


PRECISE = ("day", "month")   # a date that can say "newer": a document dated "2026" isn't newer than a June meeting


def precise_date(chunk):
    return (chunk.get("doc_date") or "") if chunk.get("date_precision") in PRECISE else ""


def with_recent(ranked, top_k, options):
    """Step 36: up to `recent_slots` chunks from just below the top_k (ranks top_k+1 to recent_window) are brought in,
    in place of the lowest of the top_k, when the reranker still finds them relevant (score >= recent_min_score) and
    they are newer than every chunk of the top_k (dates precise to the day or the month only).

    "Où en est le rappel de l'Aéris 12 ?" (Q008): the reranker scored a dozen chunks about the recall between 0.80 and
    0.99, all on topic; the five best were the launch (December 2025), the closure (March 2026) came ninth. Relevance
    has no notion of time: among chunks it scores alike, the latest is the one a status question needs. When nothing
    below the top_k is newer than all of it, nothing changes; the top_k is never reordered.
    """
    top = ranked[:top_k]
    newest = max((precise_date(c) for c in top), default="")
    below = ranked[top_k:options.get("recent_window", 10)]
    newer = [c for c in below if c["rerank_score"] >= options.get("recent_min_score", 0.5) and precise_date(c) > newest]
    recent = sorted(newer, key=precise_date, reverse=True)[:min(options["recent_slots"], top_k)]
    recent.sort(key=lambda c: -c["rerank_score"])
    return top[:top_k - len(recent)] + recent
