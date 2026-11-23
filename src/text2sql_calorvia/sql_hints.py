"""What to change after a database error (step 44): the database says what is wrong, not why nor how to fix it.

Seen in the query log and the traces: an alias of the SELECT used in an ORDER BY expression (« Invalid column name
'benefice_2025' », three times in one question), « ORDER BY 2 + 3 », tables prefixed with the source's name
(« erp.dbo.STK_MVT », six times under the site roles), TOP with OFFSET. Each hint says what SQL allows and gives
the rewrite; the model wrote the same failing query again when it had only the database's message.
"""
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from text2sql_calorvia.sources import SOURCES

WRAP = "enveloppez la requête : SELECT * FROM (…) t ORDER BY t.a + t.b DESC"


def select_aliases(sql: str, dialect: str) -> set[str]:
    """The aliases of the outermost SELECT, in lower case."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except ParseError:
        return {a.lower() for a in re.findall(r"\bAS\s+\[?(\w+)\]?", sql, re.I)}
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    return {e.alias.lower() for e in (select.expressions if select else []) if e.alias}


def hint(source: str, sql: str, message: str) -> str | None:
    """A sentence for the model after a database error, or None when there is nothing better to say than the error."""
    dialect = SOURCES[source].dialect
    missing = re.search(r"Invalid column name '([^']+)'|column \"?([\w.]+)\"? does not exist", message)
    if missing:
        name = (missing.group(1) or missing.group(2)).split(".")[-1]
        if name.lower() in select_aliases(sql, dialect):
            return (f"Piste : « {name} » est un alias du SELECT. SQL ne l'accepte ni dans WHERE, GROUP BY ou HAVING, "
                    f"ni dans une expression d'ORDER BY ; seul (ORDER BY {name} DESC), il fonctionne. Répétez "
                    f"l'expression, ou {WRAP}.")
        return None
    if "constant expression was encountered in the ORDER BY" in message or "non-integer constant in ORDER BY" in message:
        return ("Piste : un numéro de colonne n'est permis dans ORDER BY que seul (ORDER BY 2 DESC) : ORDER BY 2 + 3 "
                f"ne trie pas par la somme des colonnes 2 et 3. Pour trier sur un calcul de colonnes, {WRAP}.")
    unknown = re.search(r"Invalid object name '([^']+)'|relation \"([^\"]+)\" does not exist", message)
    if unknown:
        name = unknown.group(1) or unknown.group(2)
        parts = name.split(".")
        if len(parts) > 1 and parts[0].lower() in SOURCES:
            return (f"Piste : « {parts[0]} » est le nom de la source dans les outils, pas un préfixe SQL : "
                    f"écrivez {'.'.join(parts[1:])}.")
        return f"Piste : table inconnue de la source {source} ; vérifiez son nom avec list_tables."
    if "TOP can not be used in the same query or sub-query as a OFFSET" in message:
        return "Piste : en T-SQL, TOP et OFFSET ne se combinent pas : ORDER BY … OFFSET n ROWS FETCH NEXT m ROWS ONLY."
    return None
