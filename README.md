# labo: chatbots for Calorvia

Two chatbots for **Calorvia SA**, a fictional Belgian heat-pump manufacturer:

1. **`rag_calorvia`**: a RAG over 393 documents from the company's shared drive (in progress).
2. **`text2sql_calorvia`**: a text-to-SQL agent over three business databases (phase B, not started).

`ROADMAP.md` tracks the steps and decisions; `QUIZ.md` holds a quiz per step.

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker with Compose
- One NVIDIA GPU (24 GB), `llama-server` (llama.cpp) and vLLM for the model servers (from step 4 on)
- The course material (statements, corpus, eval set) in `enonces/`. It is **not** in Git: copy it there yourself.

## Installation

```bash
uv sync                      # Python dependencies, dev ones included (pytest)
cp .env.example .env         # then replace every change-me and set MODELS_PATH
docker compose up -d         # PostgreSQL on 5432, Qdrant on 6333

# data/ is git-ignored: link the corpus and the eval set from the course material
mkdir -p data
ln -sfn ../enonces/calorvia_rag/calorvia_dataset/corpus/calorvia data/calorvia
ln -sfn ../enonces/calorvia_rag/calorvia_dataset/corpus/calorvia_eval.json data/calorvia_eval.json

uv run pytest                # the database test is skipped if PostgreSQL isn't up
```

## Pipeline

```bash
uv run python scripts/inventory.py   # Docling conversions (cached in data/conversions/) + the documents registry
```

What is kept out of the index and why: `exclusions.toml` (reviewed by hand), plus the duplicates and empty
files the inventory finds itself. Query the registry with `SELECT * FROM documents WHERE excluded_reason IS NOT NULL`.

Everything runs **from the repository root**: the paths in `config.py` are relative to it.

## Layout

```text
src/rag_calorvia/
├── config.py       # settings from .env (URLs, paths)
├── db.py           # the only module that runs SQL; queries in sql/
├── git_state.py    # commit + dirty flag stored with every experiment
├── logs.py
├── etl/
│   ├── convert.py    # Docling: text documents -> DoclingDocument JSON, once
│   └── inventory.py  # the registry: hashes, pages, text layer, exclusions
└── sql/            # schema and queries (documents, experiments, answers, scores)
scripts/            # command-line entry points
exclusions.toml     # hand-reviewed exclusions, with their reason
tests/
```
