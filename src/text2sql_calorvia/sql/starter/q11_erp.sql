-- Starter question 11, ERP side. Net invoiced revenue of May 2026, split by transfer status.
-- EMISE = issued but not yet transferred to accounting: it explains the gap with the ledger.
SELECT COALESCE(FAC_STATUT, 'TOTAL') AS statut,
       SUM(CASE FAC_TYPE WHEN 'A' THEN -FAC_MT_HT ELSE FAC_MT_HT END) AS ca_net_ht,
       COUNT(*) AS documents
FROM VTE_FACT
WHERE FAC_DT >= '2026-05-01' AND FAC_DT < '2026-06-01'
GROUP BY ROLLUP (FAC_STATUT)
