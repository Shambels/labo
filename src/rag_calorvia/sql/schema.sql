-- The three tables of an experiment. IF NOT EXISTS: safe to run before every experiment.

CREATE TABLE IF NOT EXISTS experiments (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    config      JSONB NOT NULL,                  -- the whole TOML file, with the prompt text
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_s  REAL,
    status      TEXT NOT NULL DEFAULT 'running', -- running, done, failed
    git_commit  TEXT NOT NULL,                   -- HEAD when the run started
    git_dirty   BOOLEAN NOT NULL                 -- uncommitted changes: not reproducible, kept out of the report
);

CREATE TABLE IF NOT EXISTS answers (
    experiment_id  INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    question_id    TEXT NOT NULL,
    chunks         JSONB NOT NULL,               -- document, chunk index, score and text of each retrieved chunk
    answer         TEXT,                         -- NULL when the experiment skips generation
    latency_ms     REAL,
    PRIMARY KEY (experiment_id, question_id)
);

CREATE TABLE IF NOT EXISTS scores (
    experiment_id  INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    question_id    TEXT NOT NULL,
    question_type  TEXT NOT NULL,
    metric         TEXT NOT NULL,                -- hit@5, mrr, recall@5, ndcg@5, faithfulness...
    value          REAL,                         -- NULL when the judge failed
    reason         TEXT,                         -- the judge's explanation, if any
    PRIMARY KEY (experiment_id, question_id, metric)
);

-- The registry of the corpus: one row per file, written by etl/inventory.py (scripts/inventory.py).
CREATE TABLE IF NOT EXISTS documents (
    path             TEXT PRIMARY KEY,           -- relative to the corpus root
    format           TEXT NOT NULL,              -- extension: docx, pdf, xlsx, jpg...
    size_bytes       INTEGER NOT NULL,
    sha256           TEXT NOT NULL,              -- of the bytes of the file
    content_hash     TEXT NOT NULL,              -- of the normalized text (of the bytes when there is no text)
    page_count       INTEGER,                    -- PDF pages, PPTX slides
    has_text_layer   BOOLEAN,                    -- PDFs only: false for a scan
    text_chars       INTEGER NOT NULL,           -- characters of text found by Docling
    duplicate_of     TEXT REFERENCES documents(path) DEFERRABLE INITIALLY DEFERRED,
    excluded_reason  TEXT,                       -- NULL: indexed. duplicate, empty, personal_data, template, noise
    inventoried_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
