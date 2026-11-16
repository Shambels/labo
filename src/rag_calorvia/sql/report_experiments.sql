-- Every experiment, oldest first. No parameters.
SELECT id, name, config, started_at, duration_s, status, git_commit, git_dirty
FROM experiments
ORDER BY started_at, id;
