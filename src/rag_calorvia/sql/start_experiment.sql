-- Parameters: name, config (JSONB), git_commit, git_dirty. Returns the new experiment id.
INSERT INTO experiments (name, config, git_commit, git_dirty)
VALUES (%s, %s, %s, %s)
RETURNING id;
