# labo: chatbots for Calorvia

Two chatbots for **Calorvia SA**, a fictional Belgian heat-pump manufacturer:

1. **`rag_calorvia`**: a RAG over 393 documents from the company's shared drive. Done: final configuration
   `experiments/status_filter.toml`, results and analysis in `RAPPORT.md`, exports in `results/`.
2. **`text2sql_calorvia`**: a text-to-SQL agent over three business databases (phase B, in progress:
   sources restored and explored, see `docs/sources/`).

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

## Model servers

One terminal per server, from any directory. Start the two vLLM servers **first**: vLLM reserves a fixed share of
the GPU at start-up, llama-server only takes what it needs. Loading takes 30 s to 2 min.

```bash
export MODELS_PATH=~/models

# Embedder (8001): bge-m3. The served name must be the folder name: the chunker loads the tokenizer from it
~/vllm_server/.venv/bin/vllm serve $MODELS_PATH/embedder/bge-m3 \
  --runner pooling --served-model-name bge-m3 --port 8001 \
  --dtype float16 --max-model-len 2048 --gpu-memory-utilization 0.10 --enforce-eager

# Reranker (8002): bge-reranker-v2-m3
~/vllm_server/.venv/bin/vllm serve $MODELS_PATH/reranker/bge-reranker-v2-m3 \
  --runner pooling --served-model-name bge-reranker --port 8002 \
  --dtype float16 --max-model-len 2048 --gpu-memory-utilization 0.10 --enforce-eager

# Generator (8000): Qwen3.8-27B, Q4 (~17.5 GB of weights; with the two vLLM servers, ~21.7 GB of the 24 GB)
~/llama.cpp/build/bin/llama-server -m $MODELS_PATH/qwen3.8-27b/llama/Qwen3.8-27B-UD-Q4_K_XL.gguf \
  -a qwen3.8-27b --port 8000 -ngl 99 -c 16384 -np 1 -fa on --reasoning off

# VLM (8003): Qwen3.5-9B with its vision projector (mmproj), for scripts/transcribe.py only (step 7).
# It shares port 8003 with the judge: one or the other
~/llama.cpp/build/bin/llama-server -m $MODELS_PATH/qwen3.5-9b/llama/Qwen3.5-9B-UD-Q4_K_XL.gguf \
  --mmproj $MODELS_PATH/qwen3.5-9b/llama/mmproj-F16.gguf \
  -a qwen3.5-9b --port 8003 -ngl 99 -c 16384 -np 1 -fa on --reasoning off

# Judge (8003): Gemma 4 26B-A4B, Q4 (~17 GB). Another family than the generator: a model grading its own answers
# is lenient. Stop the generator first: they don't fit together
~/llama.cpp/build/bin/llama-server -m $MODELS_PATH/gemma4-26b-a4b/llama/gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf \
  -a gemma4-26b-a4b --port 8003 -ngl 99 -c 16384 -np 1 -fa on --reasoning off
```

Check that a server is ready (it answers with its served name):

```bash
for port in 8000 8001 8002 8003; do
  printf "%s: " $port; curl -s -m 2 localhost:$port/v1/models | grep -o '"id":"[^"]*"' || echo "down"
done
```

| What you run | Needs |
|---|---|
| `inventory.py`, `check_eval.py` | nothing (PostgreSQL only) |
| indexing, retrieval-only experiments | embedder, reranker |
| experiments with generation | embedder, reranker, generator |
| judging | judge only (it reads the stored answers) |

The flags: `--runner pooling` serves an embedding/scoring model instead of a text generator;
`--gpu-memory-utilization 0.10` caps vLLM's reservation at 10 % of the GPU each; `--enforce-eager` skips CUDA graph
capture (faster start, less memory); `-ngl 99` puts every layer on the GPU; `-c 16384` is the context size;
`-np 1` one request slot; `-fa on` flash attention; `--reasoning off` no thinking tokens (faster, and the eval
compares final answers); `-a` the name clients use as `model`.

## Pipeline

