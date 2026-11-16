"""The eval set: loading, the dev/test split, the judge sample, and duplicates mapped to the copy we index.

Rules of the statement, enforced here rather than remembered:
- the 31 questions whose number is a multiple of 5 are the test set: tune on the 127 others, evaluate the
  chosen configuration on the test set once, at the end (step 9);
- the eval set measures, it never builds: nothing here is used by the RAG itself.
"""
import json
from collections import defaultdict

from rag_calorvia.config import settings

SPLITS = ("dev", "test", "all")
JUDGE_PER_TYPE = 2  # 2 questions per type of the dev set: 31 questions (image_in_document has only 1 in dev)


def is_test(question_id):
    """Q005, Q010… Q155: the held-out test set."""
    return int(question_id[1:]) % 5 == 0


def load_questions(split="dev", allow_test=False, path=None):
    """The questions of a split. Reading the test set must be asked for explicitly (allow_test=True)."""
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, not {split!r}")
    if split != "dev" and not allow_test:
        raise PermissionError("the test set is held out until the final evaluation: pass allow_test=True")
    with open(path or settings.eval_path, encoding="utf-8") as f:
        questions = json.load(f)
    if split == "dev":
        return [q for q in questions if not is_test(q["id"])]
    if split == "test":
        return [q for q in questions if is_test(q["id"])]
    return questions


def judge_sample(questions):
    """The questions the LLM judge scores: the first JUDGE_PER_TYPE ids of each type, the same for every run."""
    by_type = defaultdict(list)
    for question in sorted(questions, key=lambda q: q["id"]):
        if len(by_type[question["type"]]) < JUDGE_PER_TYPE:
            by_type[question["type"]].append(question)
    return [q for group in by_type.values() for q in group]


def corpus_path(path, registry):
    """The registry path of an eval path. The corpus replaced apostrophes with underscores in file names
    ('Test d_etancheite Aeris.pdf') but the eval set kept them ("Test d'etancheite Aeris.pdf")."""
    if path not in registry and path.replace("'", "_") in registry:
        return path.replace("'", "_")
    return path


def align_with_registry(questions, registry):
    """Evidence and trap paths rewritten to the document we actually index.

    1. corpus_path(): the file-name convention of the corpus (apostrophes);
    2. an excluded duplicate is replaced by the copy we keep (registry duplicate_of). The copies have the same
       text, so a chunk of the kept copy proves what the excluded copy proved. Without this, a question citing
       only the copy in 99_Archives/Doublons would count as a miss even when the right content is retrieved.
    Items that become identical (both copies were listed) are merged, so nDCG's ideal ranking isn't inflated.
    """
    def resolve(path):
        path = corpus_path(path, registry)
        return (registry.get(path) or {}).get("duplicate_of") or path

    def remap(items):
        seen, result = set(), []
        for item in items:
            item = {**item, "document": resolve(item["document"])}
            key = (item["document"], tuple(item["snippets"]), item.get("grade"), item.get("fact"))
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    return [{**q, "evidence": remap(q["evidence"]), "traps": remap(q.get("traps") or [])} for q in questions]
