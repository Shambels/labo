"""The RAG: question -> chunks -> answer. Scripts, evaluation and the UI call this module, never the steps directly."""
import time

from rag_calorvia.rag.generate import generate
from rag_calorvia.rag.rerank import rerank
from rag_calorvia.rag.search import search
from rag_calorvia.rag.translate import translate_question


def elapsed_ms(start):
    return (time.perf_counter() - start) * 1000


def retrieve(question, config):
    """The top_k chunks for a question (translate, search, then rerank), with the time of each stage.

    Enough on its own for the retrieval metrics: experiments that only change retrieval skip generation.
    The reranker always compares the chunks with the original (French) question.
    """
    start = time.perf_counter()
    versions = translate_question(question, config)  # {'fr': question} when [search] translate is off
    translate_ms = elapsed_ms(start)

    start = time.perf_counter()
    candidates = search(question, config, versions=versions)
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
