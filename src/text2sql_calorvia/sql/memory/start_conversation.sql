INSERT INTO t2sql_conversations (id, user_name, title) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING
