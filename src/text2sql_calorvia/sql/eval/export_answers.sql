-- Every answer of every finished, clean run (step 16 export), with its scores and the SQL it executed
SELECT r.experiment_id, e.split, r.question_id, r.category, r.behavior, r.label, r.ok, r.missing, r.leaked,
       round(r.seconds::numeric, 1) AS seconds, r.tool_calls, r.queries, r.refused, r.exec_errors, r.error,
       r.judge_why, r.answer
FROM t2sql_results r JOIN t2sql_experiments e ON e.id = r.experiment_id
WHERE e.finished_at IS NOT NULL AND NOT e.git_dirty
ORDER BY r.experiment_id, r.question_id
