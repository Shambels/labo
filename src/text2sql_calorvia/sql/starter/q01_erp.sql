-- Starter question 1. Net invoiced revenue (excl. VAT) of a month.
-- Credit notes (FAC_TYPE = 'A') are stored with POSITIVE amounts in the same table: subtract them.
SELECT SUM(CASE FAC_TYPE WHEN 'A' THEN -FAC_MT_HT ELSE FAC_MT_HT END) AS ca_net_ht
FROM VTE_FACT
WHERE FAC_DT >= '2026-03-01' AND FAC_DT < '2026-04-01'
