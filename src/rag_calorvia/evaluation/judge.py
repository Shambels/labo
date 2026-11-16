"""LLM judge (DeepEval): answer quality on the 31-question sample, scored by a model other than the generator.

The judge is Gemma 4 26B-A4B, another model family than the generator (Qwen3.8-27B): a model grading its own
answers tends to be lenient (decision D21).
"""
import logging
import os
from functools import cache

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")  # before importing deepeval: no usage data sent out

from deepeval.metrics import (  # noqa: E402
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    FaithfulnessMetric,
    GEval,
)
from deepeval.models import LocalModel  # noqa: E402
from deepeval.test_case import LLMTestCase, SingleTurnParams  # noqa: E402

from rag_calorvia.config import settings  # noqa: E402
from rag_calorvia.evaluation.metrics import is_refusal  # noqa: E402

logger = logging.getLogger(__name__)

METRIC_NAMES = ["contextual_precision", "contextual_recall", "faithfulness", "answer_relevancy", "correctness"]
# out_of_corpus: the expected answer is a refusal. "Do the chunks hold the answer?" has no meaning when there is
# no answer, and a refusal has no claim to check: only correctness (did it refuse?) is judged.
REFUSAL_METRICS = ["correctness"]


@cache
def get_judge(model=None):
    """The judge model on JUDGE_URL. JSON output forced: DeepEval parses every verdict as JSON."""
    return LocalModel(
        model=model or settings.judge_model,
        base_url=settings.judge_url,
        api_key="EMPTY",
        generation_kwargs={"response_format": {"type": "json_object"}},
    )


def make_metrics(judge):
    """New metric objects for each question: a DeepEval metric keeps the state of its last run."""
    return {
        # Retrieval, seen by the judge: are the useful chunks ranked first? Do they hold everything the answer needs?
        "contextual_precision": ContextualPrecisionMetric(model=judge, async_mode=False),
        "contextual_recall": ContextualRecallMetric(model=judge, async_mode=False),
        # Generation: is every claim of the answer backed by the chunks? Does the answer address the question?
        "faithfulness": FaithfulnessMetric(model=judge, penalize_ambiguous_claims=True, async_mode=False),
        "answer_relevancy": AnswerRelevancyMetric(model=judge, async_mode=False),
        # Against the expected answer of the eval set
        "correctness": GEval(
            name="correctness",
            evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
            evaluation_steps=[
                "Compare the facts of the actual output and the expected output.",
                "Penalize any fact that contradicts the expected output.",
                "Missing facts in the actual output should also be penalized.",
            ],
            model=judge,
            async_mode=False,
        ),
    }


def metrics_for(question, answer=None):
    """The metric names judged for a question (and its answer, when known).

    A refusal makes no claim: faithfulness ("is every claim supported?") would score it 0 because "Je ne sais pas"
    isn't in the chunks (Q014, Q034, Q144 in the baseline). Correctness still judges it: a wrong refusal is an error.
    """
    if question["type"] == "out_of_corpus":
        return REFUSAL_METRICS
    if answer is not None and is_refusal(answer):
        return [name for name in METRIC_NAMES if name != "faithfulness"]
    return METRIC_NAMES


def metric_name(name, judge_model):
    """The main judge's scores keep the plain name; another judge's are stored next to them, e.g. "faithfulness (qwen3.8-27b)"."""
    return name if judge_model in (None, settings.judge_model) else f"{name} ({judge_model})"


def judge_answer(question, answer, chunks, judge_model=None):
    """The judge's scores for one answer: {metric: (value, reason)}; value None when the judge failed on a metric."""
    test_case = LLMTestCase(
        input=question["question"],
        actual_output=answer,
        expected_output=question["answer"],
        retrieval_context=[chunk["text"] for chunk in chunks],
    )
    metrics = make_metrics(get_judge(judge_model))
    scores = {}
    for name in metrics_for(question, answer):
        metric = metrics[name]
        try:
            metric.measure(test_case)
            scores[metric_name(name, judge_model)] = (metric.score, metric.reason)
        except Exception as error:  # one malformed verdict must not lose the other metrics, nor the run
            logger.warning("judge failed on %s / %s: %s", question["id"], name, error)
            scores[metric_name(name, judge_model)] = (None, f"judge error: {error}")
    return scores
