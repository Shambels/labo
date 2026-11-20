UPDATE t2sql_conversations SET summary = %s, summary_messages = %s, compacted_at = now()
WHERE id = %s AND user_name = %s RETURNING id
