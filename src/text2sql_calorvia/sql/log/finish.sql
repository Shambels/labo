UPDATE t2sql_query_log
SET sql_executed = %s, status = %s, error = %s, duration_ms = %s, row_count = %s, truncated = %s
WHERE id = %s
