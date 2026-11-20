-- archived true: into the archives (the first archiving date is kept); false: restored
UPDATE t2sql_conversations
SET archived_at = CASE WHEN %(archived)s THEN coalesce(archived_at, now()) END
WHERE id = %(id)s AND user_name = %(user)s RETURNING id
