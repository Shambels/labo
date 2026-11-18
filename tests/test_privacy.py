"""Unit tests of the payroll privacy rule (no database: a small hand-written schema)."""
import pytest
import sqlglot
from sqlglot.optimizer.qualify import qualify

from text2sql_calorvia import privacy

SCHEMA = {"public": {
    "payslips": {"payslip_id": "int", "employee_id": "text", "run_id": "int", "contract_id": "int",
                 "gross_amount": "numeric", "net_amount": "numeric"},
    "payslip_lines": {"payslip_id": "int", "element_code": "text", "amount": "numeric"},
    "contracts": {"contract_id": "int", "employee_id": "text", "department_code": "text"},
    "departments": {"department_code": "text", "site_code": "text"},
    "employees": {"employee_id": "text", "last_name": "text"},
    "salary_history": {"employee_id": "text", "monthly_gross": "numeric", "hourly_rate": "numeric"},
}}


def qualified(sql):
    return qualify(sqlglot.parse_one(sql, read="postgres"), schema=SCHEMA, dialect="postgres", db="public",
                   validate_qualify_columns=True, identify=False)  # as validation.py does


@pytest.mark.parametrize("sql", [
    "SELECT employee_id FROM payslips",
    "SELECT COUNT(*) FROM payslips",
    "SELECT e.last_name FROM employees e",
])
def test_queries_without_salaries_are_not_concerned(sql):
    assert privacy.check(qualified(sql)) is False


@pytest.mark.parametrize("sql", [
    "SELECT AVG(gross_amount) FROM payslips",
    "SELECT d.site_code, SUM(p.gross_amount) FROM payslips p JOIN contracts c ON c.contract_id = p.contract_id "
    "JOIN departments d ON d.department_code = c.department_code GROUP BY d.site_code",
    "SELECT COUNT(*) FROM payslips WHERE gross_amount > 5000",       # a filter, not a displayed amount
    "SELECT ROUND(AVG(net_amount), 2) FROM payslips",
])
def test_aggregates_are_allowed_and_need_the_group_size_check(sql):
    assert privacy.check(qualified(sql)) is True


@pytest.mark.parametrize("sql, why", [
    ("SELECT employee_id, gross_amount FROM payslips", "montant individuel"),
    ("SELECT gross_amount + 0 FROM payslips", "montant individuel"),
    ("SELECT MAX(gross_amount) FROM payslips", "MAX"),
    ("SELECT MIN(net_amount) FROM payslips", "MIN"),
    ("SELECT SUM(gross_amount) OVER (PARTITION BY employee_id) FROM payslips", "fenêtre"),
    ("WITH x AS (SELECT gross_amount FROM payslips) SELECT SUM(gross_amount) FROM x", "SELECT simple"),
    ("SELECT SUM(g) FROM (SELECT gross_amount AS g FROM payslips) s", "SELECT simple"),
    ("SELECT employee_id FROM payslips ORDER BY gross_amount DESC", "montant individuel"),
])
def test_individual_salaries_are_refused(sql, why):
    with pytest.raises(privacy.PrivacyError, match=why):
        privacy.check(qualified(sql))


def test_group_size_query_counts_people_per_group():
    tree = qualified("SELECT d.site_code, AVG(p.gross_amount) FROM payslips p "
                     "JOIN contracts c ON c.contract_id = p.contract_id "
                     "JOIN departments d ON d.department_code = c.department_code "
                     "WHERE d.site_code <> 'X' GROUP BY d.site_code ORDER BY 2 LIMIT 3")
    sql = privacy.group_size_query(tree, "postgres")
    assert sql.startswith("SELECT MIN(n_people) FROM (SELECT COUNT(DISTINCT p.employee_id) "
                          "FILTER(WHERE p.gross_amount <> 0) AS n_people")
    assert "GROUP BY d.site_code" in sql and "<> 'X'" in sql
    assert "ORDER BY" not in sql and "LIMIT" not in sql   # every group counts, not only the ones displayed


def test_lines_alone_cannot_be_counted_in_people():
    tree = qualified("SELECT SUM(amount) FROM payslip_lines WHERE element_code = 'PFA'")
    assert privacy.check(tree) is True
    with pytest.raises(privacy.PrivacyError, match="jointe à payslips"):
        privacy.group_size_query(tree, "postgres")


# Step 17 (D65): each of these went through the first version of the rule, or is a close variant of one that did
PEOPLE_JOIN = "FROM employees e JOIN payslips p ON p.employee_id = e.employee_id"


@pytest.mark.parametrize("sql", [
    "SELECT p FROM payslips p",
    "SELECT row_to_json(p) FROM payslips p",
    "SELECT to_jsonb(p) FROM payslips p",
    "SELECT p::text FROM payslips p",
    "SELECT (p).net_amount FROM payslips p",
    "SELECT net_amount(p) FROM payslips p",
    "SELECT (p.*)::text FROM payslips p",
])
def test_a_whole_row_is_refused(sql):
    with pytest.raises(privacy.PrivacyError, match="ligne entière"):
        privacy.check(qualified(sql))


@pytest.mark.parametrize("sql", [
    "SELECT SUM(CASE WHEN p.employee_id = 'X' THEN p.net_amount END) FROM payslips p",
    "SELECT SUM(p.net_amount) FILTER (WHERE p.employee_id = 'X') FROM payslips p",
    "SELECT SUM(p.net_amount * (p.employee_id = 'X')::int) FROM payslips p",
    "SELECT SUM(p.net_amount / (p.payslip_id - 1)) FROM payslips p",
    "SELECT SUM(p.net_amount * p.net_amount) FROM payslips p",
    "SELECT COUNT(CASE WHEN p.employee_id = 'X' THEN 1 END) FROM payslips p WHERE p.net_amount > 3000",
    "SELECT BOOL_OR(p.employee_id = 'X') FROM payslips p WHERE p.net_amount > 3000",
])
def test_an_aggregate_cannot_pick_one_person(sql):
    with pytest.raises(privacy.PrivacyError, match="Règle de confidentialité"):
        privacy.check(qualified(sql))


