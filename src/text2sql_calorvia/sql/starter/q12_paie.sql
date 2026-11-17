-- Starter question 12, payroll side. A salesperson's commission on the March 2026 monthly payslip.
-- quantity = the sales it is computed on, rate = a PERCENTAGE (0.1000 means 0.1 %).
-- Payroll writes the staff number with an M (M10405), the ERP without (10405).
SELECT r.period_month, r.run_type, l.quantity AS base, l.rate AS taux_pct, l.amount AS commission
FROM payslips p
JOIN payroll_runs r USING (run_id)
JOIN payslip_lines l USING (payslip_id)
WHERE p.employee_id = 'M10405'   -- the salesperson's staff number (ERP VDR_MATRICULE 10405)
  AND r.period_month = DATE '2026-03-01' AND r.run_type = 'MENSUEL'
  AND l.element_code = 'COMMISSION'
