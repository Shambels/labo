"""Search: question -> candidate chunks from Qdrant, with dense, sparse (BM25) or hybrid search."""
from qdrant_client import models

from rag_calorvia.etl.index import bm25, collection_name, embed, get_qdrant


def query_text(question, config):
    """Harrier and Qwen3-Embedding expect a task instruction before the question; documents get none."""
    instruction = config["embedder"]["query_instruction"]
    return f"Instruct: {instruction}\nQuery: {question}" if instruction else question


def fusion_query(search):
    """How the hybrid search merges the dense and sparse rankings."""
    if search["fusion"] == "rrf":
        return models.RrfQuery(rrf=models.Rrf(k=search["rrf_k"]))
    if search["fusion"] == "dbsf":
        return models.FusionQuery(fusion=models.Fusion.DBSF)
    raise ValueError(f"unknown fusion: {search['fusion']!r}")


def multilingual_prefetch(versions, config, query_filter):
    """One dense and one BM25 search per version of the question ({'fr': ..., 'nl': ..., 'en': ...}), each BM25
    with the stemmer of its language. Fused by RRF with the rest: a chunk found by several versions rises."""
    limit = config["search"]["candidates"]
    dense = embed([query_text(text, config) for text in versions.values()], config["embedder"]["model"])
    prefetch = []
    for (language, text), vector in zip(versions.items(), dense):
        prefetch.append(models.Prefetch(query=vector, using="dense", limit=limit, filter=query_filter))
        prefetch.append(models.Prefetch(query=bm25(text, language), using="sparse", limit=limit, filter=query_filter))
    return prefetch


def search(question, config, query_filter=None, versions=None):
    """The [search] candidates best chunks for a question: payload dicts plus the search score, best first.

    versions: the question and its translations ({'fr': question, 'nl': ...}); more than one turns the hybrid
    search into 2 searches per version. query_filter (a models.Filter) also applies to every prefetch.
    """
    params = config["search"]
    method = params["method"]
    limit = params["candidates"]
    if versions and len(versions) > 1:
        if method != "hybrid":
            raise ValueError("question translation needs [search] method = 'hybrid'")
        points = get_qdrant().query_points(
            collection_name(config), query=fusion_query(params), prefetch=multilingual_prefetch(versions, config, query_filter),
            query_filter=query_filter, limit=limit, with_payload=True,
        ).points
        return [{**point.payload, "search_score": point.score} for point in points]
    # The BM25 vector uses the bare question: the instruction is for the embedder, its words would only add noise
    sparse = bm25(question)

    if method == "sparse":
        query, using, prefetch = sparse, "sparse", None
    else:
        dense = embed([query_text(question, config)], config["embedder"]["model"])[0]
        if method == "dense":
            query, using, prefetch = dense, "dense", None
        elif method == "hybrid":
            query, using = fusion_query(params), None
            prefetch = [
                models.Prefetch(query=dense, using="dense", limit=limit, filter=query_filter),
                models.Prefetch(query=sparse, using="sparse", limit=limit, filter=query_filter),
            ]
        else:
            raise ValueError(f"unknown search method: {method!r}")

    points = get_qdrant().query_points(
        collection_name(config),
        query=query,
        using=using,
        prefetch=prefetch,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
    ).points
    return [{**point.payload, "search_score": point.score} for point in points]
