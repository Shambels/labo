-- Every column with a readable type (nvarchar(60), decimal(12,2)...), nullability, comment and read permission
SELECT s.name AS table_schema, o.name AS table_name, c.name AS column_name,
       t.name + CASE
           WHEN t.name IN ('varchar', 'char', 'varbinary', 'binary')
               THEN '(' + CASE WHEN c.max_length = -1 THEN 'max' ELSE CAST(c.max_length AS varchar(10)) END + ')'
           WHEN t.name IN ('nvarchar', 'nchar')
               THEN '(' + CASE WHEN c.max_length = -1 THEN 'max' ELSE CAST(c.max_length / 2 AS varchar(10)) END + ')'
           WHEN t.name IN ('decimal', 'numeric')
               THEN '(' + CAST(c.precision AS varchar(10)) + ',' + CAST(c.scale AS varchar(10)) + ')'
           ELSE '' END AS data_type,
       CAST(c.is_nullable AS bit) AS nullable,
       CAST(ep.value AS nvarchar(4000)) AS comment,
       CAST(HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', 'SELECT',
                              c.name, 'COLUMN') AS bit) AS readable
FROM sys.columns c
JOIN sys.objects o ON o.object_id = c.object_id
JOIN sys.schemas s ON s.schema_id = o.schema_id
JOIN sys.types t ON t.user_type_id = c.user_type_id
LEFT JOIN sys.extended_properties ep
       ON ep.class = 1 AND ep.major_id = c.object_id AND ep.minor_id = c.column_id AND ep.name = 'MS_Description'
WHERE o.type IN ('U', 'V') AND o.is_ms_shipped = 0
ORDER BY 1, 2, c.column_id
