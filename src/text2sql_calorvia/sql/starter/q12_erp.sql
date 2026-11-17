-- Starter question 12, ERP side. A salesperson's net invoiced sales of the previous month (February 2026).
-- The salesperson is the order's (VTE_CDE.VDR_ID); VDR_MATRICULE is payroll's employee_id without its M.
SELECT v.VDR_MATRICULE, SUM(CASE f.FAC_TYPE WHEN 'A' THEN -f.FAC_MT_HT ELSE f.FAC_MT_HT END) AS ventes_nettes
FROM VTE_FACT f
JOIN VTE_CDE c ON c.CDE_ID = f.CDE_ID
JOIN VDR_VENDEUR v ON v.VDR_ID = c.VDR_ID
WHERE v.VDR_MATRICULE = '10405'
  AND f.FAC_DT >= '2026-02-01' AND f.FAC_DT < '2026-03-01'
GROUP BY v.VDR_MATRICULE
