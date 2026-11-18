"""A warning when a join multiplies the rows being counted or summed (step 21, D69).

After `FROM ecriture e JOIN ligne_ecriture l`, there is one row per line: COUNT(*) counts lines, and SUM of a column
of `ecriture` adds it once per line. The query is valid and its result looks plausible (C02: 47 for 12 entries), so
nothing else catches it. The foreign keys of the catalog say which joins multiply: a joined table that references a
table already in the query. It stays a warning: counting the lines may be what was asked.
"""
import re

from sqlglot import exp

from text2sql_calorvia.privacy import conjuncts

FOREIGN_KEY = re.compile(r'FOREIGN KEY \((.+?)\) REFERENCES (?:"?\w+"?\.)?"?(\w+)"?\((.+?)\)', re.I)


def parse_foreign_key(definition: str):
    """(columns, referenced table, referenced columns), lower case, from a catalog definition; None if another kind."""
    match = FOREIGN_KEY.search(definition)
    if match is None:
        return None
    names = lambda text: tuple(c.strip(' "').lower() for c in text.split(","))  # noqa: E731
    return names(match[1]), match[2].lower(), names(match[3])


def _equalities(select):
    conditions = [j.args["on"] for j in select.args.get("joins") or [] if j.args.get("on") is not None]
    if select.args.get("where") is not None:
        conditions.append(select.args["where"].this)
    pairs = set()
    for condition in (c for top in conditions for c in conjuncts(top)):
        if isinstance(condition, exp.EQ) and isinstance(condition.left, exp.Column) \
                and isinstance(condition.right, exp.Column):
            a = (condition.left.table.lower(), condition.left.name.lower())
            b = (condition.right.table.lower(), condition.right.name.lower())
            pairs |= {(a, b), (b, a)}
    return pairs


def _fan_outs(select, foreign_keys):
    """(child alias, child table, parent alias, parent table, parent key, aliases present before the join)."""
    source = select.args.get("from_") or select.args.get("from")
    if source is None or not isinstance(source.this, exp.Table):
        return []
    seen = {source.this.alias_or_name.lower(): source.this.name.lower()}
    pairs, found = _equalities(select), []
    for join in select.args.get("joins") or []:
        if not isinstance(join.this, exp.Table):
            continue
        alias, table = join.this.alias_or_name.lower(), join.this.name.lower()
        for columns, parent, parent_columns in foreign_keys.get(table, []):
            for parent_alias in (a for a, t in seen.items() if t == parent):
                links = zip(columns, parent_columns)
                if all(((alias, c), (parent_alias, p)) in pairs for c, p in links):
                    found.append((alias, table, parent_alias, parent, parent_columns[0], set(seen)))
        seen[alias] = table
    return found


def fan_out_warnings(tree, foreign_keys: dict) -> list[str]:
    """Warnings, written for the model, for each SELECT of a qualified query."""
    warnings = []
    for select in tree.find_all(exp.Select):
        fan_outs = _fan_outs(select, foreign_keys)
        if not fan_outs:
            continue
        group = select.args.get("group")
        grouped = {c.table.lower() for c in group.find_all(exp.Column)} if group is not None else set()
        for count in select.find_all(exp.Count):
            if count.find_ancestor(exp.Select) is not select or not isinstance(count.this, (exp.Star, exp.Literal)):
                continue
            for child_alias, child, alias, parent, key, _ in fan_outs:
                if alias not in grouped:   # grouped by the parent, it counts the children of each: what is meant
                    warnings.append(f"Attention : après la jointure avec {child}, COUNT(*) compte les lignes de "
                                    f"{child}, pas les {parent}. Pour compter les {parent} : COUNT(DISTINCT "
                                    f"{alias}.{key}). Si ce sont bien les lignes de {child} qui sont demandées, "
                                    "ignorez ceci.")
        for total in select.find_all(exp.Sum, exp.Avg):
            if total.find_ancestor(exp.Select) is not select:
                continue
            for column in total.find_all(exp.Column):
                for child_alias, child, alias, parent, key, before in fan_outs:
                    if column.table.lower() in before:
                        warnings.append(f"Attention : {column.table}.{column.name} est répété pour chaque ligne de "
                                        f"{child} : {total.key.upper()} le compte plusieurs fois. Calculez-le sans "
                                        f"cette jointure, ou agrégez {child} d'abord.")
    return list(dict.fromkeys(warnings))
