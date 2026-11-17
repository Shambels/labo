INSERT INTO t2sql_query_log (tool, source, question, sql_submitted, status, session_id)
VALUES (%s, %s, %s, %s, 'running', %s)
RETURNING id
