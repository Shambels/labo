"""The payroll privacy rule (O5, D43, D65): salaries only as aggregates over at least 5 people.

Checked by the server on the SQL itself, not left to the prompt. An allowlist: what a query reading a salary column
may contain is listed, everything else is refused (step 17: a list of forbidden forms had let individual pay through).

1. No reference to a whole row (`p`, `row_to_json(p)`, `p::text`, `(p).net_amount`, `(p.*)`), in any payroll query.
2. A query reading a salary column is one plain SELECT: no CTE, subquery, UNION, window function or FILTER. It returns
   aggregates only (no individual row, even when the salary is only a filter).
3. Its aggregates are SUM, AVG and COUNT, over plain arithmetic of columns and constants: a CASE inside an aggregate
   picks one person out of a large group. MIN and MAX of a group *are* one person's salary.
4. In WHERE, a salary is compared with constants, in a condition joined by AND: an OR or a CASE can bring in rows that
   count as people but add nothing to the amount.
5. Before running the query, `group_size_query` counts, for every table a salary is read from, the distinct people
   behind each group, ignoring HAVING and the rows whose aggregated amount is NULL or 0. The query is refused if one
   group has fewer than `min_group_size` people.

The one individual figure a business question needs (a salesperson's commission, derived from their ERP sales)
has its own narrow tool instead of an exception in this rule.

Known limits: two allowed queries can still be compared (groups differing by one person, or a refusal against an
answer, tell something about that person); payroll is the only source checked (the accounting's monthly SAL entries
per cost centre are already aggregates, but a cost centre of one person would show that person's cost); absences
(sickness) are health data and are not covered by this rule.
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
# Salary tables that carry the person directly; payslip_lines reaches it through its payslip
PERSON_TABLES = {"payslips", "salary_history"}
ALLOWED_AGGREGATES = (exp.Sum, exp.Avg, exp.Count)
# What an aggregate's argument may be made of: no CASE, comparison or function that could select rows
PLAIN_ARGUMENT = (exp.Column, exp.Identifier, exp.Literal, exp.Star, exp.Distinct, exp.Paren, exp.Cast, exp.DataType,
                  exp.DataTypeParam, exp.Coalesce, exp.Add, exp.Sub, exp.Neg, exp.Mul, exp.Div)
# What a condition on a salary may be made of
COMPARISONS = (exp.GT, exp.GTE, exp.LT, exp.LTE, exp.EQ, exp.NEQ, exp.Between, exp.In, exp.Is, exp.Not)
PLAIN_FILTER = (*COMPARISONS, exp.Null, exp.Column, exp.Identifier, exp.Literal, exp.Neg, exp.Paren)
RULE = ("agrégé par SUM, AVG ou COUNT sur au moins 5 personnes par groupe, dans un SELECT simple. Filtrez par WHERE "
        "et regroupez par GROUP BY.")


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


def conjuncts(condition):
    """The conditions joined by AND at the top of `condition`."""
    condition = condition.unnest()
    if isinstance(condition, exp.And):
        return conjuncts(condition.left) + conjuncts(condition.right)
    return [condition]


def _check_row_references(tree):
    """A table name used as a value carries all its columns, salaries included, past the column checks."""
    star = next((c for c in tree.find_all(exp.Column) if isinstance(c.this, exp.Star)), None)
    if tree.find(exp.TableColumn) is not None or star is not None:
        raise PrivacyError("Règle de confidentialité de la paie : une ligne entière (alias de table utilisé comme "
                           "valeur, row_to_json, p.*) n'est pas permise. Nommez les colonnes.")


def _check_functions(tree):
    for func in tree.find_all(exp.Func):
        if isinstance(func, ALLOWED_AGGREGATES):
            continue
        name = func.name if isinstance(func, exp.Anonymous) else func.sql_name()
        # Unknown functions may be aggregates, but an aggregate cannot appear in WHERE or ON
        unknown = isinstance(func, exp.Anonymous) and func.find_ancestor(exp.Where, exp.Join) is None
        if isinstance(func, exp.AggFunc) or unknown or "AGG" in name.upper():
            raise PrivacyError(f"Règle de confidentialité : {name.upper()} peut désigner le montant ou l'identité "
                               f"d'une seule personne (le plus haut, le plus bas...). Montant {RULE}")


def _check_aggregate_arguments(tree):
    for aggregate in tree.find_all(*ALLOWED_AGGREGATES):
        for node in aggregate.this.walk():
            non_linear = (isinstance(node, exp.Mul) and node.left.find(exp.Column) and node.right.find(exp.Column)
                          or isinstance(node, exp.Div) and node.right.find(exp.Column))
            if non_linear or not isinstance(node, PLAIN_ARGUMENT):
                raise PrivacyError("Règle de confidentialité : dans une requête sur les salaires, un agrégat porte "
                                   "sur des colonnes et des constantes, sans CASE ni condition (elle isolerait une "
                                   f"personne). Montant {RULE}")


def _check_filter(where, salary_columns):
    for condition in conjuncts(where.this):
        columns = list(condition.find_all(exp.Column))
        if not any(id(c) in salary_columns for c in columns):
            continue
        if not all(id(c) in salary_columns for c in columns) or not isinstance(condition, COMPARISONS) \
                or not all(isinstance(node, PLAIN_FILTER) for node in condition.walk()):
            raise PrivacyError("Règle de confidentialité : un salaire dans WHERE se compare à des constantes, dans "
                               f"une condition reliée par AND (pas de OR ni de CASE). Montant {RULE}")


def check(tree):
    """Apply the rules to a qualified query of the payroll source. Returns True if it reads salaries."""
    _check_row_references(tree)
    found = sensitive_columns(tree)
    if not found:
        return False
    if not isinstance(tree, exp.Select) or tree.find(exp.CTE) is not None or sum(1 for _ in tree.find_all(exp.Select)) > 1:
        raise PrivacyError(f"Règle de confidentialité de la paie : un montant de salaire ne peut être lu qu'{RULE} "
                           "Pas de CTE, de sous-requête ni d'UNION.")
    if tree.find(exp.Window) is not None:
        table, name = found[0][1], found[0][0].name
        raise PrivacyError(f"Règle de confidentialité : {table}.{name} avec une fonction de fenêtre (OVER) donne un "
                           "montant par personne. Utilisez GROUP BY.")
    if tree.find(exp.Filter) is not None:
        raise PrivacyError(f"Règle de confidentialité : pas de FILTER sur une requête de salaires. Montant {RULE}")
    _check_functions(tree)
    _check_aggregate_arguments(tree)
    for column, table in found:
        if column.find_ancestor(exp.Where) is None and column.find_ancestor(exp.AggFunc) is None:
            raise PrivacyError(
                f"Règle de confidentialité : {table}.{column.name} est un montant individuel. Il ne peut "
                f"apparaître qu'{RULE} Pour la commission d'un commercial, utilisez l'outil get_sales_commission.")
    if tree.args.get("where") is not None:
        _check_filter(tree.args["where"], {id(column) for column, _ in found})
    if tree.args.get("group") is None and not any(e.find(exp.AggFunc) for e in tree.expressions):
        raise PrivacyError("Règle de confidentialité : une requête filtrée sur un salaire ne renvoie pas de lignes "
                           f"individuelles. Montant {RULE}")
    return True


def _person_of(tree, alias, table, tables):
    """The column identifying the people behind the rows of one salary table."""
    if table in PERSON_TABLES:
        return f"{alias}.employee_id"
    conditions = [join.args["on"] for join in tree.args.get("joins") or [] if join.args.get("on") is not None]
    if tree.args.get("where") is not None:
        conditions.append(tree.args["where"].this)
    for condition in (c for top in conditions for c in conjuncts(top)):
        if not isinstance(condition, exp.EQ):
            continue
        sides = [condition.left, condition.right]
        if all(isinstance(s, exp.Column) and s.name.lower() == "payslip_id" for s in sides):
            aliases = [s.table.lower() for s in sides]
            if alias in aliases:
                other = aliases[1 - aliases.index(alias)]
                if tables.get(other) == "payslips":
                    return f"{other}.employee_id"
    raise PrivacyError("Règle de confidentialité : pour vérifier qu'un montant couvre au moins 5 personnes, "
                       "payslip_lines doit être jointe à payslips (ON l.payslip_id = p.payslip_id).")


def group_size_query(tree, dialect):
    """A query returning the smallest number of distinct people behind one group of `tree` (NULL if no row).

    Same FROM, JOINs, WHERE and GROUP BY; the select list replaced by the people count. HAVING is dropped: a group it
    hides is still refused, or an empty answer would tell what a refusal would have told. One count per salary column
    read, on that column's own table; the rows an aggregate ignores or that add nothing (NULL, 0) do not count.
    """
    tables = _base_tables(tree)
    counts = []
    for column, table in sensitive_columns(tree):
        alias = column.table.lower()
        count = f"COUNT(DISTINCT {_person_of(tree, alias, table, tables)})"
        if column.find_ancestor(exp.AggFunc) is not None:
            count += f" FILTER (WHERE {alias}.{column.name} <> 0)"
        if count not in counts:
            counts.append(count)
    people = counts[0] if len(counts) == 1 else f"LEAST({', '.join(counts)})"
    inner = tree.copy()
    for key in ("order", "limit", "offset", "distinct", "having"):
        inner.set(key, None)
    inner.set("expressions", [exp.alias_(sqlglot.parse_one(people, read="postgres"), "n_people")])
    return sqlglot.select("MIN(n_people)").from_(inner.subquery("g")).sql(dialect)
