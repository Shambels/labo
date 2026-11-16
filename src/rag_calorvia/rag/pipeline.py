"""The RAG: question -> chunks -> answer. Scripts, evaluation and the UI call this module, never the steps directly."""
import time

from qdrant_client import models

from rag_calorvia.rag.generate import generate
from rag_calorvia.rag.rerank import rerank
from rag_calorvia.rag.search import search
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


def retrieve(question, config):
    """The top_k chunks for a question (translate, search, then rerank), with the time of each stage.

    Enough on its own for the retrieval metrics: experiments that only change retrieval skip generation.
    The reranker always compares the chunks with the original (French) question.
    """
    start = time.perf_counter()
    versions = translate_question(question, config)  # {'fr': question} when [search] translate is off
    translate_ms = elapsed_ms(start)

    start = time.perf_counter()
    candidates = search(question, config, query_filter=status_filter(config), versions=versions)
    search_ms = elapsed_ms(start)

    start = time.perf_counter()
    chunks = rerank(question, candidates, config)
    rerank_ms = elapsed_ms(start)
    timings = {"search_ms": search_ms, "rerank_ms": rerank_ms}
    if len(versions) > 1:
        timings = {"translate_ms": translate_ms, **timings}
    return {"chunks": chunks, "versions": versions, "timings": timings}


def context_order(chunks, config):
    """The chunks as the LLM sees them. [generation] order = "chronological" (step 8): sorted by date, oldest first,
    so the latest decision is the one closest to the question; undated chunks first (their date can't rank them).
    Default "rank": the reranker's order. Python's sort is stable: chunks of the same date keep their rank order."""
    if config["generation"].get("order", "rank") != "chronological":
        return chunks
    return sorted(chunks, key=lambda chunk: chunk.get("doc_date") or "")


def answer(question, config):
    """The full RAG: {answer, chunks, context, latency_ms, timings, prompt_tokens, completion_tokens, finish_reason}.

    chunks: in the reranker's order (the retrieval metrics); context: in the order given to the LLM, the one its
    citations [n] refer to."""
    result = retrieve(question, config)
    context = context_order(result["chunks"], config)

    start = time.perf_counter()
    generation = generate(question, context, config)
    result["timings"]["generate_ms"] = elapsed_ms(start)
    return {**generation, **result, "context": context, "latency_ms": sum(result["timings"].values())}
