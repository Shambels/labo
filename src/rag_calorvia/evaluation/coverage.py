"""The ceiling of the eval set: which evidence can be found at all in the text we have, before any search.

For every evidence item, one of:
- found: every snippet is in the whole converted text of its document (the best a chunk can do);
- needs_vision: the document is an image or a scan, unread until step 7;
- not_in_text: the document has text, but a snippet isn't in it (conversion or normalization problem);
- excluded: the document is out of the index (personal data, noise...), and not as a duplicate;
- missing: the document isn't in the corpus.
A question is reachable when each of its needed facts has at least one 'found' grade-2 item.
"""
from collections import Counter

from rag_calorvia.evaluation.metrics import contains_all


def evidence_status(evidence, registry, document_text):
    """Status of one evidence item (see the module docstring). document_text(path) -> the converted text."""
    entry = registry.get(evidence["document"])
    if entry is None:
        return "missing"
    if entry["excluded_reason"] is not None:
        return "excluded"
    text = document_text(evidence["document"])
    if entry["source_type"] in ("image", "scan") and not text:
        return "needs_vision"  # no transcription given for it
    pseudo_chunk = {"document": evidence["document"], "text": text}
    return "found" if contains_all(pseudo_chunk, evidence["document"], evidence["snippets"]) else "not_in_text"


def question_coverage(question, registry, document_text):
    """(reachable, Counter of the statuses of its grade-2 items). Questions without evidence are not counted."""
    needed = {e["fact"] for e in question["evidence"] if e["grade"] == 2}
    statuses, found_facts = Counter(), set()
    for evidence in question["evidence"]:
        if evidence["grade"] != 2:
            continue
        status = evidence_status(evidence, registry, document_text)
        statuses[status] += 1
        if status == "found":
            found_facts.add(evidence["fact"])
    return found_facts == needed, statuses
