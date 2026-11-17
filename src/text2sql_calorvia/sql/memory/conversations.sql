SELECT c.id, c.title, c.created_at, c.updated_at, count(m.id) AS messages
FROM t2sql_conversations c LEFT JOIN t2sql_messages m ON m.conversation_id = c.id
WHERE c.user_name = %s GROUP BY c.id ORDER BY c.updated_at DESC LIMIT %s
