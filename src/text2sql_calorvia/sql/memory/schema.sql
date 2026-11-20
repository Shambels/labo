-- Conversations and learned memory of the agent (step 15). The OpenAI API is stateless: the client sends the
-- whole history each time; these tables keep it on our side, to read conversations back and to remember across them.
CREATE TABLE IF NOT EXISTS t2sql_conversations (
    id          TEXT PRIMARY KEY,               -- the completion id of the first answer
    user_name   TEXT NOT NULL,
    title       TEXT NOT NULL,                  -- the first question
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS t2sql_messages (
    id               SERIAL PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES t2sql_conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,             -- user or assistant
    content          TEXT NOT NULL,
    steps            JSONB,                     -- the agent's tool calls for an answer (queries, charts...)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS t2sql_memory (
    id               SERIAL PRIMARY KEY,
    user_name        TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('preference', 'definition', 'query')),
    content          TEXT NOT NULL,
    conversation_id  TEXT,                      -- where it was learned
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    active           BOOLEAN NOT NULL DEFAULT true   -- forget = deactivate: what was learned stays traceable
);

-- Step 33: conversations the user manages. Archived, never deleted (like a forgotten memory): archived_at set, the
-- messages kept. A compacted conversation keeps every message; its summary replaces the first summary_messages ones
-- in what the agent reads.
ALTER TABLE t2sql_conversations ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
ALTER TABLE t2sql_conversations ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE t2sql_conversations ADD COLUMN IF NOT EXISTS summary_messages INTEGER NOT NULL DEFAULT 0;
ALTER TABLE t2sql_conversations ADD COLUMN IF NOT EXISTS compacted_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS t2sql_conversations_user ON t2sql_conversations (user_name, updated_at DESC);
CREATE INDEX IF NOT EXISTS t2sql_messages_conversation ON t2sql_messages (conversation_id, id);
