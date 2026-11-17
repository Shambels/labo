-- What auto-ontology's ingest stored, per source database (run in its PostgreSQL, port 5435):
--   docker exec -i postgres psql -U postgres -d auto_ontology < ontology/catalog_summary.sql
SELECT d.name                                                        AS database,
       COUNT(DISTINCT t.id)                                          AS tables,
       COUNT(DISTINCT c.id)                                          AS columns,
       COUNT(DISTINCT t.id) FILTER (WHERE cardinality(t.pk) > 0)     AS tables_with_pk,
       (SELECT COUNT(*) FROM column__foreign_key fk
          JOIN catalog_column sc ON sc.id = fk.source_column_id
          JOIN catalog_table st ON st.id = sc.table_id
          JOIN catalog_schema ss ON ss.id = st.schema_id
         WHERE ss.database_id = d.id)                                AS foreign_keys,
       string_agg(DISTINCT s.name, ', ')                             AS schemas
FROM catalog_database d
JOIN catalog_schema s ON s.database_id = d.id
JOIN catalog_table t ON t.schema_id = s.id
LEFT JOIN catalog_column c ON c.table_id = t.id
GROUP BY d.id, d.name
ORDER BY d.name;
