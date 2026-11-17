-- Starter question 5. Net result of a financial year: products (class 7) minus charges (class 6), validated entries.
-- Leave out 693000: the year-end appropriation entry (OD, 31/12) moves the profit to equity and brings the sum to 0.
SELECT SUM(l.credit - l.debit) AS resultat_net
FROM ecriture e
JOIN ligne_ecriture l USING (id_ecriture)
JOIN periode p USING (code_periode)
WHERE p.code_exercice = '2025'
  AND e.statut = 'VALIDEE'
  AND left(l.numero_compte, 1) IN ('6', '7')
  AND l.numero_compte <> '693000'
