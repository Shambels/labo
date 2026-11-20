-- A new turn: the conversation moves to the top, and comes back from the archives if it was there
UPDATE t2sql_conversations SET updated_at = now(), archived_at = NULL WHERE id = %s
