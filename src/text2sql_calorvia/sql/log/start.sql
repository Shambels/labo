INSERT INTO t2sql_query_log (tool, source, question, sql_submitted, status, session_id, user_name, role)
VALUES (%s, %s, %s, %s, 'running', %s, %s, %s)
RETURNING id
