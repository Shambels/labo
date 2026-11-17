INSERT INTO t2sql_results (experiment_id, question_id, category, behavior, label, judge_why, ok, missing, leaked,
                           seconds, tool_calls, queries, refused, exec_errors, error, answer, steps)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
