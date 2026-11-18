"""Search: question -> candidate chunks from Qdrant, with dense, sparse (BM25) or hybrid search."""
from qdrant_client import models

from rag_calorvia.etl.index import bm25, collection_name, embed, get_qdrant

QUESTION_LANGUAGE = "fr"  # the language of the questions, and of the stemmer of an untranslated one


def query_text(question, config):
    """Harrier and Qwen3-Embedding expect a task instruction before the question; documents get none."""
    instruction = config["embedder"]["query_instruction"]
    return f"Instruct: {instruction}\nQuery: {question}" if instruction else question


def dense_vectors(questions, config):
    return embed([query_text(question, config) for question in questions], config["embedder"]["model"])


def fusion_query(search_config):
    """How the hybrid search merges the dense and sparse rankings."""
    fusion = search_config["fusion"]
    if fusion == "rrf":
        return models.RrfQuery(rrf=models.Rrf(k=search_config["rrf_k"]))
    if fusion == "dbsf":
        return models.FusionQuery(fusion=models.Fusion.DBSF)
    raise ValueError(f"unknown fusion: {fusion!r}")


def dense_request(question, config):
    return {"query": dense_vectors([question], config)[0], "using": "dense"}


def sparse_request(question, config):
    # The bare question: the embedder's instruction would only add noise to BM25
    return {"query": bm25(question), "using": "sparse"}


def hybrid_request(versions, config, query_filter):
    """One dense and one BM25 search per version of the question ({'fr': ..., 'nl': ..., 'en': ...}), each BM25
    with the stemmer of its language, then fused: a chunk found by several versions rises."""
    search_config = config["search"]
    limit = search_config["candidates"]
    prefetch = []
    for (language, text), vector in zip(versions.items(), dense_vectors(versions.values(), config)):
        prefetch += [models.Prefetch(query=vector, using="dense", limit=limit, filter=query_filter),
                     models.Prefetch(query=bm25(text, language), using="sparse", limit=limit, filter=query_filter)]
    return {"query": fusion_query(search_config), "prefetch": prefetch}


SINGLE_SEARCHES = {"dense": dense_request, "sparse": sparse_request}


def build_request(question, config, query_filter, versions):
    """The method-specific arguments of the Qdrant query."""
    method = config["search"]["method"]
    translated = bool(versions) and len(versions) > 1
    if translated and method != "hybrid":
        raise ValueError("question translation needs [search] method = 'hybrid'")
    if method == "hybrid":
        return hybrid_request(versions if translated else {QUESTION_LANGUAGE: question}, config, query_filter)
    if method in SINGLE_SEARCHES:
        return SINGLE_SEARCHES[method](question, config)
    raise ValueError(f"unknown search method: {method!r}")


def search(question, config, query_filter=None, versions=None):
    """The [search] candidates best chunks for a question: payload dicts plus the search score, best first.

    versions: the question and its translations ({'fr': question, 'nl': ...}); more than one turns the hybrid
    search into 2 searches per version. query_filter (a models.Filter) also applies to every prefetch.
    """
    points = get_qdrant().query_points(
        collection_name(config),
        query_filter=query_filter,
        limit=config["search"]["candidates"],
        with_payload=True,
        **build_request(question, config, query_filter, versions),
    ).points
    return [{**point.payload, "search_score": point.score} for point in points]
