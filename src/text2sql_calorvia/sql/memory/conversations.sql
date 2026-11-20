-- A user's conversations, newest first: active or archived; with a pattern, only those whose title or a message
-- matches it (NULL: all; the caller escapes the LIKE wildcards of the search text)
SELECT c.id, c.title, c.created_at, c.updated_at, count(m.id) AS messages, c.archived_at, c.compacted_at
FROM t2sql_conversations c LEFT JOIN t2sql_messages m ON m.conversation_id = c.id
WHERE c.user_name = %(user)s
  AND (c.archived_at IS NOT NULL) = %(archived)s
  AND (%(pattern)s::text IS NULL OR c.title ILIKE %(pattern)s OR EXISTS (
        SELECT 1 FROM t2sql_messages s WHERE s.conversation_id = c.id AND s.content ILIKE %(pattern)s))
GROUP BY c.id ORDER BY c.updated_at DESC LIMIT %(limit)s
