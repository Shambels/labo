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


def within(query_filter, documents):
    """The question's filter (statuses, role, reference date) and "one of these documents"."""
    condition = models.FieldCondition(key="document", match=models.MatchAny(any=documents))
    if query_filter is None:
        return models.Filter(must=[condition])
    return models.Filter(must=[*(query_filter.must or []), condition], must_not=query_filter.must_not)


def hybrid_request(versions, config, query_filter, documents=None):
    """One dense and one BM25 search per version of the question ({'fr': ..., 'nl': ..., 'en': ...}), each BM25
    with the stemmer of its language, then fused: a chunk found by several versions rises.

    documents (step 41): the documents of the entities the question names; one more dense search of the first
    version, restricted to them, joins the fusion."""
    search_config = config["search"]
    limit = search_config["candidates"]
    prefetch, vectors = [], dense_vectors(versions.values(), config)
    for (language, text), vector in zip(versions.items(), vectors):
        prefetch += [models.Prefetch(query=vector, using="dense", limit=limit, filter=query_filter),
                     models.Prefetch(query=bm25(text, language), using="sparse", limit=limit, filter=query_filter)]
    if documents:
        prefetch.append(models.Prefetch(query=vectors[0], using="dense", limit=limit,
                                        filter=within(query_filter, documents)))
    return {"query": fusion_query(search_config), "prefetch": prefetch}


SINGLE_SEARCHES = {"dense": dense_request, "sparse": sparse_request}


def build_request(question, config, query_filter, versions, documents=None):
    """The method-specific arguments of the Qdrant query."""
    method = config["search"]["method"]
    translated = bool(versions) and len(versions) > 1
    if translated and method != "hybrid":
        raise ValueError("question translation needs [search] method = 'hybrid'")
    if method == "hybrid":
        return hybrid_request(versions if translated else {QUESTION_LANGUAGE: question}, config, query_filter,
                              documents)
    if method in SINGLE_SEARCHES:
        return SINGLE_SEARCHES[method](question, config)
    raise ValueError(f"unknown search method: {method!r}")


def search(question, config, query_filter=None, versions=None, documents=None):
    """The [search] candidates best chunks for a question: payload dicts plus the search score, best first.

    versions: the question and its translations ({'fr': question, 'nl': ...}); more than one turns the hybrid
    search into 2 searches per version. query_filter (a models.Filter) also applies to every prefetch.
    documents (step 41): the documents of the entities the question names, searched once more on their own.
    """
    points = get_qdrant().query_points(
        collection_name(config),
        query_filter=query_filter,
        limit=config["search"]["candidates"],
        with_payload=True,
        **build_request(question, config, query_filter, versions, documents),
    ).points
    return [{**point.payload, "search_score": point.score} for point in points]
