-- Primary, unique and foreign keys, as PostgreSQL writes them ("FOREIGN KEY (x) REFERENCES t(y)")
SELECT n.nspname AS table_schema, c.relname AS table_name,
       CASE con.contype WHEN 'p' THEN 'primary' WHEN 'u' THEN 'unique' ELSE 'foreign' END AS kind,
       pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE con.contype IN ('p', 'u', 'f')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'access_control')
ORDER BY 1, 2, 3, 4
