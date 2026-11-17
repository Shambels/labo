-- One row per experiment and category; the report adds the totals. Only finished, clean runs (git_dirty = false)
SELECT e.id, e.name, e.split, left(e.git_commit, 7) || ' / scored ' || left(coalesce(e.scorer_commit, e.git_commit), 7), r.category,
       count(*)                                                        AS questions,
       count(*) FILTER (WHERE r.ok)                                    AS ok,
       count(*) FILTER (WHERE r.behavior = 'answer' AND NOT r.ok
                        AND r.label IN ('answer', 'assume'))           AS confidently_wrong,
       count(*) FILTER (WHERE r.label = 'assume')                      AS assumed,
       sum(r.queries)                                                  AS queries,
       sum(r.refused)                                                  AS refused,
       sum(r.exec_errors)                                              AS exec_errors,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r.seconds)          AS median_s,
       max(r.seconds)                                                  AS max_s,
       count(*) FILTER (WHERE r.error IS NOT NULL)                     AS agent_errors
FROM t2sql_experiments e JOIN t2sql_results r ON r.experiment_id = e.id
WHERE e.finished_at IS NOT NULL AND (NOT e.git_dirty OR %s) AND e.id = ANY(%s)
GROUP BY e.id, e.name, e.split, e.git_commit, r.category
ORDER BY e.id, r.category