```bash
uv run python scripts/inventory.py   # Docling conversions (cached in data/conversions/) + the documents registry with metadata
uv run python scripts/check_eval.py  # the ceiling: which dev questions the indexed text can answer at all
uv run python scripts/transcribe.py  # images, scanned pages, charts in PDFs -> data/vision/ (VLM on 8003, once)
uv run python scripts/index.py experiments/baseline.toml          # chunks + Qdrant collection (embedder)
uv run python scripts/run_experiment.py experiments/baseline.toml # dev set -> answers + scores in PostgreSQL
uv run python scripts/run_experiment.py experiments/baseline.toml --retrieval-only  # no generator needed
uv run python scripts/judge_experiment.py baseline                 # 31-question sample (judge on 8003 only)
uv run python scripts/judge_experiment.py tools_tables --types excel_lookup excel_reasoning  # every dev question of these types
uv run python scripts/report.py baseline no_context_line__retrieval  # per question type and per format
uv run python scripts/ask.py "Quand le nouvel ERP démarre-t-il ?"   # one question, its chunks, and the images it cites
uv run python scripts/compare_ocr.py   # Docling OCR vs the VLM on the scanned PDFs (step 7)
uv run python scripts/run_experiment.py experiments/status_filter.toml --test  # the final config, once, on the 31 held-out questions
uv run python scripts/export_results.py --final status_filter                  # results/*.csv
uv run streamlit run app/chat.py      # chat with the final configuration: answer, extracts, cited images, SQL
```

An experiment is a TOML file in `experiments/` that changes **one** key of `baseline.toml`. `run_experiment.py`
refuses uncommitted code (`--allow-dirty` for a trial run, kept out of reports): every reported run is stored
with its commit.

The eval set is split in code (`evaluation/dataset.py`): the 31 questions whose number is a multiple of 5 are the
held-out test set, readable only with `allow_test=True`, for the final evaluation.

What is kept out of the index and why: `exclusions.toml` (reviewed by hand), plus the duplicates and empty
files the inventory finds itself. Query the registry with `SELECT * FROM documents WHERE excluded_reason IS NOT NULL`.

Everything runs **from the repository root**: the paths in `config.py` are relative to it.

## Phase B: the source databases

```bash
# ERP (SQL Server) on 14330, accounting on 5433, payroll on 5434; passwords from .env (see .env.example)
docker compose -f enonces/calorvia_t2sql/sources_calorvia/docker/docker-compose.yml --env-file .env up -d
docker logs -f calorvia-erp-restore      # ends with "GESPRO restored." (under a minute)

uv run python scripts/explore_sources.py # schemas -> docs/sources/{erp,compta,paie}.md (no data values)
uv run python scripts/run_starter.py -v  # the 12 starter questions, by hand-written SQL, checked against the presentation
uv run pytest tests/test_sources.py      # agent_ro is read-only, tested on each database
```

The application connects only as `agent_ro` (`text2sql_calorvia/sources.py`); the admin passwords in `.env` are
for the restore. To start again from scratch: the same `docker compose` command with `down -v`, then `up -d`.

## Layout

```text
src/rag_calorvia/
├── config.py       # settings from .env (URLs, paths)
├── db.py           # the only module that runs SQL; queries in sql/
├── git_state.py    # commit + dirty flag stored with every experiment
├── logs.py
├── etl/
│   ├── convert.py    # Docling: text documents -> DoclingDocument JSON, once
│   ├── inventory.py  # the registry: hashes, pages, text layer, exclusions
│   └── metadata.py   # type, date, version/status, language, source type from path, name and text
├── evaluation/
│   ├── dataset.py    # dev/test split, judge sample, eval paths aligned with the registry
│   ├── metrics.py    # hit, MRR, recall, nDCG, trap_hit, redundancy, refusals, citations
│   └── coverage.py   # the ceiling: evidence findable in the converted text
└── sql/            # schema and queries (documents, experiments, answers, scores)
src/text2sql_calorvia/
├── config.py       # settings from .env (agent_ro password, ports)
├── sources.py      # the three sources; the only module that connects to them, always as agent_ro
├── catalog.py      # tables, columns (readable or not), keys, row counts, from the database catalog
├── starter.py      # the 12 starter questions: expected answers read from the course material, checked
└── sql/            # catalog queries per engine, starter/ queries per question and source
docs/sources/       # generated schemas + NOTES.md (exploration, read-only findings, traps)
scripts/            # command-line entry points
exclusions.toml     # hand-reviewed exclusions, with their reason
tests/
```
