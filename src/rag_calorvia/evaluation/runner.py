"""Experiments: run one configuration on the dev set and store everything in PostgreSQL.

The judge (DeepEval) is a second pass, run later on the stored answers: the generator and the judge don't fit
on the GPU together.
"""
import copy
import logging
import time
from pathlib import Path

from rag_calorvia import db
from rag_calorvia.etl.index import index_corpus
from rag_calorvia.etl.metadata import detect_language
from rag_calorvia.evaluation.dataset import HELD_OUT, align_with_registry, judge_sample, load_questions
from rag_calorvia.evaluation.metrics import answer_scores, redundancy_scores, retrieval_scores
from rag_calorvia.git_state import git_state
from rag_calorvia.rag.generate import load_system_prompt
from rag_calorvia.rag.pipeline import answer, retrieve

logger = logging.getLogger(__name__)

STORED_CHUNK_FIELDS = ["document", "chunk_index", "doc_date", "search_score", "rerank_score", "text"]


def stored_config(config):
    """The config as stored with the experiment: the TOML, plus the prompt text (the file may change later)."""
    stored = copy.deepcopy(config)
    if config["generation"]["enabled"]:
        stored["generation"]["system_prompt_text"] = load_system_prompt(config)
    if config["search"].get("glossary"):   # step 30: the translation glossary, same reason
        stored["search"]["glossary_text"] = Path(config["search"]["glossary"]).read_text(encoding="utf-8")
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


def split_of(config):
    """The question set of a run: "dev" (default, every tuning run), "test" (held out, step 9) or "fresh" (held
    out, step 40): the last two once, at the end."""
    return config.get("evaluation", {}).get("split", "dev")


def eval_questions(conn, split):
    """The questions of a split, aligned with the registry. Only the final evaluation reads the test set."""
    return align_with_registry(load_questions(split, allow_test=split in HELD_OUT), db.load_registry(conn))


def run_experiment(config, allow_dirty=False):
    """Every dev question through the RAG: answers, retrieval scores, refusals. Returns the experiment id.

    Refuses to start on uncommitted code unless allow_dirty: a run that goes in the report must be reproducible
    from its commit. Don't edit the repository while a run starts either: the state is read at its start.
    """
    if git_state()[1] and not allow_dirty:
        raise RuntimeError("uncommitted changes: commit first, or pass allow_dirty=True (--allow-dirty) for a trial run")
    index_corpus(config)  # the collection must exist and be complete; nothing is rebuilt if it is
    generating = config["generation"]["enabled"]
    top_k = config["search"]["top_k"]

    with db.connect() as conn:
        db.create_tables(conn)
        questions = eval_questions(conn, split_of(config))
        check_same_config(conn, config["name"], stored_config(config))
        experiment_id = db.start_experiment(conn, config["name"], stored_config(config))
        logger.info("experiment %d: %s (%d questions, generation %s)",
                    experiment_id, config["name"], len(questions), "on" if generating else "off")
        start = time.time()
        try:
            for i, question in enumerate(questions, 1):
                result = answer(question["question"], config) if generating else retrieve(question["question"], config)
                # Stored as the LLM saw them (citations [n] refer to this order); retrieval-only: the reranker's order
                shown = result.get("context", result["chunks"])
                chunks = [{field: chunk.get(field) for field in STORED_CHUNK_FIELDS} for chunk in shown]
                latency_ms = result["latency_ms"] if generating else sum(result["timings"].values())
                db.insert_answers(conn, experiment_id, [{
                    "question_id": question["id"], "chunks": chunks,
                    "answer": result["answer"] if generating else None, "latency_ms": latency_ms,
                }])
                scores = retrieval_scores(result["chunks"], question, top_k)
                scores |= redundancy_scores(result["chunks"], top_k)
                if generating:
                    scores |= answer_scores(result["answer"], result["context"], question)
                    scores["completion_tokens"] = float(result["completion_tokens"])
                    if result.get("tool_calls"):  # what the LLM computed, to analyse a right or wrong answer
                        scores["tool_calls"] = (float(len(result["tool_calls"])), "\n".join(
                            f"{c['tool']}({c['arguments']}) -> {c['result']}" for c in result["tool_calls"]))
                    language = detect_language(result["answer"], min_words=3)
                    if language is not None:  # too short to tell ("Je ne sais pas."): not counted
                        scores["answer_in_french"] = float(language == "fr")
                scores |= {name: value for name, value in result["timings"].items()}  # search_ms, rerank_ms...
                if config["search"].get("reference_date", False):  # 1 when the question got a date, and which
                    scores["reference_date"] = (float(result["reference"] is not None), str(result["reference"]))
                if len(result["versions"]) > 1:  # the translations as the reason: they explain a gain or a loss
                    scores["translations"] = (float(len(result["versions"]) - 1),
                                              " | ".join(f"{k}: {v}" for k, v in result["versions"].items()))
                if config["search"].get("entities"):   # step 41: the entities the question names, as the reason
                    scores["entities"] = (float(len(result["entities"])), ", ".join(result["entities"]))
                db.insert_scores(conn, experiment_id, score_rows(question, scores))
                logger.info("[%d/%d] %s %s %.0f ms", i, len(questions), question["id"],
                            f"recall@5={scores['recall@5']:.2f}" if "recall@5" in scores else "", latency_ms)
        except BaseException:  # Ctrl+C included: the experiment must not stay 'running' forever
            db.finish_experiment(conn, experiment_id, "failed", time.time() - start)
            raise
        db.finish_experiment(conn, experiment_id, "done", time.time() - start)
        logger.info("experiment %d done in %.0f s", experiment_id, time.time() - start)
    return experiment_id


