-- Primary, unique and foreign keys, written like PostgreSQL's pg_get_constraintdef for a uniform output
SELECT s.name AS table_schema, t.name AS table_name,
       CASE WHEN k.type = 'PK' THEN 'primary' ELSE 'unique' END AS kind,
       CASE WHEN k.type = 'PK' THEN 'PRIMARY KEY' ELSE 'UNIQUE' END + ' ('
         + (SELECT STRING_AGG(c.name, ', ') WITHIN GROUP (ORDER BY ic.key_ordinal)
            FROM sys.index_columns ic
            JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            WHERE ic.object_id = k.parent_object_id AND ic.index_id = k.unique_index_id) + ')' AS definition
FROM sys.key_constraints k
JOIN sys.tables t ON t.object_id = k.parent_object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
WHERE s.name <> 'access_control'
UNION ALL
SELECT s.name, t.name, 'foreign',
       'FOREIGN KEY (' + STRING_AGG(pc.name, ', ') WITHIN GROUP (ORDER BY fkc.constraint_column_id)
         + ') REFERENCES ' + rt.name + '('
         + STRING_AGG(rc.name, ', ') WITHIN GROUP (ORDER BY fkc.constraint_column_id) + ')'
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.tables t ON t.object_id = fk.parent_object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.tables rt ON rt.object_id = fk.referenced_object_id
JOIN sys.columns pc ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
JOIN sys.columns rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
GROUP BY s.name, t.name, fk.object_id, rt.name
ORDER BY 1, 2, 3, 4
