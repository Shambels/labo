-- Experiments of the text-to-SQL agent (step 14): one row per run, one row per question answered
CREATE TABLE IF NOT EXISTS t2sql_experiments (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    config       JSONB NOT NULL,
    split        TEXT NOT NULL,
    git_commit   TEXT NOT NULL,
    git_dirty    BOOLEAN NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);
-- The scoring code can change after a run (a stricter check, a better judge prompt): answers are re-scored, not
-- re-asked, and the commit of the scoring code is kept apart from the commit of the agent that answered
ALTER TABLE t2sql_experiments ADD COLUMN IF NOT EXISTS scorer_commit TEXT;

CREATE TABLE IF NOT EXISTS t2sql_results (
    experiment_id INTEGER NOT NULL REFERENCES t2sql_experiments(id) ON DELETE CASCADE,
    question_id   TEXT NOT NULL,
    category      TEXT NOT NULL,
    behavior      TEXT NOT NULL,            -- expected: answer, clarify, unknown, refuse
    label         TEXT,                     -- judged: answer, assume, clarify, unknown, refuse, error
    judge_why     TEXT,
    ok            BOOLEAN NOT NULL,         -- did the right thing (evaluation.verdict)
    missing       JSONB NOT NULL,           -- expected numbers and names not in the prose
    leaked        JSONB NOT NULL,           -- forbidden patterns found
    seconds       REAL NOT NULL,
    tool_calls    INTEGER NOT NULL,
    queries       INTEGER NOT NULL,         -- execute_sql calls
    refused       INTEGER NOT NULL,         -- refused by validation
    exec_errors   INTEGER NOT NULL,         -- passed validation, failed in the database
    error         TEXT,                     -- the agent itself failed
    answer        TEXT NOT NULL,
    steps         JSONB NOT NULL,
    PRIMARY KEY (experiment_id, question_id)
);
