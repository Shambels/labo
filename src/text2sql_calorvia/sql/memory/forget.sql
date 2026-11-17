UPDATE t2sql_memory SET active = false WHERE id = %s AND user_name = %s AND active RETURNING id
