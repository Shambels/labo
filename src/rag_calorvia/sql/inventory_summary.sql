-- Files per format: total, indexed, and excluded by reason. No parameters.
SELECT format,
       count(*)                                                AS files,
       count(*) FILTER (WHERE excluded_reason IS NULL)         AS indexed,
       count(*) FILTER (WHERE excluded_reason = 'duplicate')   AS duplicate,
       count(*) FILTER (WHERE excluded_reason IS NOT NULL AND excluded_reason <> 'duplicate') AS other_excluded,
       count(*) FILTER (WHERE has_text_layer = false)          AS scans
FROM documents
GROUP BY format
ORDER BY files DESC;