@pytest.mark.parametrize("sql", [
    f"SELECT e.last_name {PEOPLE_JOIN} WHERE p.net_amount > 3000",
    f"SELECT DISTINCT e.employee_id {PEOPLE_JOIN} WHERE p.net_amount > 3000",
    f"SELECT e.last_name, COUNT(*) OVER () {PEOPLE_JOIN} WHERE p.net_amount > 3000",
    f"SELECT ARRAY_AGG(e.last_name) {PEOPLE_JOIN} WHERE p.net_amount > 3000",
    f"SELECT STRING_AGG(e.last_name, ',') {PEOPLE_JOIN} WHERE p.net_amount > 3000",
    f"SELECT JSON_AGG(e.last_name) {PEOPLE_JOIN} WHERE p.net_amount > 3000",
    f"SELECT MIN(e.last_name) {PEOPLE_JOIN} WHERE p.net_amount > 3000",
    "SELECT e.employee_id FROM employees e WHERE EXISTS "
    "(SELECT 1 FROM payslips p WHERE p.employee_id = e.employee_id AND p.net_amount > 3000)",
    "SELECT e.employee_id FROM employees e WHERE e.employee_id IN "
    "(SELECT p.employee_id FROM payslips p WHERE p.net_amount > 3000)",
])
def test_a_salary_filter_does_not_list_people(sql):
    with pytest.raises(privacy.PrivacyError, match="Règle de confidentialité"):
        privacy.check(qualified(sql))


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM payslips p WHERE p.employee_id = 'X' OR p.net_amount > 3000",
    "SELECT COUNT(*) FROM payslips p WHERE CASE WHEN p.employee_id = 'X' THEN p.net_amount > 3000 ELSE TRUE END",
    "SELECT COUNT(*) FROM payslips p WHERE (p.employee_id = 'X') = (p.net_amount > 3000)",
    "SELECT AVG(s.monthly_gross) FROM salary_history s WHERE s.employee_id = 'X' OR s.monthly_gross IS NULL",
])
def test_a_salary_filter_is_a_plain_condition(sql):
    with pytest.raises(privacy.PrivacyError, match="dans WHERE"):
        privacy.check(qualified(sql))


@pytest.mark.parametrize("sql", [
    "SELECT ROUND(SUM(p.gross_amount - p.net_amount) / NULLIF(SUM(p.gross_amount), 0) * 100, 2) FROM payslips p",
    "SELECT SUM(COALESCE(p.net_amount, 0)) FROM payslips p",
    "SELECT SUM(p.gross_amount / 1000.0) FROM payslips p",
    "SELECT COUNT(DISTINCT p.employee_id), AVG(p.gross_amount) FROM payslips p WHERE p.gross_amount IS NOT NULL",
    "SELECT COUNT(*) FROM payslips p WHERE p.gross_amount BETWEEN 3000 AND 4000 AND p.run_id = 7",
    "SELECT p.run_id, SUM(p.gross_amount) FROM payslips p GROUP BY p.run_id HAVING SUM(p.gross_amount) > 0",
])
def test_ordinary_payroll_questions_stay_possible(sql):
    assert privacy.check(qualified(sql)) is True


def people_counted(sql):
    tree = qualified(sql)
    assert privacy.check(tree) is True
    return privacy.group_size_query(tree, "postgres")


def test_people_are_counted_on_the_table_the_salary_comes_from():
    sql = people_counted("SELECT AVG(s.monthly_gross) FROM payslips p JOIN salary_history s ON s.employee_id = 'X'")
    assert "COUNT(DISTINCT s.employee_id)" in sql and "p.employee_id" not in sql


def test_every_salary_table_of_a_query_is_counted():
    sql = people_counted("SELECT SUM(p.net_amount), SUM(q.net_amount) FROM payslips p "
                         "JOIN payslips q ON q.employee_id = 'X'")
    assert "LEAST(" in sql and "DISTINCT p.employee_id" in sql and "DISTINCT q.employee_id" in sql


def test_rows_adding_nothing_to_an_aggregate_are_not_people():
    sql = people_counted("SELECT SUM(p.net_amount) FROM payslips p")
    assert "FILTER(WHERE p.net_amount <> 0)" in sql


def test_having_cannot_hide_a_group_of_one():
    sql = people_counted("SELECT p.employee_id, COUNT(*) FROM payslips p WHERE p.net_amount > 0 "
                         "GROUP BY p.employee_id HAVING SUM(p.net_amount) > 1000000")
    assert "HAVING" not in sql and "GROUP BY p.employee_id" in sql


def test_payslip_lines_count_the_people_of_their_payslip():
    sql = people_counted("SELECT SUM(l.amount) FROM payslip_lines l JOIN payslips p ON p.payslip_id = l.payslip_id")
    assert "COUNT(DISTINCT p.employee_id)" in sql


@pytest.mark.parametrize("join", ["ON l.payslip_id = 1", "ON l.payslip_id = p.payslip_id OR l.payslip_id = 1"])
def test_payslip_lines_must_really_be_tied_to_their_payslip(join):
    tree = qualified(f"SELECT SUM(l.amount) FROM payslips p JOIN payslip_lines l {join}")
    assert privacy.check(tree) is True
    with pytest.raises(privacy.PrivacyError, match="jointe à payslips"):
        privacy.group_size_query(tree, "postgres")
