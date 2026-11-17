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
    assert sql.startswith("SELECT MIN(n_people) FROM (SELECT COUNT(DISTINCT p.employee_id) AS n_people")
    assert "GROUP BY d.site_code" in sql and "<> 'X'" in sql
    assert "ORDER BY" not in sql and "LIMIT" not in sql   # every group counts, not only the ones displayed


def test_lines_alone_cannot_be_counted_in_people():
    tree = qualified("SELECT SUM(amount) FROM payslip_lines WHERE element_code = 'PFA'")
    assert privacy.check(tree) is True
    with pytest.raises(privacy.PrivacyError, match="joindre payslips"):
        privacy.group_size_query(tree, "postgres")
