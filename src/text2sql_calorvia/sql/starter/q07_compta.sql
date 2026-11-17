-- Starter question 7. Depreciation booked in a year: account 630000 on validated entries.
-- The fixed-asset register (amortissement) gives the same total; the ledger is what was booked.
SELECT SUM(l.debit - l.credit) AS amortissements
FROM ecriture e
JOIN ligne_ecriture l USING (id_ecriture)
WHERE e.code_periode LIKE '2025-%' AND e.statut = 'VALIDEE' AND l.numero_compte = '630000'
