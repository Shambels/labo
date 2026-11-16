"""Experiments: run one configuration on the dev set and store everything in PostgreSQL.

The judge (DeepEval) is a second pass, run later on the stored answers: the generator and the judge don't fit
on the GPU together.
"""
import copy
import logging
import time

from rag_calorvia import db
from rag_calorvia.etl.index import index_corpus
from rag_calorvia.evaluation.dataset import align_with_registry, load_questions
from rag_calorvia.evaluation.metrics import answer_scores, redundancy_scores, retrieval_scores
from rag_calorvia.rag.generate import load_system_prompt
from rag_calorvia.rag.pipeline import answer, retrieve

logger = logging.getLogger(__name__)

STORED_CHUNK_FIELDS = ["document", "chunk_index", "search_score", "rerank_score", "text"]


def stored_config(config):
    """The config as stored with the experiment: the TOML, plus the prompt text (the file may change later)."""
    stored = copy.deepcopy(config)
    if config["generation"]["enabled"]:
        stored["generation"]["system_prompt_text"] = load_system_prompt(config)
    return stored


def flatten(config, prefix=""):
    """{"generation": {"temperature": 0}} -> {"generation.temperature": 0}"""
    flat = {}
    for key, value in config.items():
        if isinstance(value, dict):
            flat |= flatten(value, f"{prefix}{key}.")
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def check_same_config(conn, name, config):
    """Runs with the same name are repeats, averaged together: refuse a run whose config differs from earlier ones.

    The stored config includes the prompt text, so an edited prompt file under an unchanged name is caught too.
    """
    previous_id = db.find_experiment(conn, name)
    if previous_id is None:
        return
    previous, new = flatten(db.load_experiment(conn, previous_id)[2]), flatten(config)
    changed = sorted(key for key in previous.keys() | new.keys() if previous.get(key) != new.get(key))
    if changed:
        raise ValueError(
            f"experiment {name!r} already ran (id {previous_id}) with another config: {', '.join(changed)}. "
            "Give this configuration another name."
        )


def score_rows(question, scores):
    """{metric: value} or {metric: (value, reason)} -> rows for db.insert_scores()."""
    rows = []
    for metric, value in scores.items():
        value, reason = value if isinstance(value, tuple) else (value, None)
        rows.append({"question_id": question["id"], "question_type": question["type"],
                     "metric": metric, "value": value, "reason": reason})
    return rows


def run_experiment(config):
    """Every dev question through the RAG: answers, retrieval scores, refusals. Returns the experiment id."""
    index_corpus(config)  # the collection must exist and be complete; nothing is rebuilt if it is
    generating = config["generation"]["enabled"]
    top_k = config["search"]["top_k"]

    with db.connect() as conn:
        db.create_tables(conn)
        questions = align_with_registry(load_questions("dev"), db.load_registry(conn))
        check_same_config(conn, config["name"], stored_config(config))
        experiment_id = db.start_experiment(conn, config["name"], stored_config(config))
        logger.info("experiment %d: %s (%d questions, generation %s)",
                    experiment_id, config["name"], len(questions), "on" if generating else "off")
        start = time.time()
        try:
            for i, question in enumerate(questions, 1):
                result = answer(question["question"], config) if generating else retrieve(question["question"], config)
                chunks = [{field: chunk.get(field) for field in STORED_CHUNK_FIELDS} for chunk in result["chunks"]]
                latency_ms = result["latency_ms"] if generating else sum(result["timings"].values())
                db.insert_answers(conn, experiment_id, [{
                    "question_id": question["id"], "chunks": chunks,
                    "answer": result["answer"] if generating else None, "latency_ms": latency_ms,
                }])
                scores = retrieval_scores(result["chunks"], question, top_k)
                scores |= redundancy_scores(result["chunks"], top_k)
                if generating:
                    scores |= answer_scores(result["answer"], result["chunks"], question)
                    scores["completion_tokens"] = float(result["completion_tokens"])
                scores |= {name: value for name, value in result["timings"].items()}  # search_ms, rerank_ms...
                db.insert_scores(conn, experiment_id, score_rows(question, scores))
                logger.info("[%d/%d] %s %s %.0f ms", i, len(questions), question["id"],
                            f"recall@5={scores['recall@5']:.2f}" if "recall@5" in scores else "", latency_ms)
        except BaseException:  # Ctrl+C included: the experiment must not stay 'running' forever
            db.finish_experiment(conn, experiment_id, "failed", time.time() - start)
            raise
        db.finish_experiment(conn, experiment_id, "done", time.time() - start)
        logger.info("experiment %d done in %.0f s", experiment_id, time.time() - start)
    return experiment_id
