SELECT id, user_name, title, created_at, updated_at, archived_at, summary, summary_messages, compacted_at
FROM t2sql_conversations WHERE id = %s
