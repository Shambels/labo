-- Every query the agent sends to a source (step 11), in the course PostgreSQL (5432).
-- A row is written BEFORE the query runs (status 'running'), then completed: a crash still leaves a trace.
CREATE TABLE IF NOT EXISTS t2sql_query_log (
    id            bigserial PRIMARY KEY,
    logged_at     timestamptz NOT NULL DEFAULT now(),
    tool          text NOT NULL,            -- execute_sql, get_sales_commission...
    source        text,
    question      text,                     -- the user's question, when the agent passes it
    sql_submitted text,
    sql_executed  text,                     -- with the row limit added by validation
    status        text NOT NULL,            -- running, ok, refused, error
    error         text,
    duration_ms   double precision,
    row_count     integer,
    truncated     boolean,
    session_id    text                      -- the conversation, from step 13
);
CREATE INDEX IF NOT EXISTS t2sql_query_log_logged_at ON t2sql_query_log (logged_at);
