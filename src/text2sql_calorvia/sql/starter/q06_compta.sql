-- Starter question 6. EBITDA and EBITDA margin of a month.
-- EBITDA = operating products and charges before depreciation and provisions: accounts 60-62, 64 and 70-74.
-- Out: 63 (depreciation, provisions, incl. the 637100 reversal), 65 (interest, bank fees), 66-67 (exceptional, tax), 69.
-- Margin = EBITDA / sales (accounts 70).
WITH m AS (
    SELECT l.numero_compte, l.credit - l.debit AS solde
    FROM ecriture e
    JOIN ligne_ecriture l USING (id_ecriture)
    WHERE e.code_periode = '2026-03' AND e.statut = 'VALIDEE'
)
SELECT SUM(solde) FILTER (WHERE left(numero_compte, 2) IN ('60', '61', '62', '64', '70', '71', '72', '73', '74')) AS ebitda,
       SUM(solde) FILTER (WHERE left(numero_compte, 2) = '70') AS chiffre_affaires,
       round(100 * SUM(solde) FILTER (WHERE left(numero_compte, 2) IN ('60', '61', '62', '64', '70', '71', '72', '73', '74'))
                 / SUM(solde) FILTER (WHERE left(numero_compte, 2) = '70'), 1) AS marge_pct
FROM m
