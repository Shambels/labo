-- Parameters: experiment id. Every score of one experiment.
SELECT question_id, metric, value
FROM scores
WHERE experiment_id = %s;
