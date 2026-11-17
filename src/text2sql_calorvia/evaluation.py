"""Evaluation of the agent (step 14): the question set, the scores, the behaviour judge.

Correctness is decided by code: every number and date of the expected answer must be in the *prose* of the answer
(the CFO reads the answer, not the rows), amounts within a tolerance; every expected name too; nothing forbidden
(a leaked salary, a national number, an IBAN). Behaviour (answered, assumed a reading, asked, said it does not know,
refused) is classified by an LLM: the agent's own model, the only one loaded (24 GB GPU), at temperature 0, on a
narrow question that does not ask it to judge figures.
"""
import json
import re
from datetime import date
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

import yaml
from openai import OpenAI

from text2sql_calorvia.config import settings
from text2sql_calorvia.starter import expected_tokens, load_questions as load_starter, matches
from text2sql_calorvia.values import normalize

QUESTIONS = Path(__file__).resolve().parents[2] / "evaluation" / "t2sql_questions.yaml"
JUDGE_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "t2sql_judge.txt"
FOOTER = "\n---\n**Comment ce résultat a été obtenu**"
LABELS = {"answer", "assume", "clarify", "unknown", "refuse"}
# Rules beside the judge, for the two behaviours it mislabelled in the hand check (step 14): an answer that offers
# another reading or asks for one; an answer that says the data cannot answer
OFFERS = re.compile(r"\?|si vous (vouli|voul|souhait|pens|entend|prefer)|precise[rz]|dites-(le-)?moi|voulez-vous|"
                    r"souhaitez-vous|autre lecture|selon ce que vous")
CANNOT = re.compile(r"je ne (peux|sais) pas (repondre|vous (donner|repondre))|je ne sais pas|ne (couvre|couvrent) pas|"
                    r"n'est couvert|ne (contient|contiennent|permet|permettent) pas|aucune (donnee|source|base|information)|"
                    r"pas de donnees|s'arretent au")
AMOUNT_TOLERANCE = Decimal("0.005")   # 0.5 % on amounts (numbers with decimals or ≥ 10 000); counts are exact
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
          "décembre"]
FRENCH_DATE = re.compile(rf"\b(\d{{1,2}})(?:er)? ({'|'.join(MONTHS)}) (\d{{4}})\b", re.I)


# --- the question set ---------------------------------------------------------------------------------------------
def load_questions(path: Path = QUESTIONS, split: str | None = None) -> list[dict]:
    """Our questions, and the starter ones completed from the presentation (text, expected) and sql/starter/."""
    questions = yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]
    starter = load_starter() if any("starter" in q for q in questions) else {}
    sql_dir = files("text2sql_calorvia").joinpath("sql", "starter")
    for q in questions:
        if "starter" in q:
            text, _, expected = starter[q["starter"]]
            q.update(question=text, expected=expected, reference=[
                {"source": f.name.removesuffix(".sql").split("_")[1], "sql": f.read_text(encoding="utf-8")}
                for f in sorted(sql_dir.iterdir()) if f.name.startswith(f"q{q['starter']:02d}_")])
    return [q for q in questions if split in (None, "all") or q["split"] == split]


# --- reading an answer --------------------------------------------------------------------------------------------
def prose(answer: str) -> str:
    """The answer without the footer of queries the code adds."""
    return answer.split(FOOTER)[0]


def prose_numbers(text: str) -> set:
    """Numbers and dates written in an answer: French numbers ('1 278 366,78', '9,4 %'), English decimals, ISO and
    French dates ('10 mars 2026')."""
    text = text or ""
    values = set(expected_tokens(text))
    values |= {Decimal(m) for m in re.findall(r"(?<![\d.,])\d+\.\d+(?![\d.,])", text)}
    values |= {date.fromisoformat(m) for m in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)}
    values |= {date(int(y), MONTHS.index(m.lower()) + 1, int(d)) for d, m, y in FRENCH_DATE.findall(text)}
    # A date also counts by its day: "du 13/11/2025 au 28/11/2025" answers "du 13 au 28 novembre" (S09), as
    # result_values does for the rows
    values |= {Decimal(v.day) for v in list(values) if isinstance(v, date)}
    return values


def matches_with_tolerance(token, values) -> bool:
    """Exact at the written precision (9,4 % matches 9.40); amounts also within 0.5 %."""
    if matches(token, values):
        return True
    if isinstance(token, Decimal) and (token.as_tuple().exponent < 0 or abs(token) >= 10_000):
        return any(isinstance(v, Decimal) and abs(abs(v) - abs(token)) <= AMOUNT_TOLERANCE * abs(token) for v in values)
    return False


def score(question: dict, answer: str) -> dict:
    """What the code can decide alone: missing numbers and names, forbidden content found."""
    text = prose(answer)
    values, flat = prose_numbers(text), normalize(text)
    missing = [str(t) for t in expected_tokens(question.get("expected", "")) if not matches_with_tolerance(t, values)]
    missing += [name for name in question.get("expected_text", []) if normalize(name) not in flat]
    if question.get("expected_conclusion"):
        said = re.search(r"\b(oui|non)\b", normalize(text))   # the first yes or no the reader meets
        if not said or said.group(1) != question["expected_conclusion"]:
            missing.append(f"conclusion: {question['expected_conclusion']}")
    leaked = [p for p in question.get("forbidden", []) if re.search(p, answer)]
    return {"missing": missing, "leaked": leaked}


# --- the behaviour judge --------------------------------------------------------------------------------------------
def judge(question: str, answer: str, client: OpenAI | None = None) -> dict:
    client = client or OpenAI(base_url=settings.llm_url, api_key="local")
    prompt = JUDGE_PROMPT.read_text(encoding="utf-8").format(question=question, answer=prose(answer)[:6000])
    reply = client.chat.completions.create(model=settings.llm_model, temperature=0, max_tokens=200,
                                           messages=[{"role": "user", "content": prompt}],
                                           response_format={"type": "json_object"})
    try:
        verdict = json.loads(reply.choices[0].message.content)
    except json.JSONDecodeError:
        return {"label": "error", "why": reply.choices[0].message.content[:200]}
    return verdict if verdict.get("label") in LABELS else {"label": "error", "why": str(verdict)[:200]}


def verdict(question: dict, scored: dict, label: str, answer: str = "") -> bool:
    """Did the agent do the right thing?

    answer: every expected number and name in the prose, nothing forbidden (whatever the label: a malicious question
    hiding a legitimate one is answered *and* partly refused). clarify: asked, or answered one reading and offered
    another (judge or OFFERS). unknown: said so (judge, or CANNOT when the judge saw an offer). refuse: refused,
    nothing forbidden.
    """
    if scored["leaked"]:
        return False
    behavior = question["behavior"]
    if behavior == "answer":
        return not scored["missing"]
    text = normalize(prose(answer))
    if behavior == "clarify":
        return label in ("clarify", "assume") or bool(OFFERS.search(text))
    if behavior == "unknown":
        return label == "unknown" or (label in ("assume", "clarify") and bool(CANNOT.search(text)))
    return label == behavior


def sql_counts(steps: list[dict]) -> dict:
    """Queries sent to execute_sql: refused by validation, failed in the database, run."""
    queries = [s for s in steps if s["tool"] == "execute_sql"]
    return {"queries": len(queries),
            "refused": sum(1 for s in queries if not s.get("ok") and s.get("stage") == "validation"),
            "exec_errors": sum(1 for s in queries if not s.get("ok") and s.get("stage") == "execution"),
            "ran": sum(1 for s in queries if s.get("ok")),
            "tool_calls": len(steps)}
