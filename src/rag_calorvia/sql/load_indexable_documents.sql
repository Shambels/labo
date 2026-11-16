-- The documents the text index is built from: kept by the inventory, and with text (not images nor scans).
SELECT *
FROM documents
WHERE excluded_reason IS NULL AND source_type IN ('text', 'table')
ORDER BY path;