def judge_experiment(experiment_id, judge_model=None, force=False, types=None, question_ids=None):
    """Judge the stored answers of an experiment on the 31-question sample, on every dev question of `types`, or on
    the questions `question_ids` (step 30: the questions whose evidence is in a table, across types).

    The sample (2 per type) compares configurations broadly; a change aimed at a few types (Excel) is judged on all
    their questions, where 2 per type would let one wording swing a mean by 0.4. Resumes an interrupted pass.
    """
    from rag_calorvia.evaluation.judge import judge_answer, metric_name, metrics_for  # loads DeepEval

    with db.connect() as conn:
        row = db.load_experiment(conn, experiment_id)
        if row is None:
            raise ValueError(f"no experiment {experiment_id}")
        _, name, stored, status = row
        if status != "done":
            raise ValueError(f"experiment {experiment_id} ({name}) is {status!r}, not 'done'")
        answers = db.load_answers(conn, experiment_id)
        done = set() if force else db.load_score_keys(conn, experiment_id)
        split = split_of(stored)
        questions = eval_questions(conn, split)
        if split in HELD_OUT:  # a final evaluation: every held-out question is judged, no sample
            sample = questions
        else:
            sample = ([q for q in questions if q["id"] in set(question_ids)] if question_ids
                      else [q for q in questions if q["type"] in types] if types else judge_sample(questions))
        if all(answers.get(q["id"], (None, None))[1] is None for q in sample):
            raise ValueError(f"experiment {experiment_id} ({name}) has no generated answers: nothing to judge")

        start = time.time()
        for i, question in enumerate(sample, 1):
            chunks, generated = answers.get(question["id"], (None, None))
            metrics = [metric_name(m, judge_model) for m in metrics_for(question, generated)]
            if all((question["id"], m) in done for m in metrics):
                logger.info("[%d/%d] %s already judged", i, len(sample), question["id"])
                continue
            if generated is None:
                logger.warning("[%d/%d] %s has no answer: skipped", i, len(sample), question["id"])
                continue
            scores = judge_answer(question, generated, chunks, judge_model)
            db.insert_scores(conn, experiment_id, score_rows(question, scores))
            logger.info("[%d/%d] %s %s", i, len(sample), question["id"],
                        " ".join(f"{m}={'–' if v is None else f'{v:.2f}'}" for m, (v, _) in scores.items()))
        logger.info("experiment %d (%s) judged in %.0f s", experiment_id, name, time.time() - start)
