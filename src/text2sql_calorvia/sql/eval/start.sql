INSERT INTO t2sql_experiments (name, config, split, git_commit, git_dirty) VALUES (%s, %s, %s, %s, %s) RETURNING id
