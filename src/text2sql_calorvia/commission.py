"""The one individual payroll figure the agent may show: a salesperson's sales commission (privacy rule, D43).

A commission is a fixed percentage of the salesperson's invoiced sales, which the ERP shows per salesperson
anyway; checking it against the ERP is a normal finance task. So instead of an exception in the general rule,
a narrow tool: only element COMMISSION, only for someone who is a salesperson in the ERP, one month, logged.
"""
import re
import time

from text2sql_calorvia.execution import log_finish, log_start, run_unvalidated

ERP_SALESPERSON = "SELECT VDR_CODE, VDR_PRENOM, VDR_NOM FROM VDR_VENDEUR WHERE VDR_MATRICULE = %s"
PAYROLL_COMMISSION = """
SELECT r.period_month, r.run_type, r.payment_date, l.quantity, l.rate, l.amount
FROM payslips p
JOIN payroll_runs r ON r.run_id = p.run_id
JOIN payslip_lines l ON l.payslip_id = p.payslip_id
WHERE p.employee_id = %s AND r.period_month = %s::date AND l.element_code = 'COMMISSION'
ORDER BY r.run_id
"""


def _bind(sql, *params):
    """Our own constant SQL with checked parameters (digits, a YYYY-MM-01 date): safe to inline."""
    return sql % tuple(f"'{p}'" for p in params)


def get_sales_commission(staff_number, month, question=None, session_id=None, role=None):
    """The commission on a salesperson's payslip for a month ('2026-03'), with the sales it was computed on.

    staff_number: as the ERP writes it (10405) or as payroll does (M10405).
    """
    match = re.fullmatch(r"\s*M?(\d{4,6})\s*", str(staff_number), re.I)
    digits = match.group(1) if match else None
    if not digits or not re.fullmatch(r"\d{4}-\d{2}", str(month)):
        return {"ok": False, "errors": ["Paramètres attendus : un matricule (10405 ou M10405) et un mois AAAA-MM."]}
    log_id = log_start("get_sales_commission", "erp+paie", question, f"staff_number={digits} month={month}", session_id)
    start = time.perf_counter()
    _, seller, _ = run_unvalidated("erp", _bind(ERP_SALESPERSON, digits), max_rows=1, role=role)
    if not seller:
        message = (f"Le matricule {digits} n'est pas un commercial dans l'ERP : la règle de confidentialité ne "
                   "permet pas d'afficher d'autre montant individuel.")
        log_finish(log_id, "refused", error=message, duration_ms=(time.perf_counter() - start) * 1000)
        return {"ok": False, "errors": [message]}
    columns, rows, _ = run_unvalidated("paie", _bind(PAYROLL_COMMISSION, f"M{digits}", f"{month}-01"), max_rows=10,
                                  role=role)
    log_finish(log_id, "ok", f"erp: VDR_VENDEUR {digits}; paie: COMMISSION M{digits} {month}", None,
               (time.perf_counter() - start) * 1000, len(rows), False)
    code, first, last = seller[0]
    return {
        "ok": True, "salesperson": f"{first} {last} ({code})", "erp_staff_number": digits,
        "payroll_employee_id": f"M{digits}", "month": month,
        "commission_lines": [{"period_month": r[0], "run_type": r[1], "payment_date": r[2],
                              "base_sales": r[3], "rate_percent": r[4], "amount": r[5]} for r in rows],
        "note": "rate_percent est un pourcentage (0.1 = 0,1 %). La base est le chiffre d'affaires facturé du mois "
                "précédent dans l'ERP. Sources : ERP (VDR_VENDEUR) et paie (payslip_lines, élément COMMISSION).",
    }
