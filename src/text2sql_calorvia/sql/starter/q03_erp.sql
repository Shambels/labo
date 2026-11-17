-- Starter question 3. What happened to a lot: every stock movement that carries its number.
-- The return to the supplier is only in STK_MVT (type RET, negative); the reception line shows 0 refused.
SELECT m.MVT_DT, m.MVT_TYPE, p.COD_LIB AS type_libelle, m.MVT_QTE, m.MVT_REF, a.ART_LIB
FROM STK_MVT m
JOIN ART_ARTICLE a ON a.ART_ID = m.ART_ID
LEFT JOIN PAR_CODE p ON p.COD_TYPE = 'TYPE_MVT' AND p.COD_VAL = m.MVT_TYPE
WHERE m.MVT_LOT = 'V-2544'
ORDER BY m.MVT_DT
