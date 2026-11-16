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


def answer(question, config):
    """The full RAG: {answer, chunks, latency_ms, timings, prompt_tokens, completion_tokens, finish_reason}."""
    result = retrieve(question, config)

    start = time.perf_counter()
    generation = generate(question, result["chunks"], config)
    result["timings"]["generate_ms"] = elapsed_ms(start)
    return {**generation, **result, "latency_ms": sum(result["timings"].values())}
