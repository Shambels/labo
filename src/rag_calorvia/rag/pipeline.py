"""The RAG: question -> chunks -> answer. Scripts, evaluation and the UI call this module, never the steps directly."""
import time

from qdrant_client import models

from rag_calorvia.etl.chunk import ACCESS_FIELD
from rag_calorvia.rag.entities import card, entities_of, entity_documents
from rag_calorvia.rag.generate import generate
from rag_calorvia.rag.reference_date import date_condition, reference_date
from rag_calorvia.rag.rerank import rerank
from rag_calorvia.rag.search import search
from rag_calorvia.rag.siblings import add_siblings
from rag_calorvia.rag.translate import translate_question


def elapsed_ms(start):
    return (time.perf_counter() - start) * 1000


def status_filter(config):
    """[search] exclude_status (step 8): the registry statuses kept out of every search, e.g. ["draft", "archive"].

    A draft minute or an archived price list stays in the index (and in the registry) but is never a candidate:
    a must_not condition, applied inside each prefetch, so the 30 candidates are all eligible.
    """
    excluded = config["search"].get("exclude_status", [])
    if not excluded:
        return None
    return models.Filter(must_not=[models.FieldCondition(key="status", match=models.MatchAny(any=excluded))])


def role_condition(role):
    """Only the chunks this role may read (D77). A chunk without the field matches no role."""
    return models.FieldCondition(key=ACCESS_FIELD, match=models.MatchValue(value=role))


def question_filter(config, reference, role=None):
    """The Qdrant filter of a question: the status exclusions, the role's documents and, when the question has a
    reference date, only chunks dated on or before it (or undated). None when there is nothing to filter."""
    status = status_filter(config)
    must = ([date_condition(reference)] if reference is not None else []) + ([role_condition(role)] if role else [])
    if not must:
        return status
    return models.Filter(must=must, must_not=status.must_not if status else None)


def retrieve(question, config, role=None):
    """The top_k chunks for a question (translate, search, then rerank), with the time of each stage.

    Enough on its own for the retrieval metrics: experiments that only change retrieval skip generation.
    The reranker compares the chunks with the original (French) question, or with its version in each chunk's language
    ([reranker] query_language = "chunk", step 30). [search] translated_search = false (step 30c): the translations
    serve the reranker only, the search runs on the French question, so the candidates stay those of the untranslated
    configuration.
    """
    on_demand = bool(config["reranker"].get("translate_window"))   # step 30d: translate later, only if needed
    start = time.perf_counter()
    versions = {"fr": question} if on_demand else translate_question(question, config)  # {'fr'} when translate is off
    translate_ms = elapsed_ms(start)
    made = {}

    def translate(languages):
        """Called by the reranker when a non-French chunk is in its French top N; timed apart."""
        begin = time.perf_counter()
        made["versions"] = translate_question(question, config, languages)
        made["ms"] = elapsed_ms(begin)
        return made["versions"]

    start = time.perf_counter()
    reference = reference_date(question, config)  # None when [search] reference_date is off
    reference_ms = elapsed_ms(start)

    start = time.perf_counter()
    entities = entities_of(question, config)   # step 41: [] without [search] entities
    documents = entity_documents(entities, config, role) if entities else None
    entities_ms = elapsed_ms(start)

    start = time.perf_counter()
    searched = versions if config["search"].get("translated_search", True) else {"fr": question}
    query_filter = question_filter(config, reference, role)
    candidates = search(question, config, query_filter=query_filter, versions=searched,
                        **({"documents": documents} if documents else {}))
    search_ms = elapsed_ms(start)

    start = time.perf_counter()
    chunks = rerank(question, candidates, config, versions, translate if on_demand else None)
    rerank_ms = elapsed_ms(start)
    timings = {"search_ms": search_ms, "rerank_ms": rerank_ms}
    if config["reranker"].get("siblings"):   # step 40: the other chunks of the documents kept
        start = time.perf_counter()
        chunks = add_siblings(question, chunks, config, query_filter, made.get("versions", versions))
        timings["siblings_ms"] = elapsed_ms(start)
    if made:
        versions = made["versions"]
        timings = {"translate_ms": made["ms"], **timings, "rerank_ms": rerank_ms - made["ms"]}
    elif len(versions) > 1:
        timings = {"translate_ms": translate_ms, **timings}
    if config["search"].get("reference_date", False):
        timings = {"reference_ms": reference_ms, **timings}
    if config["search"].get("entities"):
        timings = {"entities_ms": entities_ms, **timings}
    return {"chunks": chunks, "versions": versions, "reference": reference, "timings": timings,
            "entities": [entity["name"] for entity in entities]}


def context_order(chunks, config):
    """The chunks as the LLM sees them. [generation] order = "chronological" (step 8): sorted by date, oldest first,
    so the latest decision is the one closest to the question; undated chunks first (their date can't rank them).
    Default "rank": the reranker's order. Python's sort is stable: chunks of the same date keep their rank order."""
    if config["generation"].get("order", "rank") != "chronological":
        return chunks
    return sorted(chunks, key=lambda chunk: chunk.get("doc_date") or "")


def answer(question, config, role=None):
    """The full RAG: {answer, chunks, context, latency_ms, timings, prompt_tokens, completion_tokens, finish_reason}.

    chunks: in the reranker's order (the retrieval metrics); context: in the order given to the LLM, the one its
    citations [n] refer to."""
    result = retrieve(question, config, role)
    context = context_order(result["chunks"], config)
    entity_card = card(entities_of(question, config), role) if config["generation"].get("entity_cards") else None
    if entity_card:   # step 41: what the named entities are, as the last extract
        context = [*context, entity_card]

    start = time.perf_counter()
    generation = generate(question, context, config, role)
    result["timings"]["generate_ms"] = elapsed_ms(start)
    return {**generation, **result, "context": context, "latency_ms": sum(result["timings"].values())}
