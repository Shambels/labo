-- The latest finished, clean run of each role (step 29)
SELECT DISTINCT ON (e.config->>'role') e.id, e.config->>'role' AS role, e.git_commit
FROM t2sql_experiments e
WHERE e.config ? 'role' AND e.finished_at IS NOT NULL AND NOT e.git_dirty
ORDER BY e.config->>'role', e.id DESC
