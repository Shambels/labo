# labo: chatbots for Calorvia

Two chatbots for **Calorvia SA**, a fictional Belgian heat-pump manufacturer:

1. **`rag_calorvia`**: a RAG over 393 documents from the company's shared drive. Done: final evaluation of
   `experiments/status_filter.toml` (step 9), results and analysis in `RAPPORT.md`, exports in `results/`. The
   configuration in use is `experiments/combined_stated.toml` (step 30's `markdown_tables`, plus the issuer in
   the context line, the v2 image prompt, fuller answers, 10 chunks, up to 2 other chunks of the kept documents
   (step 40), the corpus description (step 41), a rule refusing instructions in the question (the injection
   guard), a conclusion an extract states kept (step 46), meant for the generator served with MTP (step 45));
   `FINAL_CONFIG` in `.env` changes it.
2. **`text2sql_calorvia`**: a text-to-SQL agent over three business databases (phase B). Done: LangGraph agent
   behind an OpenAI-compatible endpoint, read-only MCP server, certified ontology; results and analysis in
   `RAPPORT_T2SQL.md`, exports in `results/t2sql/`. To run it: [Phase B in five steps](#phase-b-in-five-steps).

Both answer from **one chat** (step 31): the endpoint serves `calorvia-sql`, `calorvia-docs` and `calorvia-both`, and the
Streamlit chat has the same toggle. See [One chat for both](#one-chat-for-both-step-31).

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
# Step 45 (D102): speculative decoding with the MTP layer the model file already holds (no extra weights):
# 2.2x the writing speed, answers 7.3 s -> 5.2 s, same judged correctness. A DFlash draft does not fit (1.1 GB short)
~/llama.cpp/build/bin/llama-server -m $MODELS_PATH/qwen3.8-27b/llama/Qwen3.8-27B-UD-Q4_K_XL.gguf \
  -a qwen3.8-27b --port 8000 -ngl 99 -c 16384 -np 1 -fa on --reasoning off \
  --spec-type draft-mtp --spec-draft-n-max 3

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
uv run python scripts/transcribe.py --prompt v2  # step 35: also the text on a diagram's links (for experiments/diagram_labels.toml)
VLM_URL=http://localhost:8000/v1 uv run python scripts/transcribe.py --prompt v2 --model qwen3.8-27b  # step 37: the generator, served with --mmproj
uv run python scripts/index.py experiments/baseline.toml          # chunks + Qdrant collection (embedder)
uv run python scripts/run_experiment.py experiments/baseline.toml # dev set -> answers + scores in PostgreSQL
uv run python scripts/run_experiment.py experiments/baseline.toml --retrieval-only  # no generator needed
uv run python scripts/judge_experiment.py baseline                 # 31-question sample (judge on 8003 only)
uv run python scripts/judge_experiment.py tools_tables --types excel_lookup excel_reasoning  # every dev question of these types
uv run python scripts/reuse_judgments.py 196 --from 191   # step 40: copy verdicts of identical answers; prints what is left to judge
uv run python scripts/run_experiment.py experiments/combined_siblings.toml --fresh  # step 40: the 35 fresh held-out questions, once
uv run python scripts/analyse_misses.py 196   # step 41: why a run's answers lost points (refusal, not found, wrong, incomplete)
uv run python scripts/build_entities.py experiments/combined_entities.toml --workers 2  # step 41: the semantic layer -> knowledge/entities.json (generator)
uv run python scripts/contextualize_chunks.py experiments/combined_contextual.toml       # step 41: one context sentence per chunk -> data/contexts/ (generator)
uv run python scripts/report.py baseline no_context_line__retrieval  # per question type and per format
uv run python scripts/ask.py "Quand le nouvel ERP démarre-t-il ?"   # one question, its chunks, and the images it cites
uv run python scripts/compare_ocr.py   # Docling OCR vs the VLM on the scanned PDFs (step 7)
uv run python scripts/run_experiment.py experiments/status_filter.toml --test  # the final config, once, on the 31 held-out questions
uv run python scripts/run_experiment.py experiments/issuer.toml   # step 34: "Calorvia SA" in the context line (after scripts/inventory.py)
uv run python scripts/run_experiment.py experiments/combined_complete_top10.toml  # steps 38-39: issuer + v2 images + fuller rule 4 + 10 chunks
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

## Comparing experiments

```bash
uv run streamlit run app/experiments.py --server.port 8502   # needs only PostgreSQL (5432)
```

One page for both chatbots, reading the same tables as `scripts/report.py` and `scripts/t2sql_report.py`:

- **RAG:** choose runs (★ marks the configuration in use), metrics (retrieval or judged) and the grouping (question
  type, evidence format, or all); the best value of each row is marked ▲ (lower is better for `trap_hit`). Judged
  metrics are compared on the questions scored in every chosen run, since each run was judged on its own set.
- **Text-to-SQL agent:** right answers and confidently wrong ones per category.
- For both: the questions whose result changed (with the expected answer and each run's answer) and the settings that
  differ between the runs' stored configurations.

Stored answers quote every document: with `API_KEYS` set, the page asks for a key whose role is `direction` or `it`.

## The quiz game

```bash
uv run streamlit run app/quiz.py --server.port 8503     # no server needed
```

Every question of `QUIZ.md` (open: write your answer, reveal the model answer, grade yourself), multiple-choice
versions of the long ones (`quiz/choices.yaml`; you can still answer them in your own words), and a **Code &
pipeline** phase (`quiz/code.yaml`): put the stages in order, match files to their jobs, read a snippet. XP and levels,
streaks, badges, a score per phase (🏅 at 80 % with every question tried), **Redo failed** (questions last answered
wrong or partly), and a **pipeline map** of the app coloured by what you know, with "practice this part". Progress is
saved after each answer in `data/quiz/progress.json`. A new step's quiz in `QUIZ.md` appears in the game by itself.

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
uv run python -m text2sql_calorvia.api           # http://127.0.0.1:9000/v1, models calorvia-sql / -docs / -both

# 4. Ask a question
curl -s http://127.0.0.1:9000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model": "calorvia-agent", "messages": [{"role": "user", "content": "Quel est le CA net facturé de mars 2026 ?"}]}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["choices"][0]["message"]["content"])'

# 5. Check it: the tests (read-only access proven on each database), then the evaluation
uv run pytest
uv run python scripts/run_t2sql_eval.py experiments/t2sql/final.toml             # 33 dev questions, ~11 min
```

Beyond this machine, set `API_KEYS=name:key,...` in `.env` first (see `.env.example`): every `/v1` call then needs
`Authorization: Bearer <key>`, and the server refuses to listen beyond loopback without keys.

Role-based access (Phase D of `ROADMAP.md`) is in place and tested on the course data. `uv run python
scripts/apply_roles.py` creates the role logins and row limits from `policy/roles.yaml` (run it again after restoring
a source); `USER_ROLES=alice:finance` assigns roles. `uv run python scripts/apply_document_roles.py` writes the
documents' roles on the RAG index (no re-embedding); with `API_KEYS` set, `app/chat.py` asks for a key.
`uv run python scripts/prove_access.py` checks every role with planted values, which it removes afterwards: run it
with nothing else using the databases. `--role all` on `scripts/run_t2sql_eval.py` evaluates the agent under each role.

In Open WebUI, add `http://127.0.0.1:9000/v1` as an OpenAI connection: the steps unfold live in a fold-out, charts
show as images, and the queries that ran are listed under every answer.

## One chat for both (step 31)

The model you pick is the toggle:

| Model | Searches | Runs |
|---|---|---|
| `calorvia-sql` (also `calorvia-agent`) | the three databases | the agent, as in phase B |
| `calorvia-docs` | the documents | the RAG of phase A, with its configuration in use (`markdown_tables`) |
| `calorvia-both` | both | the agent with a `search_documents` tool: it picks the source per question, and can compare |

A client may send `"sources": ["sql", "docs"]` instead of choosing a model. Extracts are cited `[D1]`, `[D2]`; the cited
documents are listed under the answer with the queries; an image or scanned page the answer cites is shown from a
signed `/images/` link that expires like a chart's. With `API_KEYS`, the documents are filtered by the same role as
the databases.

Needs everything at once: the embedder (8001), the reranker (8002), the generator on 8000 as in step 2 above, the
MCP server and the endpoint. In Open WebUI, pick the model in the selector. In Streamlit
(`uv run streamlit run app/chat.py`), the sidebar's "Chercher dans" chooses Documents (the RAG, run in the app, with
its extracts), Bases de données or Les deux (both asked to the endpoint on 9000).

To try it in Open WebUI with Docker (port 3000 and 3001 are auto-ontology's):

```bash
docker run -d --name open-webui --network=host -e PORT=8080 \
  -v open-webui:/app/backend/data ghcr.io/open-webui/open-webui:main
# http://localhost:8080 -> Admin Settings -> Connections -> OpenAI: http://127.0.0.1:9000/v1, any key in local mode
```

## Monitoring with Langfuse (step 32)

Every question the endpoint answers becomes a [Langfuse](https://langfuse.com) trace, self-hosted on this machine:

```bash
# fill the LANGFUSE_* block of .env first (see .env.example), then:
docker compose -f monitoring/docker-compose.yaml --env-file .env up -d   # ~1 min; http://localhost:3100
uv run python -m text2sql_calorvia.api                                   # traces as soon as both keys are set
```

Log in with `LANGFUSE_ADMIN_EMAIL` / `LANGFUSE_ADMIN_PASSWORD`: the organisation, the project and its API keys (the
same as the application's) were created at first start. Each trace is one question: its user, its conversation (a
Langfuse *session*, the id of `t2sql_conversations`), the commit that answered (*release*), and below it each LLM call
(input, output, tool calls, tokens), each tool call (the model's arguments, what came back, ⚠ when refused), the
documents found and the grounding check. Six scores per answer to chart and filter on: `tool_calls`, `queries_run`,
`sql_errors`, `unverified_numbers`, `grounding_retry`, `budget_spent`. Streamlit's Documents mode is traced as
`calorvia-docs`.

Traces hold everything the model saw (payroll aggregates, extracts): Langfuse is published on 127.0.0.1 only, sign-up
is off, and its telemetry is off. Tracing is off while `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` is empty; the
tests and the evaluation scripts never trace. To stop it: the same `docker compose` command with `down` (`down -v`
also deletes the traces).

## Managing conversations (step 33)

Every conversation is kept in PostgreSQL, whatever the mode. In Streamlit (`uv run streamlit run app/chat.py`), the
sidebar's **Conversations**: ➕ a new one, a search over titles and messages, the **Archives** toggle, and the list (a
click reopens one, to go on in any mode). Under the title, **⚙️** renames, archives or restores, **compacts** (the
earlier turns summarized for the agent; every message is kept and shown) and **exports** as Markdown.

The same for any client of the endpoint:

```bash
curl -s "localhost:9000/v1/conversations?user=alice&q=avril"                      # search (archived=true: the archives)
curl -s -X PATCH "localhost:9000/v1/conversations/<id>?user=alice" -H 'Content-Type: application/json' \
  -d '{"title": "CA 2026", "archived": true}'                                     # rename, archive (false: restore)
curl -s -X POST "localhost:9000/v1/conversations/<id>/compact?user=alice" -H 'Content-Type: application/json' \
  -d '{"keep_turns": 2}'                                                          # needs the generator on 8000
curl -s "localhost:9000/v1/conversations/<id>/export?user=alice" -o conversation.md
```

With `API_KEYS`, the user is the key's name and `user=` is ignored. Archiving never deletes: a new question in an
archived conversation brings it back. Compaction keeps the last 2 turns word for word and refuses a summary holding a
figure the conversation doesn't have.

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
  matplotlib, the endpoint serves it from a signed `/charts/<id>.png` link that expires after 24 hours, and the answer
  carries it as a Markdown image (Open WebUI displays it). Set `AGENT_PUBLIC_URL` if the client reaches the endpoint by another address than localhost:9000.
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
├── documents.py    # step 31: the RAG in the endpoint (search_documents, documents-only mode, signed image links)
├── charts.py       # step 15: query results drawn as PNG charts (matplotlib)
├── memory.py       # step 15: conversations and learned memory in PostgreSQL; step 33: search, rename, archive
├── conversations.py  # step 33: compaction (summary checked like an answer), Markdown export
├── tracing.py      # step 32: Langfuse traces (one per question), spans, scores; off without keys
├── evaluation.py   # step 14: the question set, scoring in code, the behaviour judge and its rules
└── sql/            # catalog queries per engine, starter/ queries, log/ (query log table)
docs/sources/       # generated schemas + NOTES.md (exploration, read-only findings, traps)
evaluation/         # t2sql_questions.yaml: the agent's evaluation set (51 questions, reference SQL)
ontology/           # auto-ontology: NOTE.md, certification.yaml, export/ (Ossie YAML), patches/, compose files
monitoring/         # step 32: Langfuse's compose file (self-hosted, 127.0.0.1:3100)
scripts/            # command-line entry points
exclusions.toml     # hand-reviewed exclusions, with their reason
tests/
```
