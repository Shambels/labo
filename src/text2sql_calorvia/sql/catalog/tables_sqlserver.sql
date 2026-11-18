-- Tables and views, with their MS_Description if any (the ERP has none, per the presentation)
SELECT s.name AS table_schema, o.name AS table_name,
       CASE o.type WHEN 'V' THEN 'view' ELSE 'table' END AS kind,
       CAST(ep.value AS nvarchar(4000)) AS comment
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
LEFT JOIN sys.extended_properties ep
       ON ep.class = 1 AND ep.major_id = o.object_id AND ep.minor_id = 0 AND ep.name = 'MS_Description'
WHERE o.type IN ('U', 'V') AND o.is_ms_shipped = 0 AND s.name <> 'access_control'
ORDER BY 1, 2
