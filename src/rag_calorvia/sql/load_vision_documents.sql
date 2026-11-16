-- The documents a vision model must read: indexed images and scans, and the text PDFs (some embed charts).
SELECT *
FROM documents
WHERE excluded_reason IS NULL AND (source_type IN ('image', 'scan') OR format = 'pdf')
ORDER BY path;
