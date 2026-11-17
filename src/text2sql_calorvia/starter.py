"""The 12 starter questions of the course, answered by hand-written SQL in sql/starter/.

The questions and expected answers are read from the course presentation at run time, never copied into the
repository (it is public: same rule as phase A's eval set, D39). The check is deliberately simple: every number
and date of the expected answer must appear among the values the queries return.
"""
import re
import time
from datetime import date, datetime
from decimal import Decimal
from importlib.resources import files

from text2sql_calorvia.config import settings
from text2sql_calorvia.sources import run_query

# A French number ("13 599 646,63", "9,4", "1 230") or a date ("19/11/2025").
# Thousands are separated by a space, a no-break space or a narrow no-break space.
_DATE = r"\d{2}/\d{2}/\d{4}"
_NUMBER = r"\d{1,3}(?:[   ]\d{3})+(?:,\d+)?|\d+(?:,\d+)?"
_TOKEN = re.compile(rf"({_DATE})|({_NUMBER})")


def expected_tokens(answer):
    """The dates and numbers of an expected answer, as date and Decimal objects."""
    tokens = []
    for d, n in _TOKEN.findall(answer):
        if d:
            tokens.append(datetime.strptime(d, "%d/%m/%Y").date())
        else:
            tokens.append(Decimal(re.sub(r"[   ]", "", n).replace(",", ".")))
    return tokens


def result_values(rows):
    """Every value a check may match: numbers (and their absolute value), dates, and the day and year of each date
    (an answer says "du 13 au 28 novembre", "février 2026")."""
    values = set()
    for row in rows:
        for v in row:
            if isinstance(v, datetime):
                v = v.date()
            if isinstance(v, date):
                values.update({v, Decimal(v.day), Decimal(v.year)})
            elif isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
                values.update({Decimal(str(v)), abs(Decimal(str(v)))})
    return values


def matches(token, values):
    """A number matches at the precision it is written with (9,4 % matches 9.40 or 9.4)."""
    if isinstance(token, date):
        return token in values
    exponent = token.as_tuple().exponent
    return any(isinstance(v, Decimal) and v.quantize(Decimal(1).scaleb(exponent)) == token for v in values)


def load_questions(path=None):
    """{number: (question, sources, expected answer)} from the table of section 5 of the presentation."""
    path = path or settings.sources_path / "presentation_sources_calorvia.md"
    questions = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].isdigit():
            questions[int(cells[0])] = (cells[1], cells[2], cells[3])
    return questions


def starter_queries():
    """{number: [(source, file name, sql)]}: q11_erp.sql and q11_compta.sql both answer question 11."""
    queries = {}
    for f in sorted(files("text2sql_calorvia").joinpath("sql", "starter").iterdir()):
        if f.name.endswith(".sql"):
            number, source = f.name.removesuffix(".sql").split("_")
            queries.setdefault(int(number[1:]), []).append((source, f.name, f.read_text(encoding="utf-8")))
    return queries


def check(number, expected, queries):
    """Run a question's queries; return the rows of each, the missing tokens and the time taken."""
    start = time.perf_counter()
    results, values = [], set()
    for source, name, sql in queries:
        columns, rows = run_query(source, sql)
        results.append((name, columns, rows))
        values |= result_values(rows)
    missing = [t for t in expected_tokens(expected) if not matches(t, values)]
    return results, missing, time.perf_counter() - start
