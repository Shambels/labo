SELECT id, kind, content, created_at FROM t2sql_memory WHERE user_name = %s AND active ORDER BY id DESC LIMIT %s
