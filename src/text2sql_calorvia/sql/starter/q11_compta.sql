-- Starter question 11, accounting side. Sales (accounts 70) of May 2026, validated entries.
SELECT SUM(l.credit - l.debit) AS ca_comptable
FROM ecriture e
JOIN ligne_ecriture l USING (id_ecriture)
WHERE e.code_periode = '2026-05' AND e.statut = 'VALIDEE' AND l.numero_compte LIKE '70%'
