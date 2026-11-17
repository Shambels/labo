-- One row per finished, clean run (step 16 export): totals as in the report, both commits
SELECT e.id, e.name, e.split, e.git_commit, coalesce(e.scorer_commit, e.git_commit) AS scorer_commit,
       e.config->'agent' AS agent_options, e.started_at,
       count(*)                                                        AS questions,
       count(*) FILTER (WHERE r.ok)                                    AS ok,
       count(*) FILTER (WHERE r.behavior = 'answer' AND NOT r.ok
                        AND r.label IN ('answer', 'assume'))           AS confidently_wrong,
       count(*) FILTER (WHERE r.label = 'assume')                      AS assumed,
       sum(r.queries)                                                  AS queries,
       sum(r.refused)                                                  AS refused,
       sum(r.exec_errors)                                              AS exec_errors,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r.seconds)          AS median_s,
       sum(r.seconds) / 60                                             AS total_min,
       count(*) FILTER (WHERE r.error IS NOT NULL)                     AS agent_errors
FROM t2sql_experiments e JOIN t2sql_results r ON r.experiment_id = e.id
WHERE e.finished_at IS NOT NULL AND NOT e.git_dirty
GROUP BY e.id
ORDER BY e.id
