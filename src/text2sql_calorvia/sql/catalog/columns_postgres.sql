-- Every column, with its type, nullability, comment and whether the current user (agent_ro) may read it.
-- pg_attribute rather than information_schema: the latter hides the columns the user has no right on.
SELECT n.nspname AS table_schema, c.relname AS table_name, a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       NOT a.attnotnull AS nullable,
       col_description(c.oid, a.attnum) AS comment,
       has_column_privilege(c.oid, a.attnum, 'SELECT') AS readable
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE a.attnum > 0 AND NOT a.attisdropped
  AND c.relkind IN ('r', 'p', 'v')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'access_control') AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY 1, 2, a.attnum
