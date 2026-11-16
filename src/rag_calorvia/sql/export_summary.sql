-- Mean of every metric per experiment and question type (non-NULL values), for results/summary_by_type.csv.
SELECT e.id AS experiment_id, e.name, s.question_type, s.metric,
       round(avg(s.value)::numeric, 4) AS mean, count(s.value) AS n
FROM scores s
JOIN experiments e ON e.id = s.experiment_id
WHERE e.status = 'done'
GROUP BY e.id, e.name, s.question_type, s.metric
ORDER BY e.id, s.question_type, s.metric;
