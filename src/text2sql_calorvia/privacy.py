"""The payroll privacy rule (O5, D43): salaries only as aggregates over at least 5 people.

Checked by the server on the SQL itself, not left to the prompt:

1. A salary column may appear only inside SUM, AVG or COUNT, or in the WHERE clause (as a filter).
   MIN and MAX are refused: the maximum of a group *is* one person's salary. So are window functions
   (SUM(...) OVER (PARTITION BY employee_id) is per person).
2. Only in a plain top-level SELECT: no salary column in a CTE, a subquery or a UNION, where its use can't be
   followed.
3. Before running the query, `group_size_query` counts the distinct people behind each group it returns;
   the query is refused if one group has fewer than `min_group_size` people.

The one individual figure a business question needs (a salesperson's commission, derived from their ERP sales)
has its own narrow tool instead of an exception in this rule.

Known limits: a WHERE filter can still narrow a group by differencing (two queries whose groups differ by one
person); payroll is the only source checked (the accounting's monthly SAL entries per cost centre are already
aggregates, but a cost centre of one person would show that person's cost); absences (sickness) are health data
and are not covered by this rule.
"""
import sqlglot
from sqlglot import exp

# Columns that hold an amount paid to one person (payroll database)
SENSITIVE = {
    "payslips": {"gross_amount", "onss_employee", "taxable_amount", "withholding_tax", "net_amount", "employer_onss"},
    "payslip_lines": {"quantity", "rate", "amount"},
    "salary_history": {"monthly_gross", "hourly_rate"},
}
# Columns about a person that a table card must not sample (they stay queryable: names identify people)
PERSONAL = {
    "employees": {"last_name", "first_name", "birth_date", "postal_code", "city", "work_email", "exit_reason"},
}
# Tables whose employee_id identifies the people behind a payroll row, in order of preference
PEOPLE_KEYS = ["payslips", "salary_history", "contracts", "timesheets", "employees"]
ALLOWED_AGGREGATES = (exp.Sum, exp.Avg, exp.Count)


class PrivacyError(ValueError):
    """A query that would show an individual salary. The message is written for the model."""


def _base_tables(select):
    """{alias or name: table name} for the tables of one SELECT (not those of its subqueries)."""
    tables = {}
    for table in select.find_all(exp.Table):
        if table.find_ancestor(exp.Select) is select:
            tables[table.alias_or_name.lower()] = table.name.lower()
    return tables


def sensitive_columns(tree):
    """The salary columns a (qualified) query reads, as (column node, table name)."""
    found = []
    for column in tree.find_all(exp.Column):
        select = column.find_ancestor(exp.Select)
        if select is None:
            continue
        table = _base_tables(select).get(column.table.lower())
        if table in SENSITIVE and column.name.lower() in SENSITIVE[table]:
            found.append((column, table))
    return found


def check(tree):
    """Apply rules 1 and 2 to a qualified query of the payroll source. Returns True if it reads salaries."""
    found = sensitive_columns(tree)
    if not found:
        return False
    if not isinstance(tree, exp.Select) or tree.find(exp.Subquery, exp.Union, exp.CTE) is not None:
        raise PrivacyError(
            "Règle de confidentialité de la paie : un montant de salaire ne peut être lu que dans un SELECT simple "
            "(sans CTE, sous-requête ni UNION), agrégé par SUM, AVG ou COUNT sur au moins "
            "5 personnes par groupe.")
    for column, table in found:
        if column.find_ancestor(exp.Where) is not None:
            continue
        if column.find_ancestor(exp.Window) is not None:
            raise PrivacyError(f"Règle de confidentialité : {table}.{column.name} dans une fonction de fenêtre "
                               "(OVER) donne un montant par personne. Utilisez GROUP BY.")
        aggregate = column.find_ancestor(exp.AggFunc)
        if aggregate is None:
            raise PrivacyError(
                f"Règle de confidentialité : {table}.{column.name} est un montant individuel. Il ne peut "
                "apparaître qu'agrégé (SUM, AVG ou COUNT) sur au moins 5 personnes par groupe. Pour la "
                "commission d'un commercial, utilisez l'outil get_sales_commission.")
        if not isinstance(aggregate, ALLOWED_AGGREGATES):
            raise PrivacyError(
                f"Règle de confidentialité : {aggregate.key.upper()} de {table}.{column.name} désigne le montant "
                "d'une seule personne (le plus haut, le plus bas...). Seuls SUM, AVG et COUNT sont permis.")
    return True


def group_size_query(tree, dialect):
    """A query returning the smallest number of distinct people behind one group of `tree` (NULL if no row).

    Same FROM, JOINs, WHERE, GROUP BY and HAVING; the select list replaced by COUNT(DISTINCT <t>.employee_id).
    """
    tables = _base_tables(tree)
    alias = next((a for key in PEOPLE_KEYS for a, t in tables.items() if t == key), None)
    if alias is None:
        raise PrivacyError("Règle de confidentialité : pour vérifier qu'un montant couvre au moins 5 personnes, "
                           "la requête doit joindre payslips (ou une table avec employee_id).")
    inner = tree.copy()
    for key in ("order", "limit", "offset", "distinct"):
        inner.set(key, None)
    people = exp.Count(this=exp.Distinct(expressions=[exp.column("employee_id", table=alias)]))
    inner.set("expressions", [exp.alias_(people, "n_people")])
    return sqlglot.select("MIN(n_people)").from_(inner.subquery("g")).sql(dialect)
