-- Starter question 2. Finished goods (ART_TYPE = 'PF') bought by a customer over five months.
-- Units invoiced minus units sent back. Only credit notes with reason RETOUR give goods back:
-- Distrinergie's REGUL_TARIF credit note of February 2026 lists 270 units but returns none (PAR_CODE says so).
SELECT SUM(CASE WHEN f.FAC_TYPE = 'F' THEN l.FL_QTE
                WHEN f.FAC_MOTIF = 'RETOUR' THEN -l.FL_QTE
                ELSE 0 END) AS unites
FROM VTE_FACT f
JOIN VTE_FACT_LIG l ON l.FAC_ID = f.FAC_ID
JOIN ART_ARTICLE a ON a.ART_ID = l.ART_ID
JOIN CLI_CLIENT c ON c.CLI_ID = f.CLI_ID
WHERE c.CLI_NOM LIKE 'Distrinergie%'
  AND a.ART_TYPE = 'PF'
  AND f.FAC_DT >= '2026-01-01' AND f.FAC_DT < '2026-06-01'
