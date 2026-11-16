-- Parameters: experiment name. Returns the id of its most recent finished run on committed code,
-- or of its most recent finished run when every run of that name was on uncommitted code.
SELECT id
FROM experiments
WHERE name = %s AND status = 'done'
ORDER BY git_dirty, started_at DESC, id DESC
LIMIT 1;
