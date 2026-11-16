"""The reference date of a question (step 8): "En décembre 2025, …" asks for the state of things at the end of
December 2025, not today's. The LLM extracts the date; the code decides what to do with it (a filter on doc_date).
"""
import json
import logging
from datetime import date

from qdrant_client import models

from rag_calorvia.rag.generate import get_llm

logger = logging.getLogger(__name__)

REFERENCE_PROMPT = """Tu lis une question posée sur les documents d'une entreprise (septembre 2025 à juin 2026).
Si la question demande l'état des choses à une date ou une période passée (« en décembre 2025 », « lors de la
commande en janvier 2026 », « avant le report »), donne la dernière date de cette période au format AAAA-MM-JJ.
Si elle demande l'état actuel ou ne parle d'aucune période, réponds null. N'invente aucune date.
Réponds uniquement avec un objet JSON de la forme {"date": "AAAA-MM-JJ"} ou {"date": null}."""


def parse_reference(content):
    """The date in the LLM's JSON, or None (null, malformed JSON, or not a real date)."""
    try:
        value = json.loads(content).get("date")
        return date.fromisoformat(value) if value else None
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        return None


def reference_date(question, config):
    """The question's reference date, or None: no date, or [search] reference_date is off."""
    if not config["search"].get("reference_date", False):
        return None
    response = get_llm().chat.completions.create(
        model=config["generation"]["model"], temperature=0.0, max_tokens=40,
        messages=[{"role": "system", "content": REFERENCE_PROMPT}, {"role": "user", "content": question}],
        response_format={"type": "json_object"},
    )
    return parse_reference(response.choices[0].message.content)


def date_condition(reference):
    """Chunks dated on or before the reference, or undated (a document we can't place in time is kept)."""
    return models.Filter(should=[
        models.FieldCondition(key="doc_date", range=models.DatetimeRange(lte=reference.isoformat())),
        models.IsEmptyCondition(is_empty=models.PayloadField(key="doc_date")),
    ])
