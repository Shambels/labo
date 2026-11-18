# labo: chatbots for Calorvia

Two chatbots for **Calorvia SA**, a fictional Belgian heat-pump manufacturer:

1. **`rag_calorvia`**: a RAG over 393 documents from the company's shared drive. Done: final configuration
   `experiments/status_filter.toml`, results and analysis in `RAPPORT.md`, exports in `results/`.
2. **`text2sql_calorvia`**: a text-to-SQL agent over three business databases (phase B). Done: LangGraph agent
   behind an OpenAI-compatible endpoint, read-only MCP server, certified ontology; results and analysis in
   `RAPPORT_T2SQL.md`, exports in `results/t2sql/`. To run it: [Phase B in five steps](#phase-b-in-five-steps).

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
  --runner pooling --served-model-name bge-m3 --host 127.0.0.1 --port 8001 \
  --dtype float16 --max-model-len 2048 --gpu-memory-utilization 0.10 --enforce-eager

# Reranker (8002): bge-reranker-v2-m3
~/vllm_server/.venv/bin/vllm serve $MODELS_PATH/reranker/bge-reranker-v2-m3 \
  --runner pooling --served-model-name bge-reranker --host 127.0.0.1 --port 8002 \
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

## Phase B in five steps

From a fresh clone, with the course material copied into `enonces/` and `.env` filled in (see `.env.example`):

```bash
uv sync
# 1. The course PostgreSQL (query log, evaluation runs, conversations, memory) and the three sources
docker compose up -d postgres
docker compose -f enonces/calorvia_t2sql/sources_calorvia/docker/docker-compose.yml \
  -f docker-compose.sources-local.yaml --env-file .env up -d   # published on 127.0.0.1 only
docker logs -f calorvia-erp-restore      # wait for "GESPRO restored." (under a minute)

# 2. The model: Qwen3.8-27B with a 32k context and tool calling (the only model phase B needs)
~/llama.cpp/build/bin/llama-server -m $MODELS_PATH/qwen3.8-27b/llama/Qwen3.8-27B-UD-Q4_K_XL.gguf \
  -a openai/qwen3.8-27b --port 8000 -ngl 99 -c 32768 -np 1 -fa on --reasoning off \
  --cache-type-k q8_0 --cache-type-v q8_0

# 3. The MCP server (the only process with database connections), then the agent's endpoint
uv run python -m text2sql_calorvia.mcp_server    # http://127.0.0.1:9001/mcp
uv run python -m text2sql_calorvia.api           # http://127.0.0.1:9000/v1, model "calorvia-agent"

# 4. Ask a question
curl -s http://127.0.0.1:9000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model": "calorvia-agent", "messages": [{"role": "user", "content": "Quel est le CA net facturé de mars 2026 ?"}]}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["choices"][0]["message"]["content"])'

# 5. Check it: the tests (read-only access proven on each database), then the evaluation
uv run pytest
uv run python scripts/run_t2sql_eval.py experiments/t2sql/final.toml             # 33 dev questions, ~11 min
```

In Open WebUI, add `http://127.0.0.1:9000/v1` as an OpenAI connection: the steps unfold live in a fold-out, charts
show as images, and the queries that ran are listed under every answer.

## Phase B: the source databases

```bash
# ERP (SQL Server) on 14330, accounting on 5433, payroll on 5434; passwords from .env (see .env.example)
docker compose -f enonces/calorvia_t2sql/sources_calorvia/docker/docker-compose.yml \
  -f docker-compose.sources-local.yaml --env-file .env up -d   # published on 127.0.0.1 only
docker logs -f calorvia-erp-restore      # ends with "GESPRO restored." (under a minute)

uv run python scripts/explore_sources.py # schemas -> docs/sources/{erp,compta,paie}.md (no data values)
uv run python scripts/run_starter.py -v  # the 12 starter questions, by hand-written SQL, checked against the presentation
uv run pytest tests/test_sources.py      # agent_ro is read-only, tested on each database

uv run python -m text2sql_calorvia.mcp_server          # MCP server on http://127.0.0.1:9001/mcp
uv run python -m text2sql_calorvia.mcp_server --stdio  # or for a client that starts it itself
```

The MCP server `calorvia-sources` is the only component that connects to the sources. Its tools: `list_sources`,
`list_tables`, `get_table_card`, `find_values`, `validate_sql`, `execute_sql` and `get_sales_commission`. Every
query is validated (sqlglot), run read-only with a timeout and a row limit, and logged in `t2sql_query_log`
(course PostgreSQL). Payroll salaries are only shown aggregated over at least 5 people (`privacy.py`).

The application connects only as `agent_ro` (`text2sql_calorvia/sources.py`); the admin passwords in `.env` are
for the restore. To start again from scratch: the same `docker compose` command with `down -v`, then `up -d`.

## Phase B: the ontology (auto-ontology)

Choices, patches and results: `ontology/NOTE.md`. In short:

```bash
# The ERP as a PostgreSQL copy on 5436 (auto-ontology has no SQL Server connector)
docker compose -f ontology/docker-compose.yaml --env-file .env up -d erp-copy
uv run python scripts/copy_erp.py

# NVIDIA auto-ontology (commit a630ebd) cloned in ~/src/auto-ontology, with ontology/patches/*.patch applied
# (git apply) and ~/src/auto-ontology/.env made from ontology/auto-ontology.env.example
ontology/ao.sh build auto-ontology auto-ontology-frontend
ontology/ao.sh up -d postgres auto-ontology ingestion-service frontend-migrate auto-ontology-frontend
# turn on Settings -> Semantic Compilation in http://localhost:3000, create an API token (AUTO_ONTOLOGY_API_TOKEN in .env)

uv run python scripts/certify_ontology.py      # apply ontology/certification.yaml (terms, metrics), idempotent
uv run python scripts/ask_ontology.py after     # the 12 starter questions through auto-ontology's chat API
uv run python scripts/export_ontology.py       # Ossie YAML into ontology/export/, personal samples removed
```

The generator must be served as `openai/qwen3.8-27b` with a 32k context for auto-ontology (structured output).

## Phase B: the agent (LangGraph) and its OpenAI endpoint

```bash
uv run python -m text2sql_calorvia.mcp_server    # the MCP server on 127.0.0.1:9001 (the only one with DB connections)
uv run python -m text2sql_calorvia.api           # the agent on http://127.0.0.1:9000/v1, model "calorvia-agent"
uv run python scripts/ask_agent.py run1          # the 12 starter questions through the agent, scored
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:9000/v1", api_key="...")
answer = client.chat.completions.create(model="calorvia-agent",
                                        messages=[{"role": "user", "content": "Quel est le chiffre d'affaires de mars 2026 ?"}])
```

Every answer ends with the queries that ran (source, SQL as executed, row count); with `stream=True` the agent's
steps arrive first in a collapsed `<details>` block (Open WebUI shows it as a fold-out). The generator on 8000
(`openai/qwen3.8-27b`, 32k context, tool calling) is the agent's model; the auto-ontology containers are not needed.
Graph, budgets and the grounding check: `src/text2sql_calorvia/agent.py`; prompt: `prompts/agent.txt`.

## Phase B: charts and memory (step 15)

- **Charts:** ask for a chart ("fais-moi un graphique du CA par mois"); the agent draws the query result with
  matplotlib, the endpoint serves it from `/charts/<id>.png`, and the answer carries it as a Markdown image (Open WebUI
  displays it). Set `AGENT_PUBLIC_URL` if the client reaches the endpoint by another address than localhost:9000.
- **Conversations** are saved in PostgreSQL (`t2sql_conversations`, `t2sql_messages`) and read back with
  `GET /v1/conversations?user=<user>` and `GET /v1/conversations/<id>`. A client may name the conversation with an
  `X-Conversation-Id` header; otherwise the id hidden at the end of each answer is found again in the history.
- **Memory:** "retiens : toujours en milliers d'euros", "cette requête est la bonne, retiens-la", "oublie le [3]".
  Kept per user (`user` field of the request, or Open WebUI's `X-OpenWebUI-User-Id` header) in `t2sql_memory`, shown in
  the next prompts as data that never lifts a rule. Evaluations run with memory off.

## Phase B: evaluating the agent

```bash
uv run python scripts/run_t2sql_eval.py experiments/t2sql/with_ontology.toml      # the 33 dev questions, stored with the commit
uv run python scripts/run_t2sql_eval.py experiments/t2sql/without_ontology.toml
uv run python scripts/run_t2sql_eval.py --rescore 2 3                             # re-score stored answers (scorer changed)
uv run python scripts/t2sql_report.py 2 3                                         # per category: right, confidently wrong, SQL, time
```

The set is `evaluation/t2sql_questions.yaml` (51 questions; the 18 test questions are run once, with `--test`, at the end).
`evaluation/t2sql_final_questions.yaml` is a second, sealed test set for Phase C: 32 questions, run once with `--final`.
Numbers, names, yes/no conclusions and leaks are checked by code (`src/text2sql_calorvia/evaluation.py`); behaviour
(answered, offered another reading, asked, said it doesn't know, refused) by the LLM judge backed by two rules.

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
├── config.py       # settings from .env (agent_ro password, ports, agent budgets)
├── sources.py      # the three sources; the only module that connects to them, always as agent_ro
├── catalog.py      # tables, columns (readable or not), keys, row counts, from the database catalog
├── starter.py      # the 12 starter questions: expected answers read from the course material, checked
├── privacy.py      # payroll rule: salaries only aggregated over >= 5 people
├── validation.py   # layer 2: one read, dialect, tables/columns, privacy, row limit (sqlglot)
├── execution.py    # layers 3-4: read-only transaction, timeout, row limit; query log
├── cards.py        # list_sources, list_tables, get_table_card
├── values.py       # find_values: case/accent/punctuation/typo-tolerant search of text values
├── commission.py   # get_sales_commission: the one individual payroll figure allowed
├── erp_copy.py     # step 12 tooling: the ERP copied into PostgreSQL for auto-ontology
├── mcp_server.py   # the MCP server and its 7 tools
├── ontology.py     # the certified ontology (ontology/certification.yaml) as the agent's knowledge
├── reconcile.py    # cross-source matching in Python on a normalized key (VAT, staff number, name)
├── agent.py        # the LangGraph agent: agent -> tools -> ... -> check -> finish, budgets, grounding check
├── api.py          # the OpenAI-compatible endpoint (FastAPI): /v1/models, /v1/chat/completions, streaming
├── charts.py       # step 15: query results drawn as PNG charts (matplotlib)
├── memory.py       # step 15: conversations and learned memory in PostgreSQL
├── evaluation.py   # step 14: the question set, scoring in code, the behaviour judge and its rules
└── sql/            # catalog queries per engine, starter/ queries, log/ (query log table)
docs/sources/       # generated schemas + NOTES.md (exploration, read-only findings, traps)
evaluation/         # t2sql_questions.yaml: the agent's evaluation set (51 questions, reference SQL)
ontology/           # auto-ontology: NOTE.md, certification.yaml, export/ (Ossie YAML), patches/, compose files
scripts/            # command-line entry points
exclusions.toml     # hand-reviewed exclusions, with their reason
tests/
```
