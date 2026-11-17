-- Starter question 4. A supplier delivery and the receptions that completed its order lines.
-- Two supplier records match 'Kompra' (one is flagged NE PAS UTILISER): join through the order, not the name alone.
SELECT r.REC_NUM, r.REC_DT, r.REC_COMMENT, a.ART_LIB, cl.ACL_QTE AS qte_commandee, l.RL_QTE_RECUE
FROM ACH_RECEP r
JOIN ACH_RECEP_LIG l ON l.REC_ID = r.REC_ID
JOIN ACH_CDE_LIG cl ON cl.ACL_ID = l.ACL_ID
JOIN ART_ARTICLE a ON a.ART_ID = l.ART_ID
WHERE l.ACL_ID IN (
    SELECT l2.ACL_ID
    FROM ACH_RECEP r2
    JOIN ACH_RECEP_LIG l2 ON l2.REC_ID = r2.REC_ID
    JOIN ACH_CDE c2 ON c2.AC_ID = r2.AC_ID
    JOIN FRN_FOURNISSEUR f ON f.FRN_ID = c2.FRN_ID
    WHERE f.FRN_NOM LIKE 'Kompra%' AND r2.REC_DT = '2026-03-03'
)
ORDER BY r.REC_DT
