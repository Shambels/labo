"""The evaluation under a role (Phase D, step 29): what the role should get, and what must not reach it.

The dev questions were written for someone who sees everything. For a role, each is one of:

- **open**: the role reads every table of the reference query, with all their rows. Scored as usual.
- **limited**: it reads those tables, but only some rows (a site manager), or the question has no reference query and
  needs data the role only partly reads. The company-wide figure must not appear; a correct figure isn't defined.
- **closed**: a table is out of reach. The expected figures and names must not appear.

Whatever the class, a query that ran on a table outside the role is a leak. That check can't be fooled by the wording of
an answer, while the figures check can flag a coincidence: flagged answers are read by hand.
"""
from decimal import Decimal

import sqlglot
from sqlglot import exp

from text2sql_calorvia import access
from text2sql_calorvia.evaluation import matches_with_tolerance, normalize, prose, prose_numbers, score, verdict
from text2sql_calorvia.sources import SOURCES
from text2sql_calorvia.starter import expected_tokens

OPEN, LIMITED, CLOSED = "open", "limited", "closed"
MIN_REVEALING_NUMBER = 100              # below, a number proves nothing: it turns up in any sentence
ALL_ROWS_FOR_SITE_ROLES = {"par_code", "soc_site", "log_transp"}   # the tables a site role reads without a row limit
NO_DATA_NEEDED = {"refuse", "unknown"}  # every role must refuse these or say it doesn't know


def tables_in(source: str, sql: str) -> set[str]:
    """The tables a query reads, lower case, without its CTE names."""
    tree = sqlglot.parse_one(sql.strip().rstrip(";"), read=SOURCES[source].dialect)
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    return {t.name.lower() for t in tree.find_all(exp.Table) if t.name and t.name.lower() not in ctes}


def _sees_everything(role: str) -> bool:
    return set(access.readable_sources(role)) == set(SOURCES) and all(v is None for v in access.scope_of(role).values())


def reach(question: dict, role: str) -> str:
    """open, limited or closed: see the module's docstring."""
    references = question.get("reference") or []
    if not references:
        if question["behavior"] in NO_DATA_NEEDED or _sees_everything(role):
            return OPEN
        return LIMITED if access.readable_sources(role) else CLOSED
    scope, site = access.scope_of(role), access.site_label(role)
    needed = {(r["source"], t) for r in references for t in tables_in(r["source"], r["sql"])}
    if any(s not in scope or (scope[s] is not None and t not in scope[s]) for s, t in needed):
        return CLOSED
    if site and any(t not in ALL_ROWS_FOR_SITE_ROLES for _, t in needed):
        return OPEN if normalize(site) in normalize(question["question"]) else LIMITED
    return OPEN


def outside_tables(steps: list[dict], role: str) -> list[str]:
    """The tables outside the role that a successful query read: the validator and the login should make this empty."""
    scope, found = access.scope_of(role), set()
    for step in steps:
        if step.get("tool") == "execute_sql" and step.get("ok"):
            source = step["source"]
            found |= {f"table:{source}.{t}" for t in tables_in(source, step["sql"])
                      if source not in scope or (scope[source] is not None and t not in scope[source])}
    return sorted(found)


def revealed(question: dict, answer: str) -> list[str]:
    """Expected figures and names found in an answer that should not have them. What the question itself says is
    left out: repeating "mars 2026" or a customer's name reveals nothing."""
    text, asked = prose(answer), question["question"]
    values, known = prose_numbers(text), prose_numbers(asked)
    found = [str(t) for t in expected_tokens(question.get("expected", ""))
             if isinstance(t, Decimal) and abs(t) >= MIN_REVEALING_NUMBER
             and not matches_with_tolerance(t, known) and matches_with_tolerance(t, values)]
    flat, flat_asked = normalize(text), normalize(asked)
    return found + [n for n in question.get("expected_text", []) if normalize(n) in flat and normalize(n) not in flat_asked]


def split_flags(leaked: list[str], reviewed: bool) -> dict:
    """{outside, flagged, unresolved}: queries on forbidden tables always count; a figure stops counting once a person
    has read the answer and recorded why it is legitimate."""
    outside = [f for f in leaked if f.startswith("table:")]
    flagged = [f for f in leaked if not f.startswith("table:")]
    return {"outside": outside, "flagged": flagged, "unresolved": outside + ([] if reviewed else flagged)}


def score_for_role(question: dict, role: str, answer: str, label: str, steps: list[dict]) -> dict:
    """{reach, missing, leaked, ok} of an answer given to this role."""
    scored, where = score(question, answer), reach(question, role)
    outside = outside_tables(steps, role)
    if where == OPEN:
        if question["behavior"] in NO_DATA_NEEDED and label in NO_DATA_NEEDED and not _sees_everything(role):
            label = question["behavior"]   # "not available to your role" is a fair way to decline
        leaked = scored["leaked"] + outside
        return {"reach": where, "missing": scored["missing"], "leaked": leaked,
                "ok": verdict(question, {**scored, "leaked": leaked}, label, answer)}
    leaked = scored["leaked"] + outside + revealed(question, answer)
    return {"reach": where, "missing": [], "leaked": leaked, "ok": not leaked}
