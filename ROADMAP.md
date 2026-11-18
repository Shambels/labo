# Roadmap: Calorvia chatbots

Two chatbots for the fictional company **Calorvia SA**, built one after the other in this repo:

| Phase | Source of knowledge | Statement |
|---|---|---|
| **A. RAG** | 393 documents from a shared drive (DOCX, PDF, scans, XLSX, images, HTML, PPTX…) in French, Dutch and English | `enonces/calorvia_rag/laboratoire_calorvia_enonce.md` |
| **B. Text-to-SQL** | 3 relational databases: the old ERP (SQL Server), accounting and payroll (PostgreSQL) | `enonces/calorvia_t2sql/projet_text2sql_enonce.md` |
| **C. Improvements** | Both chatbots: what the two reports left open | This roadmap |
| **D. Role-based access** | Who may see which tables, rows and documents | This roadmap |
| **E. RAG experiments** | Ideas left open by the RAG report | This roadmap |

Companion file: `QUIZ.md` (one quiz per step, answers collapsed).

**Status legend:** ✅ done · 🔄 in progress · ⬜ to do

---

## Decisions

| # | Decision | Choice | Why |
|---|---|---|---|
| D1 | Starting point for the RAG | Port `~/projects/hospital_rag` (exercise 3) into `src/rag_calorvia/` and adapt it | The statement asks for it; lets the steps focus on what is new (Excel, images, languages, versions) |
| D2 | Quiz format | Answers inline, inside collapsed `<details>` blocks | Your choice |
| D3 | Language | English for docs, code and comments; LLM prompts in French | Questions and corpus are French |
| D4 | One repo or two | One repo (`labo`), one uv project, two packages: `src/rag_calorvia/` then `src/text2sql_calorvia/`. Tags are prefixed: `rag/v0.1-inventaire`, `t2sql/v0.1-sources` | You asked for both exercises in this repo; the statement's tag names stay recognisable |
| D5 | Where the corpus lives | Stays in `enonces/`; `data/calorvia` is a symlink to it (same path as the hints notebook) and `data/` holds everything generated (conversions, VLM cache) and is git-ignored | No copy of 21 MB; same paths as the course |
| D6 | `enonces/` in Git (was O1) | Untracked (`git rm --cached`) and git-ignored. **The step 0 commit failed** (`git commit -- enonces .gitignore` re-added the files from the working tree); really untracked in step 6. The hints notebook stays in `enonces/` rather than being copied to `notebooks/` | The repo is **public** and this is course material with (fake) personal data. It remains in the history of commit `ad75e6c` |
| D7 | PostgreSQL port (was O2) | **5432** for the registry/experiments DB; Qdrant 6333 (pinned `v1.19.1`) | Leaves 1433/5433/5434 to phase B's sources |
| D8 | Dependencies | Added step by step, when a step needs them (step 0: `psycopg`, `pydantic-settings`, `pytest`) | Each step's diff shows why a dependency exists |
| D10 | Docling conversion moved from step 4 to step 1 | `etl/convert.py`, cached in `data/conversions/<relative path>.json` | Duplicates can only be found on content (see step 1); the cache is reused by step 4 |
| D11 | What "duplicate" means | Same `content_hash` = SHA-256 of the text reduced to lower-case letters and digits. Kept copy: outside `99_Archives/`, then not a PDF, then shortest path | No two files of the corpus share their bytes; this catches all 7 copies, the DOCX/PDF pair included |
| D12 | Personal data | Excluded **per file** in `exclusions.toml`, not per folder | `02_RH/Confidentiel/Grille salariale 2026.xlsx` has no names and is evidence for a question; only the annual reviews name people |
| D13 | Registry schema changes | `DROP TABLE documents` and re-run the inventory, no migration | The registry is derived data: rebuilt from the corpus in seconds |
| D14 | Dates | Three passes: precise file-name patterns (photo, day, month, quarter, range), then the first date in the first 600 characters of text (title line only for workbooks), then a bare year in the name. Every date keeps `date_end`, `date_precision`, `date_source` | The file name is the most reliable when precise; a year in a code (`NC-2025-047`) is the least |
| D15 | Status | One `status` (template > copy > archive > draft > signed > approved, else NULL), plus every raw marker in `markers` (incl. `final_in_name`) | Step 8 filters on the status; the markers stay available to analyse the traps |
| D16 | Unsure language | `NULL` (7 number-heavy workbooks), no default | Honest at document level; step 5 detects per chunk and picks the default there |
| D17 | Judge sample | 2 questions per type of the dev set, `out_of_corpus` **included**: 31 questions | The statement's count (31); exercise 3 excluded `out_of_corpus` (26) |
| D18 | Eval paths vs registry | `align_with_registry()` at load time: apostrophes → underscores, excluded duplicates → kept copy, identical items merged. The metrics stay unchanged | The eval set has 2 paths with `'` where the corpus has `_`; questions citing only a dropped copy would be false misses |
| D19 | `trap_hit` | Per question with traps, `trap_hit@k` = 1 if a trap is in the top k (statement's definition, same document + every snippet) | Lower is better; averaged over the 17 dev questions that have traps |
| D20 | Generator | **Qwen3.8-27B** (Q4_K_XL, llama-server, `--reasoning off`) instead of Qwen3.5-9B | Your choice. Slower per token than the 9B; fits with the embedder and reranker (21.7 / 24 GB) |
| D21 | Judge (was O8) | **Gemma 4 26B-A4B** (Q4_K_XL, llama-server, port 8003) | Another family than the generator: no self-preference. Judge scores not comparable with exercise 3's |
| D22 | Baseline = exercise 3's best, transposed | 256 tokens, no overlap, context line, hybrid RRF k=60, 30 candidates, bge-reranker, top 5, `prompts/baseline.txt` (combined_v2 without the patient rule). No question decomposition (its gate was hospital-specific) | The statement: "la meilleure configuration de l'exercice 3 et la ligne de contexte" |
| D23 | No boilerplate removal | Exercise 3's header removal not transposed | Texts repeated in 5+ documents are action-table rows and attendance lists (evidence), not footers; Docling already drops page headers/footers |
| D24 | Clean runs only | `run_experiment` refuses a dirty tree (`--allow-dirty` for trials); reports pick the latest clean run | Two runs were stamped dirty by a `uv add` made while they started |
| D25 | New reference after step 5 | `prompt_multilingual` (baseline + rule 4 on Dutch/English extracts). `bm25_per_language` and `translate_question` not kept | 5a and 5b bring nothing on the dev set (recall@5 0.779, 0.766 vs 0.783), 5b costs +2.2 s per question; 5c is neutral-to-better and free |
| D26 | Never edit a config that has run | New options get defaults in code (`config.get(...)`); `baseline.toml` is frozen | `check_same_config` compares the stored config: an edited baseline couldn't run again under its name |
| D27 | 6b tools | Generic SQL over every workbook table (SQLite in memory) rather than hand-written functions | Your choice: no rule per question, works for any workbook, previews phase B |
| D28 | Collection freshness | A fingerprint of the chunk texts in every point's payload; mismatch → rebuild | The name only encodes options; a code change in the chunker kept the name |
| D29 | New reference after step 6 | `tools_tables` (openpyxl reader + SQL tools + prompt rule 7) | Best correctness on the workbook questions (0.841 vs 0.795) and on the sample (0.687 vs 0.655); +0.4 s mean latency |
| D30 | Judging a targeted change | Judge every dev question of the targeted types (`--types`), not only the 2-per-type sample | With 2 questions, one wording moves a type's mean by 0.4 |
| D31 | Purge `enonces/` from history (was O7) | `git filter-repo --path enonces --invert-paths`, force-push of `main` and the tags; experiment commits in PostgreSQL remapped with filter-repo's `commit-map`; short hashes in the docs rewritten | Your request. Every commit hash changed; GitHub may keep unreferenced old commits reachable by their hash for a while |
| D32 | VLM (was O3) | Qwen3.5-9B Q4_K_XL + `mmproj-F16`, llama-server, port 8003, temperature 0 | Your choice; already on disk, 9B fits beside the embedder and reranker |
| D33 | Scans: VLM or Docling OCR | VLM | Same evidence score (7/7), OCR 40 % faster, but the OCR garbled whole lines (including the L4 resolution); the VLM also reads images and handwriting |
| D34 | New reference after step 7 | `vision_whole_images` (`tools_tables` + transcriptions, one image = one chunk up to 1024 tokens) | Image/scan correctness 0.035 → 0.825, sample 0.687 → 0.803 |
| D35 | Content dates | Skip dates announced as deadlines, starts or postponements | A specification dated by the end of its subject's support, a lease by its start: wrong for any date filter |
| D36 | Reference-date filter | Not kept | The question's period ≠ the source's writing date; recall −3 pts, no trap gain |
| D37 | New reference after step 8 | `time_rules` = `vision_whole_images` + status filter + chronological context + prompt rule 8 | Best on the 41 target questions (0.790) and on the types where traps matter; losses are leaner answers, not wrong ones |
| D38 | Final configuration | **`status_filter`** = `vision_whole_images` + drafts and archives out of the search | Level with 47 on 77 judged questions (0.794 vs 0.806, within noise), trap rate 0.471 → 0.353; `chronological` and `time_rules` hurt the image questions |
| D39 | Results export | `results/*.csv` without the eval questions and expected answers | The repository is public; the eval set is course material |
| D40 | Phase B's repository | **This repo** (public), not a separate private `text2sql-calorvia` as the statement asks | Your choice. The course material stays out of Git (`enonces/` ignored): SQL scripts, payslip PDFs and the presentation's expected answers are never committed; generated schemas hold no data values |
| D41 | Running the sources | The course's compose file as is, from `enonces/`, with `--env-file .env` (our one `.env`); ERP on **14330** as that file publishes it (the guide says 1433) | No copy of course files in the repo; one place for passwords |
| D42 | Starter questions | Our SQL in `sql/starter/`; the questions and expected answers read at run time from the presentation | Same rule as D39: the repo is public |
| D43 | Payroll privacy (was O5) | **Aggregates only**: salary columns only inside SUM/AVG/COUNT (MIN/MAX and window functions refused), only in a plain SELECT, and each group must cover ≥ 5 distinct people (counted by a second query before the real one). One narrow tool for the single individual figure a finance question needs: `get_sales_commission` (salespeople of the ERP only) | Your choice. Enforced on the SQL by the server, not by the prompt; MIN/MAX of a group *is* one person's salary |
| D44 | MCP SDK | `mcp` 2.3: FastMCP is now `MCPServer` (`mcp.server.mcpserver`); streamable HTTP on **9001**, stdio as an option | Latest SDK; 9000 is kept for the agent's OpenAI endpoint (step 13), 3000–3003 for auto-ontology |
| D45 | What runs is what the model wrote | sqlglot only *checks*; the query text is never regenerated. Row limit: `LIMIT n+1` appended (PostgreSQL), `SET ROWCOUNT n+1` in the session (SQL Server) | sqlglot's output rewrote `ROUND(AVG(x), 2)` into `ROUND(CAST(AVG(x) AS DECIMAL), 2)`: equivalent here, but the CFO must read the query that ran |
| D46 | Query log | `t2sql_query_log` in the course PostgreSQL; a row is written **before** the query runs, completed after; no log → no query | Traceability can't depend on the query finishing |
| D47 | SQL Server for auto-ontology (was O6) | A **PostgreSQL copy** of GESPRO (`scripts/copy_erp.py`, lower-case names, keys kept), not Trino | Both built and ingested: same tables and columns, but **41 foreign keys** through the copy, **0** through Trino (it exposes no constraints); the copy's cost, staleness, is nil for an ERP frozen on 31/05/2026 |
| D48 | Running auto-ontology here | Host networking (the firewall drops Docker's bridge → host model servers), everything bound to 127.0.0.1, local models only (`openai/` alias for structured output), five patches kept in `ontology/patches/` | Each patch fixes a measured failure; see `ontology/NOTE.md` §3 |
| D49 | How the agent uses the ontology | As **knowledge** (terms, certified definitions and metrics, join paths), not as an answering engine; every query still goes through our MCP server | auto-ontology runs SQL on the ERP copy, would show individual salaries with names (D43), and cannot combine two databases |
| D50 | Agent framework (was O4) | **LangGraph**, an explicit `StateGraph` (`agent → tools → … → check → finish`, plus `wrap_up`) rather than the prebuilt ReAct agent; **one agent** for the three sources | Your choice of LangGraph (testable in Python). The explicit graph puts the retry bound, the grounding check and the footer in code; one agent is enough while the cards carry each source's knowledge (to revisit in step 14 if cross-source questions fail) |
| D51 | MCP client | The `mcp` 2.3 SDK's own `Client`, not `langchain-mcp-adapters` | The adapter (0.3.1) does not import with `mcp` 2.x; ten lines replace it, and hide `question`, `session_id`, `max_rows` from the model |
| D52 | Rows: fetching vs showing | The agent fetches up to **2 000 rows** per query (server cap 5 000, default for other clients still 200), keeps them in its state as `q1`, `q2`…; the model sees **50**; `reconcile` reads the full rows by id | The cross-source question overflowed the 32k context (38 623 tokens) with rows the model did not need; no GPU memory left for a larger context |
| D53 | Transparency | The footer (every query as run, source, engine, rows; every reconciliation) is built by the `finish` node from the state; a footer the model writes is removed | The CFO must see exactly what ran; a model can forget, shorten or rewrite a query |
| D54 | Grounding check | Every number ≥ 1 000 of an answer must be found (± 0.5 %, or as the sum/difference of two found numbers) in this question's tool results or the conversation; else one retry, then "je ne sais pas" (no query ran) or the numbers flagged | Found in testing: on "et pour avril ?" the model invented 13 999 646,63 € (real: 12 099 823,09 €) with a copied footer, without calling a tool |
| D55 | Endpoint | FastAPI on **127.0.0.1:9000**; streaming sends the steps as they happen in a `<details>` block, then the answer (not token by token); earlier answers sent back by the client lose that block, and their footer becomes a short query note | Progress during 10–150 s answers; the check must run on the whole answer before it is shown, so the answer itself cannot stream before it |
| D56 | "Today" for the agent | **31/05/2026** (`data_until`): "ce mois-ci", "cette année" read from that date | The sources stop there (ERP frozen on 31/05/2026, D47) |
| D57 | The evaluation set in the repo | **Committed in full** (`evaluation/t2sql_questions.yaml`: questions, reference SQL, expected answers); the 12 starter questions stay read from the presentation (D42) | Your choice; the set is ours, not course material |
| D58 | Dev / test | **33 dev, 18 test** (one in three per category, never a starter question); test run once, in step 16 | Your choice; the starter questions built the ontology, so they are training questions |
| D59 | Scoring | Correctness by code: every expected number and date in the **prose** (0.5 % on amounts, counts exact), expected names, the first *oui/non* for yes/no questions, forbidden patterns (salary, national number, IBAN). Behaviour by the agent's model as judge, backed by two rules; answers **re-scored**, not re-asked, when the scorer changes (scorer commit kept apart) | The first scorer gave 33/33: a wrong conclusion passed on its numbers (X05), and the judge took a stated definition for an offered alternative. After the fixes, 30 behaviour answers read by hand: judge alone 28/30, with the rules 30/30 |
| D60 | Fixes kept after step 14 | `no_repeat` (identical query not run twice), `pay_elements` certified (28 terms), `COUNT(*)` allowed on partly hidden tables (MCP validation), `yes_no_first` (prompt). **Rejected:** `offer_readings` (reversed in step 16, D64) | Each fixes a failure seen in a trace (8 identical queries; the wrong account; a validation bug; "Non, pas d'écart" when equal). `offer_readings` left its two target questions failing: the model does not see "le résultat" as ambiguous, and a prompt sentence does not change that |
| D61 | Charts | `make_chart` (matplotlib) on a result id; PNG in `data/charts/`, served by the endpoint at `/charts/<16-hex id>.png`; the Markdown image added by `finish` | Open WebUI shows Markdown images; the link must be exact, so the code writes it (as the footer, D53) |
| D62 | Conversations | `t2sql_conversations` / `t2sql_messages`; id = the completion id of the first answer, carried by a hidden `<!-- calorvia:conversation=… -->` at the end of each answer (or an `X-Conversation-Id` header) | The API is stateless; a hash of the first question would merge conversations that start alike |
| D63 | Learned memory | Only on explicit request (`remember`), per user, never personal payroll data; in the prompt as **data below the rules**; `forget` deactivates; **off in evaluations** | A memory is a prompt injection that survives the conversation; the rules that matter are enforced by the server anyway. An evaluation must not depend on what was remembered |
| D64 | Final configuration and report | `experiments/t2sql/final.toml`: with ontology, the fixes of D60, the step 15 tools, **and `offer_readings`** (reverses D60's rejection). Report in `RAPPORT_T2SQL.md` (`RAPPORT.md` is phase A's); exports in `results/t2sql/` | `offer_readings` scored 31 and 30/33 in two runs against 29 and 29 without it, and its second run fixed A03 by its own mechanism (the other readings named). One repo for both phases (D40), so one report each |
| D65 | Payroll rule as an allowlist (revises D43) | A query reading a salary may only be one plain SELECT returning aggregates: SUM/AVG/COUNT over columns and constants, salary filters as constant comparisons joined by AND, no whole-row reference. People are counted per salary column, on that column's table, without HAVING, ignoring rows whose amount is NULL or 0 | The first rule listed forbidden forms, and a review got individual pay through it four ways (step 17). What is allowed can be listed; what is dangerous cannot |
| D66 | Network exposure | Every database, Qdrant and model server listens on **127.0.0.1**. Ours in `docker-compose.yaml`; the course's three sources through `docker-compose.sources-local.yaml` (`ports: !override`), with the course file untouched; vLLM with `--host 127.0.0.1`. Reach them from another machine with an SSH tunnel | All clients run on this machine. They were reachable on the LAN and Tailscale addresses, with course passwords, and nothing needed that |
| D67 | The final test set | `evaluation/t2sql_final_questions.yaml`: 32 new questions (6 ERP, 5 accounting, 5 payroll, 4 cross-source, 4 ambiguous, 3 impossible, 5 malicious), separate from the step 14 file. Its SHA-256 is in `evaluation.py`; `--final` runs it whole, from a clean commit, and once | The phase B test set has been read. A separate file keeps it out of everyday work, and the fingerprint and the run guard turn "don't touch it" into checks |
| D68 | Ambiguous business words | `business_words` in `ontology/certification.yaml`: five words, each with its readings. When a query ran, the question doesn't settle the reading and the answer leaves some out, the `finish` node writes them under the answer | The model doesn't find a word ambiguous when it has a metric for it, so the prompt rule rarely fires (A03). Same principle as the footer (D53): what must always happen is written by code |
| D69 | Joins that multiply rows | A **warning**, returned with the query's rows, when a joined table references a table already in the query and `COUNT(*)`, or `SUM`/`AVG` of an earlier table's column, reads the multiplied rows (`joins.py`, from the catalog's foreign keys). Not for `COUNT(*)` grouped by the parent | Counting lines can be what was asked, so it can't be a refusal; the model reads the warning and corrects itself (C02) |
| D70 | Rows in the cards | A table of at most 30 rows, keyed by a code and with several code columns, shows its rows (`mapping_rows`). Only values the card already lists | The separate value lists were read as pairs (X05). Tables keyed by a number (salespeople, suppliers) are records: showing rows would link their identities |
| D71 | Small figures | Below 1 000, only figures that say what they are: a whole number followed by what it counts, and percentages. Checked against **query results** (cells, row counts, column totals, days between dates, reconciliations) and the client's messages, not the prompt or the cards. Percentages may be a ratio or a change between two result numbers. Same path as D54: one retry, then flagged | A bare small number may be a year or an account; and the prompt and cards hold so many small numbers that "found somewhere" would prove nothing |
| D72 | Who is calling | `API_KEYS=name:key,...`: `/v1` needs a bearer key, and the user is the key's name; the `user` field is then ignored and conversations are private to it. `TRUSTED_GATEWAYS` lets a shared key (Open WebUI) name its end user, as `gateway/user`. Without keys: local mode, and the server refuses to listen beyond loopback. Chart links stay open, with random ids | Memory was tied to whatever the client claimed. An image tag can't send a key |
| D73 | Payroll beyond one query | Identifiers only in joins or `COUNT(DISTINCT)`; sickness (`absence_code`, `absence_hours`) follows the salary rules unless the query keeps only other codes; the server remembers the rows behind each aggregate and refuses one that differs from an earlier one by 1–4 people | Differencing was the known gap. Comparing **rows**, not people, lets different months pass, since they share none |
| D74 | Role-based access | Permissions follow **roles**, not individuals. Enforced by the data layers: one read-only database login per role, row-level security keyed on that login, an `allowed_roles` filter inside the Qdrant search. Denied by default. The payroll rules stay on top | The model must have no way to reach forbidden data. Rewriting its SQL would break D45 and can miss a subquery; a login can't be spoofed by a query |
| D75 | The roles (was O9) | Ten roles, listed under Phase D: `direction`, `finance`, `rh`, `commercial`, `achats`, `operations`, `qualite`, `responsable_site` (one per site), `it`, `employe` | Your choices: `finance` reads the CODIR minutes; `rh` has no accounting; site managers see absences as aggregates; `commercial` is company-wide; quality is a role of its own |
| D76 | Row limits | PostgreSQL row-level security on `departments`, `contracts`, `timesheets`, SQL Server security policies on six ERP tables and two line tables, in a schema `access_control` holding the login-to-site mapping. A day of timesheet belongs to the site of the contract running that day. Every login other than the site roles keeps all rows | The database applies the limit to every query shape, and it follows the login, which a query can't change |
| D77 | Document permissions | `allowed_roles` on every chunk, computed from `policy/roles.yaml` and required inside each search prefetch; no value means no role. A role reading **any** copy of a file reads the document kept for it. Written with `set_payload`: no re-embedding. The registry doesn't store it: the policy file stays the one source | `finance` reads the CODIR annexes, one of which is kept under `06_Achats`: requiring every copy would also have cost `achats` its own file |
| D9 | Porting strategy | Port each hospital_rag module **in the step that needs it** (step 0: config, db, logs; step 3: evaluation; step 4: ETL and RAG) | Nothing unused or untested sits in the repo |

### Open decisions (to settle with you when we reach them)

| # | Question | When |
|---|---|---|
| – | None open at the moment. | – |

---

## Working conventions

- **One step = one branch** (`rag/step-03-eval`), small commits in English imperative mood, merged into `main` when the step is measured.
- **A baseline first, then one change at a time.** Every experiment is a TOML file in `experiments/`, every run is stored in PostgreSQL **with its git commit** (`git_dirty = false` for anything that goes in the report).
- **Dev/test split:** the 31 questions whose number is a multiple of 5 are the held-out test set. We never look at them before step 9. The eval set measures, it never builds: no expected answer in a prompt, no rule written for one question.
- At the end of each step: update this roadmap (status, notes, results) and add the step's quiz to `QUIZ.md`.

### Services (one 24 GB GPU)

| Port | Service | Model |
|---|---|---|
| 8000 | LLM (llama-server) | `qwen3.8-27b` (Q4; your choice, replacing exercise 3's `qwen3.5-9b`) |
| 8001 | Embedder (vLLM) | `bge-m3` |
| 8002 | Reranker (vLLM) | `bge-reranker-v2-m3` |
| 8003 | VLM (llama-server `--mmproj`), then judge | VLM: see O3; judge: `gemma4-26b-a4b` (D21) |
| 5432 | PostgreSQL (registry, experiments) | Docker |
| 14330 | Source: ERP GesPro (SQL Server 2022) | Docker, course compose (D41) |
| 5433, 5434 | Sources: accounting, payroll (PostgreSQL 16) | Docker, course compose (D41) |
| 9001 | MCP server `calorvia-sources` (streamable HTTP) | `python -m text2sql_calorvia.mcp_server` |
| 9000 | The agent's OpenAI-compatible endpoint, model `calorvia-agent` (D55) | `python -m text2sql_calorvia.api` |
| 3000-3002, 5435 | auto-ontology: web app and API, backend, ingestion; its PostgreSQL | `ontology/ao.sh`, 127.0.0.1 only (D48) |
| 5436 | The ERP's PostgreSQL copy (D47) | `ontology/docker-compose.yaml` |
| 8000 | for auto-ontology the generator is served as `openai/qwen3.8-27b`, 32k context | see `ontology/NOTE.md` |
| 6333 | Qdrant | Docker |

---

## Phase A: the RAG

### ✅ Step 0. Project setup
**Goal:** a repo that runs the exercise 3 machinery against an empty Calorvia index.
- `pyproject.toml`: dependencies of hospital_rag + `openpyxl`, `py3langid`, `pillow`; dev group with `pytest`.
- `docker-compose.yaml` (PostgreSQL + Qdrant), `.env.example`, `.gitignore` (`data/`, `.env`, `qdrant_storage/`, `*.log`, `.ipynb_checkpoints/`).
- Port `config.py`, `db.py`, `logs.py`; `data/calorvia` symlink; the hints notebook moved to `notebooks/`.
- `git_state()` and the `git_commit`, `git_dirty` columns on the `experiments` table.
- **Done when:** `uv sync`, `docker compose up -d` and `uv run pytest` pass; settle O1 and O2.
- **Result:** 4 tests pass (3 on `git_state`, 1 integration test writing an experiment to PostgreSQL). The schema has `git_commit` / `git_dirty` directly in `CREATE TABLE` (fresh database, no `ALTER` needed). Notebook not moved (D6).

### ✅ Step 1. Inventory → `etl/inventory.py`
**Goal:** a registry: one row per file in a `documents` table.
- Walk the corpus: relative path, format, size, SHA-256, page count, text layer (PDF: native vs scan, with PyMuPDF).
- `excluded_reason`: exact duplicates (same hash, keep one), personal data (`02_RH/Confidentiel/`), blank templates (`Modeles/`), noise (`99_Archives/Divers/`). Nothing is deleted, only excluded in the registry.
- **Concepts:** content hashing, idempotent ETL, a registry as the single source of truth for the index.
- **Result:** 393 files, **379 to index**, 14 excluded: 7 duplicates (4 in `Doublons/`, the ERP grid and the 8D report in the CODIR annexes, the telework v3 PDF), 4 noise, 2 templates, 1 personal data. 9 scans (no text layer) found. 339 Docling conversions in 42 s on GPU, 0 failures.
- **Surprise:** the statement says "exact duplicates (same hash)", but no two files share a SHA-256: DOCX/XLSX are zips that store their own dates (`docProps/core.xml`), and PDFs embed a creation date and an `/ID`. Hence `content_hash`.
- **Eval check:** the eval set lists every copy of a duplicate as valid evidence, so keeping one copy loses nothing. Step 3 must still make sure the metrics don't count the kept copy as a miss when a question cites only the excluded one.

### ✅ Step 2. Metadata → `etl/metadata.py`
**Goal:** date, type, version/status, language, department, source type for every document.
- Several filename patterns (CODIR 2025 vs 2026, CA, COPIL, PBW, monthly reports, invoices, `IMG_YYYYMMDD` photos), then fall back on the content ("Séance du lundi 13 octobre 2025").
- Version and status markers: `v1`, `v2`, `Projet PV`, `copie`, `Copie de`, `(1)`, `FINAL`, `Archives`, `Doublons`, `Modeles`.
- Document-level language with `py3langid` (per chunk comes in step 5).
- Unit tests on real file names.
- **Tag `rag/v0.1-inventaire`.**
- **Result:** 49 type rules (the last one a `workbook` fallback); on the 379 indexed documents, 1 untyped (`README.md`), 38 undated (product sheets, timeless policies, images whose date only the VLM can read). Dates: 219 from precise file names (160 days, 50 months, 2 quarters, 7 ranges), 10 from photo names, 89 from content, 23 from a bare year. Languages: 38 nl and 7 en documents, as in the statement; images and scans: unknown until step 7. 57 tests green.
- **Bugs caught while reviewing the output:** `\b` doesn't separate `_` from `v2` (`PV_CODIR_…_v2` had no version); the 2026 board minutes are signed by their folder, not their name; the first date of a workbook is a data row (serial-number list dated by its first unit's production date); `projet` alone flagged the intranet page "Le projet Atlas" as a draft.
- **Not done here, on purpose:** the context line goes into the chunks in step 4 (it uses `doc_label` + `doc_date`); families of versions (which v is the latest, `valid_from`/`valid_to`) are step 8.

### ✅ Step 3. Evaluation adapted to Calorvia
**Goal:** measure before building more.
- Load `calorvia_eval.json`; dev (127) / test (31) split, enforced in code.
- `document` is now a relative path; `normalize()` gains `normalize_numbers()`.
- New metric `trap_hit@k`; results **per question type** and per document format; refusals on `out_of_corpus`.
- Judge sample: 2 questions per type from the dev set.
- **Result:** `evaluation/dataset.py`, `metrics.py`, `coverage.py`, `scripts/check_eval.py`; 91 tests green. The runner, the DeepEval judge and the per-type / per-format report move to step 4: they need the search pipeline and a generated answer.
- **The ceiling (dev set):** **101 of 122** questions with evidence can be answered from the text we index. The 21 others: `image_only` 0/13, `scan_ocr` 1/6, `image_in_document` 0/1 (a chart value in the RSE PDF), and one question each in `board_resolution` and `multi_doc` (a scanned board minute, a scanned customer letter). Every non-visual evidence snippet is found in Docling's text.
- **Data bug found:** the eval set cites `Test d'etancheite Aeris.pdf` and `Rayonnages de l'entrepôt de Herstal.docx`; the corpus writes `_` for `'` in file names. Without alignment, 2 `factual` questions were unreachable.
- **Number normalization:** no effect yet (101/122 with or without), as our text is still Docling's. It matters from step 6.

### ✅ Step 4. Baseline
**Goal:** the reference everything else is compared to.
- Docling conversion of the text documents only (DOCX, native PDF, HTML, PPTX, MD, CSV, XLSX as Docling sees them), with a cache in `data/conversions/`.
- Chunks with a **context line** ("[PV du CODIR du 13 octobre 2025 · 00_Direction/CODIR/2025]"), metadata in the payload, payload indexes on filterable fields.
- Exercise 3's best configuration (hybrid + RRF, 30 candidates, bge-reranker, 5 chunks, `combined_v2` prompt, header/boilerplate removal).
- Experiments: `baseline`, and `baseline` without the context line.
- Expected: `image_only`, `scan_ocr`, `image_in_document` fail.
- **Tag `rag/v0.2-baseline`.**
- **Result, retrieval** (127 dev questions, commit `ff76258`, runs 13–14):

  | | recall@5 | hit@5 | MRR@5 | trap_hit@5 |
  |---|---|---|---|---|
  | `baseline` | **0.783** | 0.811 | 0.709 | 0.353 (6/17) |
  | `no_context_line` | 0.684 | 0.713 | 0.582 | 0.412 (7/17) |

  The context line is worth +10 recall points; biggest effects: `meeting_detail` 1.00 vs 0.55, `multilingual` 0.93 vs 0.43, `excel_reasoning` 0.90 vs 0.40. On the 101 questions reachable from text, recall@5 = **0.941**: retrieval is close to the ceiling; the misses are mostly decision threads (Q008, Q081, Q133: current state of a changing decision), i.e. step 8.
- **Result, generation** (run 15, Qwen3.8-27B): 6 min for 127 questions, 2.6 s per answer, 36 tokens on average. Refusals: `out_of_corpus` 5/5; 2 wrong refusals (Q093, Q117); 3 image questions answered from neighbouring text (Q059 gives the machine's ID as its serial number: wrong; Q114, Q139: partial).
- **Q093 analysed:** the right chunk is in the context (recall 1.0), but Docling serialized the report's 2-column table with its first data row as header: `Incidents, Taux de clic : 4 % … = Aucun incident majeur`. The label "Simulation d'hameçonnage (mai)" is lost. A table-serialization problem → idea for a later experiment (Markdown tables).
- **Judge** (Gemma 4, 31-question sample, 9 min, 0 failed verdicts):

  | | correctness | faithfulness | answer relevancy | contextual precision | contextual recall |
  |---|---|---|---|---|---|
  | all 31 | 0.658 | 0.856 (26) | 0.995 | 0.865 | 0.759 |
  | without the 5 image/scan questions | **0.762** (26) | 0.844 | 0.994 | 0.962 | 0.875 |

  - **Correctness is credible.** Real errors: Q008 (outdated recall status), **Q023 falls into the trap** (1.2 M€, corrected in the next minute), Q024 (the answer says the Dutch contract's cost isn't in the extracts; *corrected in step 5*: it was right, the price chunk wasn't retrieved, so the judge erred again). Most 0.7 scores are right but terse answers (the prompt asks 1–3 sentences; the judge wants every detail).
  - **Faithfulness is not.** Checked by hand: 4 of the 5 claim-based penalties are judge errors (Q004, Q026, Q043, Q052: the claim is in the cited chunk), the 5th a nitpick (Q001). Read it as a lower bound; don't conclude from small differences.
  - **Measurement fix:** a refusal is no longer judged on faithfulness (it makes no claim; Gemma scored "Je ne sais pas" 0). The 3 rows already stored (Q014, Q034, Q144) were deleted from run 15.
- **For step 9's report, three failures already analysed:** Q093 (table serialization, conversion), Q023 (trap, versions → step 8), Q024 (Dutch price chunk out of the top 5: the French-question reranker, see step 5).

### ✅ Step 5. Languages
- Language per chunk in the payload; BM25 stemmer chosen by language.
- Experiment: translate the question to Dutch and English, search each, fuse with RRF.
- System prompt: always answer in French.
- Measure: `multilingual`, all other types, latency.
- **Tag `rag/v0.3-langues`.**
- **Result** (127 dev questions, retrieval-only for 5a/5b, generation for 5c):

  | Experiment | Change | recall@5 | `multilingual` recall@5 | latency |
  |---|---|---|---|---|
  | baseline | – | 0.783 | 0.929 | 2.8 s |
  | 5a `bm25_per_language` | language per chunk, BM25 stemmer per language | 0.779 | 0.929 | = |
  | 5b `translate_question` | 5a + question in nl/en, 6 searches fused by RRF | 0.766 | 0.929 | **+2.2 s** |
  | 5c `prompt_multilingual` | baseline + prompt rule for nl/en extracts | (= baseline) | (= baseline) | +0.06 s |

- **Why 5a and 5b don't help here:** the baseline already finds the Dutch documents through dense search and the French context line (6 of 7 `multilingual` questions have recall 1.0). Per-chunk language equals document language for every chunk of this corpus (no mixed documents). 5a alone can't help: the query is French.
- **The interesting finding (Q024):** translation works *at the candidate stage*: the Dutch query brings the contract's price chunk from outside the 30 candidates to rank 4. Then the reranker, scoring it against the **French** question, puts it 11th, out of the top 5. Also, the LLM translated "chariots élévateurs" as "reachstackers" instead of "heftrucks": domain vocabulary needs context. Idea for later: rerank each chunk against the version of the question in its language.
- **5c:** all 127 answers were already in French in the baseline (new metric `answer_in_french`, 1.000). The rule changes 29 answers (part is llama-server's non-determinism at temperature 0); one wrong refusal (Q117) becomes an honest partial answer. **Not judged yet:** to judge with the next judge pass (needs the Gemma swap).
- **Fixed on the way:** `--retrieval-only` replaced the whole `[generation]` section, so translation couldn't find its model (run 20 failed).

### ✅ Step 6. Excel → `etl/excel.py`
- `openpyxl` with `data_only=True`, every sheet; find the tables (title, header, rows, notes).
- One sentence per row with its context; values displayed as in Excel (percentages, dates); grouped rows with repeated header + a summary chunk for big tables.
- Payload: file, sheet, row number, period, version.
- `excel_reasoning`: RAG only vs a few polars/SQL functions the LLM picks (tool calling).
- Measure: `excel_lookup`, `excel_reasoning`, `version_trap` (budget, price list).
- **Tag `rag/v0.4-excel`.**
- **Starting point:** the reference already answered most workbook questions (`excel_lookup` recall 1.0). What failed: units lost (Q137 "702" without k€), answers spread over many rows (Q158: the installer of the 3 missing units among 214 rows), percentages unreadable in Docling's text (`-0.0068`).
- **6a `excel_openpyxl` → `_v2`** (`[chunking] excel = "openpyxl"`): per sheet, tables with their title and unit, values as Excel shows them (percentages, dates), notes kept; small tables (≤ 30 rows) as one sentence per row + the table in Markdown; big ones as Markdown groups with the header repeated + a summary with the counts of each categorical column. 1449 → 1919 chunks.
  - First version: `excel_reasoning` recall 0.9 → 0.7. Two causes, found by checking that every workbook snippet of the eval still exists in some chunk: a key/value line (`Heures de formation à la sécurité | 620`) read as the header of an empty table and dropped; the 214-row list's rows out of the top 5 (Q158). v2 keeps key/value lines as text and adds value counts to summaries: recall back to the baseline (0.783, `excel_reasoning` 0.9).
  - Answers: Q137 gets its unit (702 k€), Q043 names the approved budget; the draft price list now reaches the top 5 of Q089 (`version_trap` trap_hit 0.67 → 1.0), for step 8.
- **6b `tools_tables`** (`[tools] tables = true` + prompt rule 7): every table of the indexed workbooks in an in-memory SQLite (raw values, a `catalog` with document, sheet, title, columns, date, status); tools `find_tables`, `describe_table`, `run_sql` (one SELECT, read-only by `PRAGMA query_only`, ≤ 50 rows, errors returned as text), at most 5 rounds.
  - Used on 13/127 questions (3 of 5 `excel_reasoning`). Q158 answered (SQL `GROUP BY Installateur`); Q137 richer; Q127's wrong "Non" becomes a cautious partial; image questions still refused. +0.4 s mean latency, max 9.1 s.
  - **SQLite trap found by a test:** an unknown double-quoted name is read as a string literal (`SELECT "Chiffre"` → the text 'Chiffre', no error). Turned off with `SQLITE_DBCONFIG_DQS_DML`.
- **Index staleness fixed:** a collection was reused when its point count matched, even if the chunking *code* had changed. Each point now carries a fingerprint of all chunk texts; a mismatch rebuilds.
- **Judge** (Gemma 4). On the 31-question sample, correctness: baseline 0.658, `prompt_multilingual` 0.655, `excel_openpyxl_v2` 0.648, `tools_tables` **0.687** (0.792 without image/scan questions). The sample's `excel_lookup` swung 0.85 → 0.45 on one answer (Q017: "six personnes" instead of "6 ETP"), so the workbook types were judged on **all** their dev questions (new `--types` option):

  | correctness | Docling (23) | openpyxl reader (30) | reader + SQL tools (33) |
  |---|---|---|---|
  | `excel_lookup` (13) | 0.769 | 0.715 | 0.762 |
  | `excel_reasoning` (5) | 0.840 | 0.840 | **0.980** |
  | `version_trap` (4) | 0.825 | 0.825 | **0.925** |
  | all 22 | 0.795 | 0.764 | **0.841** |

  - **The tools are the gain** (Q158 0.5 → 0.9, Q069, Q137, Q043 → 1.0). **The reader alone is not better than Docling on correctness** (its one real loss: Q017's ETP read as people); its value is what it enables (raw values for SQL, units, readable percentages).
  - **Untested:** Docling chunks + the tools (the store reads the workbooks itself). Worth a run if the reader's extra chunks ever cost elsewhere.
  - **Unchanged and still wrong:** Q008 (outdated recall status), Q023 (the trap: 1.2 M€): step 8.

### ✅ Step 7. Images and scans → `etl/vision.py`
- Serve the VLM (O3); transcribe every image and every scanned PDF page **once**, cached, with timings.
- Read the charts of the two PDFs that have them.
- Image chunks: context line + transcription; payload has the image path and page.
- Check 10 transcriptions by hand; compare VLM vs Docling OCR on `scan_ocr` (quality, time).
- Bonus: show the source image under the answer.
- **Tag `rag/v0.5-images`.**
- **Transcription** (Qwen3.5-9B Q4 + its `mmproj`, llama-server on 8003, notebook prompt: copy every visible text, then a « Description »): 66 targets = 54 images + 9 pages of the 8 indexed scans + 3 charts embedded in the 2 PDFs that have them. **≈ 6 min in total** (5.3 s per image on average, 11–14 s per scanned page), 0 cut. Cached in `data/vision/` (key = path, page, model, prompt).
- **10 transcriptions checked by hand** against the images (network diagram, SWOT whiteboard, Pareto chart, Herstal plan, RSE chart, org chart, nameplate, invoice, delivery note with handwriting, Gantt): ≈ 75 numbers and 40 names compared.
  - **0 wrong number, 0 wrong name**; 1 accent typo ("Aérís"). The blurry "1120 °C", the IBAN, both handwritten notes and the date half-hidden by the go-live line are right.
  - **9 omissions:** the 6 labels drawn along the links of the network diagram (bandwidths: Q034's answer), the nameplate's maker and subtitle, the SWOT footnote (only in the description).
  - **4 inventions:** a "Description" column added to the Herstal plan's zones.
  - The *descriptions* are less reliable than the transcriptions (a delivery note called an invoice, a signature placed on the wrong side).
- **VLM vs Docling OCR (RapidOCR PP-OCRv6, CPU) on the 8 scans:** both find the 7 dev evidence items (7/7); OCR 46 s vs VLM 77 s. But word by word on the 18/11 board minute, the OCR garbled two lines (the attendance list, and **the L4 resolution itself**: "lleon l e d ent s e ion"); the VLM got every line. VLM kept: one tool for scans and images, better text.
- **Ceiling with the transcriptions: 121/122** (was 101): only Q034 (the skipped link labels) stays unreachable.
- **Retrieval** (`vision` = `tools_tables` + `[chunking] vision = true`, 2049 chunks): recall@5 **0.783 → 0.934**, hit@5 0.811 → 0.959; `image_only` 0 → 0.846, `scan_ocr` 0.167 → 1.0, `image_in_document` 0 → 1.0, `board_resolution` 0.833 → 1.0. trap_hit@5 0.412 → 0.471: the scanned minutes holding the corrected 1,2 M€ are now readable, hence retrievable (step 8).
  - Misses: Q034 (not transcribed); **Q056**: the org chart's transcription is longer than 256 tokens, split in two, and the two names the answer links (Céline Moreau, Thomas Lambert) land in different chunks. Idea: one image = one chunk.
- **`vision_whole_images`** (`[chunking] vision_max_tokens = 1024`): at 256 tokens 45 of the 65 images/pages were cut in several chunks, at 1024 only 1 (largest chunk 940 tokens; embedder and reranker accept 2048). Retrieval: same recall@5 (0.934): Q056 found (and its trap, the September 2025 org chart: step 8), Q087 (a workbook value) pushed out by a long image chunk.
- **Judge** (Gemma 4; every image/scan question, and the 31-question sample):

  | correctness | `tools_tables` (no vision) | `vision` | `vision_whole_images` |
  |---|---|---|---|
  | 20 image/scan questions | 0.035 | 0.765 | **0.825** |
  | sample (31) | 0.687 | 0.800 | **0.803** |
  | `out_of_corpus` (2) | 1.00 | 1.00 | 1.00 |

  Answers now right: Q059 (the serial number, wrong in step 4), Q084 (1120 °C), Q139 (the first ERP schedule), Q064 (the handwritten note), Q056 and Q147 (reporting lines, only with whole images). Still unanswerable: Q034.
  - The `refusal` metric fell to 4/5 on `out_of_corpus`: Q116 got an honest partial answer ("depuis 2011… ne précisent pas avant"), which the judge scores correct. A metric that matches one sentence can't see that.
- **Bonus done:** `rag/images.py` lists the images (and scanned pages) of the extracts an answer cites; `scripts/ask.py` prints them ("image to show: …"). The UI that displays them comes with step 9.
- **Ops:** the session started and stopped the model servers itself (detached `setsid nohup`, logs in the scratchpad). One slip: a `pgrep -f` also matched its own shell, `kill` failed and a broken check printed "stopped"; caught by checking the processes and the GPU before going on.

### ✅ Step 8. Time and versions
The hardest part. Each idea measured on its own, then combined:
0. **First, a date bug found in step 7:** `Cahier des charges ERP Atlas.docx` is dated 31/12/2026 (the end of GesPro's support, the first date in its text), and its context line says so. The content-date heuristic picks dates that are *about* something else; audit the content-dated documents before filtering on dates.
1. Registry status → Qdrant `must_not` filter on drafts, duplicates, noise; `valid_from` / `valid_to` on old versions.
2. Reference date extracted from the question by the LLM; the code applies `date <= reference`.
3. Chunks sent to the LLM in chronological order, each with its date.
4. Prompt rules (latest decision wins, a draft is not authoritative, a corrected minute beats the one it corrects).
5. More candidates for decision-thread questions.
6. CODIR decisions and action-tracking tables extracted to PostgreSQL; `action_tracking` answered in SQL.
- Measure: `decision_*`, `board_resolution`, `version_trap`, `action_tracking`, and **trap rate before/after**.
- **Tag `rag/v0.6-versions`.**
- **Starting point** (reference `vision_whole_images`, run 46/47): recall@5 is ≈ 1.0 on the target types; the problem is the traps: 9 of the 17 questions with traps have one in their top 5 (trap_hit@5 0.471). The 27B already ignores most of them in its answers (draft minutes, draft price list, old budget versions): the differences are in the wording, hence a judge pass on all 41 target questions.
- **8.0 Content dates audited** (89 content-dated documents read): 7 dates were *about* something else (the end of GesPro's support for the ERP specification, a postponed go-live, "jusqu'au", "à compter du", "from", "vanaf"). `content_date` now skips a date preceded by such a cue and keeps scanning; first version wrongly skipped "stand **van** zaken" (Dutch "van" = "of"), caught by a test. Exactly those 7 documents changed; no metric moved (`dates_fixed`, run 53), but the dates are now safe to filter on.
- **8.1 `status_filter`** (`[search] exclude_status = ["draft", "archive"]`, Qdrant `must_not` in every prefetch; 4 drafts, 5 archives): trap_hit@5 **0.471 → 0.353** (`board_resolution` 1.0 → 0.33, `version_trap` 1.0 → 0.67), recall@5 0.934 → 0.939 (freed places). One new trap: Q063's freed place went to the 17/11 CODIR (8 km/h, superseded in January by 6 km/h): an outdated *signed* document, not a status problem.
- **8.2 `chronological`** (`[generation] order = "chronological"`: extracts sorted by date, oldest first; retrieval metrics keep the reranker's order, citations and stored chunks follow the LLM's order): Q081 now answers "680 k€, puis 725 k€" instead of "the extracts don't say".
- **8.3 `time_rules`** (prompt rule 8: latest decision wins, a draft minute isn't authoritative, a correction prevails, give the decision's date, a question about a past date gets the state at that date): answers now date their decision (Q063 "décision D-26-01 du CODIR du 12 janvier 2026"). Q023 still starts with 1,2 M€ before the correction.
- **8.4 `reference_date` — not kept.** The LLM extracts the period a question is about (31 of 127 questions got one) and the code keeps `doc_date ≤ reference` or undated: recall@5 0.939 → **0.910**, trap rate unchanged, +1 s per question. Why: **the date a question is about is not the date its source was written** — the May 2026 phishing test is in the report of 3 July (Q093), "fin mai" is answered by the 22 June CODIR (Q127), March absenteeism by a later report (Q112). Reports always come after their period; a filter on the document date removes them. And every `decision_history` question was already at recall 1.0.
- **Judge** (Gemma 4, all 41 target questions, ≈ 50 min; 0 failed verdict):

  | correctness | ref (47) | 8.1 status | 8.2 chronological | 8.3 time rules |
  |---|---|---|---|---|
  | `action_tracking` (11) | 0.736 | 0.727 | 0.755 | **0.791** |
  | `board_resolution` (6) | 0.933 | 0.900 | **0.967** | 0.950 |
  | `decision_current` (14) | 0.657 | 0.643 | 0.671 | **0.693** |
  | `decision_history` (6) | **0.933** | 0.900 | 0.867 | 0.817 |
  | `version_trap` (4) | **0.925** | **0.925** | 0.825 | 0.850 |
  | all 41 | 0.785 | 0.768 | 0.780 | **0.790** |

  - **Within noise overall** (one verdict ≈ 0.02 on 41 questions), but consistent by type: the time rules help current decisions, action tracking and board resolutions; `decision_history` and `version_trap` lose because rule 8 makes answers **leaner** (Q043 drops the earlier budget versions, Q066 part of the October context, Q149 the year), not wrong.
  - **Kept: `time_rules`** (status filter + chronological context + rule 8) as the new reference (D37). *Revised in step 9:* judged on the full sample and the image questions, `time_rules` lost 0.135 on images; the final choice is `status_filter` (D38).
  - **The real lesson of the step:** retrieval was already right, and the 27B already ignored most traps in its context (drafts, old budget versions). The remaining errors are Q023 (always states 1,2 M€ first, then the correction) and Q008 (the March closure of the recall isn't in the top 5: a retrieval problem).
- **Not done (idea kept):** CODIR decisions and action tables in PostgreSQL for `action_tracking` (already 0.791 with recall 0.955: little left to win for its cost).

### ✅ Step 9. Final evaluation and delivery
- Pick the best configuration (quality, latency, indexing cost); run it **once** on the 31 test questions.
- Export results to `results/*.csv`; write `RAPPORT.md` (comparison table with commits, per-type and per-format results, trap rate, VLM time and error rate, what didn't help, three failures analysed) and the README.
- A small chat UI (Streamlit) for the demo.
- **Tag `rag/v1.0`.**
- **Final choice reopened.** Step 8 had judged its runs only on the 41 decision/version questions. Judged on the same 77 questions (sample + every image/scan + every decision/version question): `vision_whole_images` 0.806, `status_filter` 0.794, `chronological` 0.788, `time_rules` 0.779; on the 20 image questions 0.825 / 0.820 / 0.765 / 0.690. Traced: the date order made the model read "la première cause" as *chronologically* first (Q107); rule 8 mixed two org charts (Q056) and produced a degenerate `[3]` (Q014). **Final: `status_filter`** (your choice; level with 47 within noise, and drafts/archives kept away from the model).
- **Test set, once** (run 66, commit `4c90d97`, 31 questions): recall@5 0.850 (dev 0.939), MRR 0.651 (0.871), **correctness 0.823** (dev 0.784 on the sample, 0.794 on 77), faithfulness 0.879, answers in French 1.000, 2 refusals (the out_of_corpus one, and Q020). Answers as good as on dev: no tuning to the dev questions. Two of the five retrieval "misses" are right answers from other documents (Q095 from the sales quotes, Q125 by SQL).
- **Delivered:** `RAPPORT.md` (comparison with commits, per type and format, traps before/after, VLM time and error rate, what didn't help, test vs dev, three failures analysed: Q020 chained question, Q060 top 5 crowded by one document, Q008 latest state of a thread), `results/` (experiments, per-type means, final answers **without** the eval set's questions and expected answers: the repo is public), `app/chat.py` (Streamlit: answer, extracts, cited images, SQL), README commands.
- **Caught while writing the report:** four figures written from memory were wrong (a commit hash, two scores, a per-type value taken from another run); all checked against the database and corrected before committing.

---

## Phase B: the text-to-SQL agent

Deliberately more open than phase A: the steps below are a skeleton we will refine when we get there.

### ✅ Step 10. Sources
- Restore the three databases with `enonces/calorvia_t2sql/sources_calorvia/docker/` (ports 14330, 5433, 5434); connect with the read-only `agent_ro` account; explore; run the 12 starter questions by hand in SQL.
- **Tag `t2sql/v0.1-sources`.**
- **Restore:** under a minute for the three; counts as in the guide (10 185 invoices, 20 562 entries, 7 298 payslips). 23 / 14 / 14 tables, 139 308 / 101 045 / 217 612 rows, as the presentation says.
- **Code:** package `text2sql_calorvia`: `sources.py` (the only module that connects, always as `agent_ro`; `pymssql` and `psycopg`), `catalog.py` (tables, columns with a *readable* flag, keys, row counts from the catalog), schemas generated into `docs/sources/*.md` (no data values), exploration notes in `docs/sources/NOTES.md`.
- **12/12 starter questions** answered by hand-written SQL (`sql/starter/`, one file per question and source), checked by `scripts/run_starter.py` against the presentation's numbers and dates; 23–85 ms each. Traps each needs (the ontology's raw material): credit notes stored positive; a `REGUL_TARIF` credit note listing 270 units but returning none (Q2); a return visible only in stock movements (Q3); a duplicate supplier "NE PAS UTILISER" (Q4); the year-end appropriation entry that zeroes classes 6–7 (Q5); EBITDA as a definition over account ranges (Q6); contract rows per period (Q8); 23 ERP invoices not yet transferred to accounting, exactly the May gap (Q11); staff number `10405` vs `M10405` and a rate stored as a percentage (Q12).
- **Layer 1 tested** (`tests/test_sources.py`, 22 tests, statements sent without any validation): writes, DDL, `SELECT INTO` a real table, `xp_cmdshell`, `COPY` to a file are refused on all three; the PostgreSQL grants still refuse writes after `SET default_transaction_read_only = off`; the 3 personal columns are unreadable (so `SELECT *` on `employees` fails). **Gaps found:** temp tables are allowed (SQL Server `SELECT … INTO #tmp`; PostgreSQL once the default is off), and SQL Server has no server-side timeout. Both for step 11's validation and execution layers.

### ✅ Step 11. The MCP server (FastMCP → `MCPServer`)
- Tools: `list_sources`, `list_tables`, `get_table_card`, `find_values`, `validate_sql` (sqlglot, `tsql` / `postgres`), `execute_sql`.
- Read-only in layers: DB account, sqlglot validation, read-only transaction rolled back + timeout + row limit, logging of every query. Tests proving a write is refused even when validation is bypassed.
- Payroll privacy rule (O5).
- **Tag `t2sql/v0.2-mcp`.**
- **Server** `calorvia-sources` (`mcp_server.py`, mcp 2.3, D44): 7 tools, all annotated read-only: the 6 above + `get_sales_commission` (D43). Streamable HTTP on 9001 (checked with a real client), or stdio. Tool answers and errors in French, for the model.
- **The four layers** (837 lines in `privacy`, `validation`, `execution`, `cards`, `values`, `commission`, `mcp_server`):
  1. *Account* (step 10): grants only.
  2. *Validation* (`validation.py`): one statement; a `Query` at the top **and** no write node anywhere in the tree (a `DELETE` in a CTE parses as a SELECT); no `SELECT INTO`, `FOR UPDATE`, `SET`, `EXEC`, `COPY`; dangerous functions refused by name (`pg_*`, `lo_*`, `dblink`, `xp_*`, `sp_*`, `OPENROWSET`, `set_config`…); tables and columns resolved against the **readable** schema with readable errors (close names, "this table is in compta: no join between sources", "personal column, not readable", `SELECT *` on `employees`); the payroll rule; a row limit.
  3. *Execution* (`execution.py`): PostgreSQL `BEGIN READ ONLY` + `SET LOCAL statement_timeout` + a client-side cancel; SQL Server `SET LOCK_TIMEOUT`, `SET ROWCOUNT`, the driver's query timeout; always rolled back; ≤ 200 rows + `truncated`.
  4. *Log* (`t2sql_query_log`, D46): written before the query, completed after.
- **Table cards** (`cards.py`, 0.1–0.3 s, cached): description, readable columns with type, comment and 3 examples, keys, row count, code columns (≤ 25 distinct values) with their **PAR_CODE label** found automatically (the code list whose values contain the column's: `FAC_TYPE` → `TYPE_FACT`, "Avoir … montants positifs à déduire"), hidden columns and why, ontology terms (empty until step 12). No examples of salaries or identities.
- **`find_values`** (`values.py`): every distinct value of every readable text column in memory (54 k / 109 k / 12 k, loaded in 1.5–2.6 s), compared without case, accents, punctuation: `Aeris 12` → "Pompe à chaleur Aéris 12", `Distrinergy` → "Distrinergie SA", the ERP VAT `BE0236099757` → accounting's `BE 0236.099.757`, both Kompra records.
- **Tests: 83 new** (261 in all): the privacy rule on a hand-written schema (no DB); 26 statements refused by validation; writes sent **past validation** straight to execution, all refused (incl. `SET TRANSACTION READ WRITE` inside the query); a SQL Server temp table doesn't outlive its call; 2-second timeouts on both engines; no log → no query; a payroll average over sites shown, over one person refused at run time; the commission tool (a non-salesperson refused, an injection-shaped staff number refused); the tools through a real MCP client.
- **Found on the way:** sqlglot regenerates queries differently from what was written (D45); it also *accepts* `SELECT TOP 5 FROM t` (no column), now refused explicitly; pymssql reports a timeout as "not connected", and a `rollback` in `finally` hid it; the commission tool first *cleaned* `10405'; DROP…` into `10405` instead of refusing it.
- **The 12 starter queries pass validation**, except the payroll side of Q12 (one person's commission line), refused as intended: `get_sales_commission` gives 731.38 € on 731 384.61 € at 0.1 %.
- **Known limits** (privacy.py docstring): differencing two filtered aggregates; accounting cost centres of one person; absences (sickness) not covered.

### ✅ Step 12. The ontology (NVIDIA auto-ontology)
- Run it with local models only (structured output, rerank API format), on non-conflicting ports, KumoRFM off.
- SQL Server support (O6): compare at least two options.
- Certify the key terms (revenue, EBITDA, customer, headcount…) with before/after examples; YAML export + note.
- **Tag `t2sql/v0.3-ontologie`.**
- **O6 compared, then settled** (D47): the copy keeps the ERP's 41 foreign keys, Trino passes none; same tables, columns and types otherwise; ingest 2.9 s vs 4.7 s.
- **auto-ontology on local models** (D48): Qwen3.8-27B, bge-m3, bge-reranker; no adapter needed. Five patches, each for a measured failure: vector size (bge-m3 is 1024, not 2048); payroll `employees` **silently dropped** (column grants); `SELECT *` profiling and an all-NULL key crash; **queries refused whenever more than one database is connected** (routing on every table seen instead of the ones the query uses); services listening on every interface without authentication.
- **Generated:** 51 terms in 29 min, one per table. The model read the French abbreviations as English: salespeople *Vendor* (= supplier), purchase order lines *Access Control List*, receipt lines *Recovery Link*, fixed assets *Real Estate Asset*, three tables named *Order*.
- **Certified** (`ontology/certification.yaml`): 27 terms renamed and re-described with step 10's traps, 8 metrics (net revenue, units net of returns, booked revenue, EBITDA, net result, depreciation, headcount, telework days).
- **Starter questions answered by auto-ontology:** as shipped 0/12 (routing bug), generated 4/12, certified 7/12, with two more definitions 8/12 (±2 run to run at temperature 0). Every gain is a definition column names can't give (credit notes positive, the 693000 entry, EBITDA's ranges, "amortissements" = amount). Misses left are about reading the question (Q2 "achetées", Q10 per month).
- **Export** (`ontology/export/`, Ossie: ontology, mapping, semantic model): its sample values would have published employee names, work e-mails, staff numbers and IBANs; `export_ontology.py` scrubs payroll, salespeople and IBAN/e-mail/address columns and fails on any leak. It caught three leaks while it was written, one in my own certification text (a real staff number as an example).
- **Choices and results:** `ontology/NOTE.md`.

### ✅ Step 13. The agent and the OpenAI-compatible endpoint
- Agent (O4) using the ontology and the MCP server: pick sources, write dialect-correct SQL, self-correct with a bounded retry, cross-source reconciliation in Python, show its queries, refuse or ask when ambiguous.
- `GET /v1/models`, `POST /v1/chat/completions` (streaming if possible).
- **Tag `t2sql/v0.4-agent`.**
- **Graph** (LangGraph, D50; `agent.py`): `agent` (Qwen3.8-27B on 8000, native tool calling, temperature 0) ⇄ `tools` (the 7 MCP tools through the SDK's own client, D51, plus `reconcile`) → `check` (grounding, D54) → `finish` (footer, D53); `wrap_up` when the budget is spent (24 tool calls, 4 failed queries). The ontology is knowledge (D49): the certified table index and the 8 metrics with their reference SQL in the prompt (`prompts/agent.txt`), the certified term of each table in its card (`ontology.py`).
- **Cross-source** (`reconcile.py`): one query per source, then matching in Python on a key normalized by type (VAT, staff number, name); the model names result ids, rows never pass through it (D52). On "ERP vs VEN journal per client, May 2026": 224 clients against 219, 21 with a difference, all explained by the invoices still `EMISE` (352 505,79 €), as step 10 found by hand.
- **Endpoint** (`api.py`, D55): FastAPI on 9000; checked with the `openai` SDK, streaming and not, and with follow-ups ("et pour avril ?", "détaille par site").
- **Behaviour seen by hand:** the ambiguous "CA de mai" answered with the natural reading (invoiced) and the other offered; "supprime les factures de test" refused (read only); an individual salary refused with the rule and the allowed alternatives (aggregates, `get_sales_commission`).
- **Found on the way:** `langchain-mcp-adapters` incompatible with `mcp` 2.x; the context overflow on cross-source questions (D52); the **invented follow-up figure** (D54) and the model copying its earlier footers and notes, now removed by code; the first grounding check counting its own retry message (which quotes the number) as evidence, caught by a test.
- **Starter questions through the agent** (`scripts/ask_agent.py`, same check as step 12, plus a stricter "in the prose" score): **11/12**, in the rows and in the prose (auto-ontology: 8/12). 10–39 s per question, 1–3 queries. The miss, Q2, is a reading of the question: "Distrinergie a acheté" read as Calorvia buying from Distrinergie, 0 units after 24 tool calls, the right reading offered as a clarifying question. Training score: the ontology was certified from these questions; no rule was added for Q2.
- **Tests: 30 new** (303 in all): the graph's control flow with a scripted model on the real MCP server (footer, preview vs rows kept, both budgets, grounding retry then refusal, copied footer removed, log fields injected), the endpoint (OpenAI SDK, SSE, history cleaning), reconcile, the ontology, the row cap.
- **Known limits:** answers are not streamed token by token (the check needs the whole answer first); the model still does some arithmetic itself (a count of 219 for 203 in the cross-source answer: below the check's 1 000 threshold); one agent for three sources is untested against the alternative (step 14).

### ✅ Step 14. Evaluation
- ≥ 40 questions: simple per source, cross-source, ambiguous, impossible, malicious; expected answer and reference SQL.
- Metrics: accuracy with a tolerance on amounts, valid-SQL rate, execution errors, behaviour on impossible/malicious questions, latency. Experiments logged with git commit; at least *with* vs *without* ontology.
- **The set** (D57, D58): 51 questions, 10 simple ERP, 9 accounting, 9 payroll, 6 cross-source, 5 ambiguous, 5 impossible, 7 malicious (delete, national numbers, an individual salary, a status change, an injection hidden in a real question, an "authorized audit", a `DROP TABLE`). Every reference query is a test: it must give the expected answer (it caught two errors in the set).
- **Code:** `evaluation.py` (set, scores, judge), `prompts/t2sql_judge.txt`, `scripts/run_t2sql_eval.py` (runs, `--rescore`), `scripts/t2sql_report.py`; tables `t2sql_experiments` / `t2sql_results` (commit of the agent and of the scorer); the agent's `use_ontology` switch and the stage of each failed query (validation or database).
- **Results (dev, 33 questions)** — experiments 2 and 4 are the same configuration run twice (noise: 1 question):

  | | with ontology (run 2) | with ontology (run 4) | without ontology (run 3) |
  |---|---:|---:|---:|
  | right | **30/33** | **29/33** | 28/33 |
  | confidently wrong | **1** | **1** | 4 |
  | impossible / malicious | 3/3 · 4/4 | 3/3 · 4/4 | 3/3 · 4/4 |
  | queries refused by validation / execution errors | 1/56 · 0 | 1/67 · 0 | 3/60 · 0 |
  | median time per question (simple ERP) | 12 s | – | 20 s |
  | total time, tool calls per question | 12.9 min, 4.4 | – | 15.4 min, 6.2 |

- **Reading:** the accuracy gap (1–2 questions) is at the noise level; what the ontology changes reliably is **confidently wrong answers (4 → 1)** and effort (−30 % tool calls). Its stable wins are definitions: S06 (EBITDA margin over accounts 70, 9,4 % — without it 9,32 % over all of class 7), P03 (sickness = MAL **and** MAL_MUT). S02 (Distrinergie as a customer) went right once, and once the agent asked instead of answering: not stable. No leak in 66 answers; no query failed in a database (every failure was refused by validation first).
- **Stable failures, for step 15/16 experiments:** A03 (answers "le résultat" with the net result, no alternative offered); X03 ("**Non**, il n'y a pas d'écart" when the two figures are equal: the conclusion contradicts the question); X05 (compares payroll with the meal-voucher account 623200 instead of 623100, 14 queries, 156 s).
- **Fixing the stable failures, one change per run** (each on top of the previous one kept; dev, 33 questions):

  | run | change | right | confidently wrong | time | what the trace shows |
  |---|---|---:|---:|---:|---|
  | 2, 4 | baseline (with ontology) | 30, 29 | 1, 1 | 12.9, 14.6 min | – |
  | 5 | `no_repeat`: an identical query is not run again, counts as a failure | 30 | 2 | 13.8 min | X05 had sent one query 8 times until the budget ran out; now it changes approach (still the wrong account) |
  | 6 | certify `pay_elements`: `gl_account` links payroll to accounting | 27 | 3 | 10.9 min | **X05 right** (52 s instead of 156–172 s); P01 exposes a **validation bug**; S02, S03, A05 change path |
  | 7 | `COUNT(*)` no longer refused on `employees` (MCP server) | 28 | 3 | 10.5 min | **P01 right** (1 query, 17 s); S02, S03, A05 give the **same answers as run 6** |
  | 8 | `yes_no_first`: a closed question starts with Oui/Non answering it as asked | 29 | 2 | 10.5 min | **X03 right** ("Oui", instead of "Non, il n'y a pas d'écart") |
  | 9 | `offer_readings`: name the other readings of a word covering several indicators | 30 (**31** re-scored in step 15) | 1 (**0**) | 11.3 min | **rejected**: A03 and A05 still answer one reading silently; the gain comes from S02/S03 changing path. Re-scored after the S09 scoring fix (step 15), it is the best run of the series: worth re-testing with a second run before step 16 |

- **What these runs teach:** at temperature 0 the agent is nearly deterministic for a given prompt (runs 6 and 7: same answers to 0.2 s on the unchanged questions), but **any change to the prompt reshuffles the borderline questions** (S02, S03, S09, A05: whether a date is quoted, whether another reading is offered). On 33 questions a ±2 change in the total says nothing; a question that flips *for the reason the change targeted*, seen in its trace, does. So a change is kept for its mechanism, not for its total. Final configuration: run 8 (D60). Time per question fell by about 20 % (fewer loops, a shorter path for X05).
- **Still failing:** A03, A05 (an ambiguous word answered with one reading, never flagged; a structural fix would mark in the ontology which business words map to several certified metrics); S02 (reading of "acheté", varies with the path); S03/S09 (a date in the result left out of the prose).
- **Tests: 32 new** (335 in all): the set's reference queries, scoring, verdict rules, the agent's switch and failure stage.

### ✅ Step 15. Bonuses
- Chart tool (image served by the app, Markdown link).
- Memory: conversations in PostgreSQL, follow-up questions, learned preferences.
- **Charts** (`charts.py`, D61): bar, line or pie from a result id; refuses a missing or non-numeric column, more than 60 points, a pie of two series. Checked live: "graphique du CA net facturé par mois, janvier à mai 2026" → 5 figures in the answer and a 30 KB PNG served at the link.
- **Conversations** (`memory.py`, D62): each turn saved with its steps; `GET /v1/conversations?user=…`, `GET /v1/conversations/<id>`. Live: "et pour avril ?" found its conversation again from the marker, read back with its 4 messages.
- **Memory** (D63): `remember` / `forget` tools, `t2sql_memory` per user (`user` field or Open WebUI's `X-OpenWebUI-User-Id`). Live: "retiens : toujours en milliers d'euros" → in a **new** conversation, "13 599,6 k€" and, as a follow-up, "12 099,8 k€".
- **Found on the way:** the grounding check (D54) did not read units: "13 599,6 k€" was flagged and the agent recomputed the figure in SQL (`/ 1000.0`) to pass; the check now scales k€, M€, milliers, millions. And the scorer missed S09's "du 13/11/2025 au 28/11/2025" for "du 13 au 28 novembre" (runs 9, 10): a written date now counts by its day too; every run re-scored.
- **Regression check** (run 10, memory off, dev): **29/33**, as run 8 (29/33): no loss from the new tools and prompt lines. Misses: A03, S02, S03 (known borderline) and P03 (counted MAL only, offered MAL_MUT: no certified definition of sickness days, so the reading drifts with the prompt).
- **Tests: 21 new** (356 in all): charts, the memory tables (a throwaway user, deleted after), the agent with charts and memory (scripted model), memory off, conversations and markers in the endpoint, chart serving by id only, a failed save not costing the answer, k€ grounding, the date-day scoring.

### ✅ Step 16. Delivery
- `RAPPORT.md`, README, `results/`. **Tag `t2sql/v1.0`.**
- **`offer_readings` re-tested** (run 11, on the step 15 code): 30/33, and A03 passed by the rule's own mechanism. With run 9 (31), that makes 31 and 30 against 29 and 29 without it: kept, reversing D60 (**D64**). Its X05 miss was a different error: IND_TELE's account guessed from the card's value lists, never queried.
- **Test set, run once** (run 12, `experiments/t2sql/final.toml`, commit `f1b1cfd`): **13/18** as scored, **15/18 read by hand**. E04 and X04 are right; the scorer missed them (a count the question doesn't ask for, a number written as a word): it was corrected on dev answers only. The real misses: C02 (`COUNT(*)` after a join: 47 lines for 12 entries), P06 (contracts started instead of `hire_date`: 38 for 30; no certified "hire" term), A02 (one reading of "travaillent", silently). Malicious 3/3, impossible 2/2, no leak, no execution error. Nothing was changed after reading test answers.
- **Delivered:** `RAPPORT_T2SQL.md` (architecture and reasons, ontology, evaluation, experiments table with commits, what worked, what didn't, test vs dev, five failures analysed, the statement's §7 questions, limits); `results/t2sql/` (`experiments.csv`, `by_category.csv`, `answers.csv`: 348 answers, from `scripts/export_t2sql_results.py`); README "Phase B in five steps", its curl checked against the live endpoint.
- **Caught while writing the report:** four claims that drafts got wrong, checked against the data and corrected: the starter questions *are* in the dev set; the cross-source questions are 3/4 in the final run, not 4/4; P03 is not a stable win; the credit-note code is `'A'`, not `'AV'`. X05's failure was first described as the model pairing examples by position; the card shows separate value lists, and the text was rewritten from the trace.
- **Next, if the project went on:** certify "embauche" and mark the business words that map to several metrics (A02, A03); a validation warning on `COUNT(*)` after a one-to-many join (C02); row pairs in the cards of small mapping tables (X05); then a **new** test set, since this one has been read.

### ✅ Step 17. Payroll privacy fix
- **The bug** (found reviewing the delivered code): queries passing both the validation and the group-size check returned individual pay. Whole rows (`row_to_json(p)`, `p::text`, `SELECT p`, `(p).net_amount`); one person picked inside an aggregate (`SUM(CASE WHEN p.employee_id = … THEN p.net_amount END)`, `FILTER`), which returned exactly that person's total; people counted on another table than the salary's (`payslips p JOIN salary_history s ON s.employee_id = …`), which returned exactly their average; names listed by a salary threshold (14 people in the trial).
- **The fix** (`privacy.py`, D65): an allowlist, so that close variants fall with the forms tried. `ts_stat`, `ts_rewrite`, `schema_to_xml`, `database_to_xml` (they run SQL given as text, or dump tables) join the forbidden functions.
- **Checked:** 60 attack queries, 59 refused; the other is a nested comment that really is `SELECT 1`. 17 ordinary payroll questions accepted. All 68 distinct payroll queries that ever succeeded in the query log still pass (40 read salaries). Four attacks refused and the per-site average answered through the live MCP server.
- **No regression** (run 13, dev, commit `b9332f8`): **30/33** as run 11, the same three misses (S02, S03, X05), 39 queries, none refused, no leak. The test set was **not** run again: it has been read (step 16), and every payroll query of its run still passes.
- **Tests: 47 new** (403 in all).
- **Known limits:** comparing two allowed queries still tells something (groups differing by one person; a refusal against an answer); accounting cost centres of one person; sickness absences. A group whose amounts are all 0 is now refused.

---

## Phase C: improvements

What the two reports left open, none of it started. Order: fix the exposure first, then the agent's failures, then measure them once on a **new** test set (the phase B one has been read). One change at a time, as before.

### ✅ Step 18. Network exposure
- **Before:** from this machine's LAN and Tailscale addresses, ports 5432, 5433, 5434, 14330, 6333, 8001 and 8002 all accepted connections. No client other than this machine was connected.
- **Done (D66):** PostgreSQL, Qdrant and the three sources recreated on `127.0.0.1`: their five ports are now closed on both addresses and open on loopback. Same data after the recreate (10 185 invoices, 20 562 entries, 7 298 payslips, 393 documents, 12 runs, 381 answers, 1 319 log rows, 6 collections with 10 210 points). 403 tests pass, 12/12 starter questions. The comment on the ERP port is corrected.
- **Model servers:** the embedder (8001) and reranker (8002) restarted with `--host 127.0.0.1` (the README's commands): closed on both addresses too.
- **Not tested:** a connection from another machine, and the firewall rules (they need root). Binding to loopback does not depend on either. auto-ontology's connection to the recreated databases was not exercised; the chatbots don't use it at run time.
- **Side effect:** Trino (rejected in D47, stopped) reaches the sources through the Docker gateway, so it needs them started without the override.

### ✅ Step 19. A new text-to-SQL test set
- **The set** (D67): 32 questions, none from the step 14 set, each answer checked by a reference query that the tests run. It includes the failure kinds seen so far (counting rows after a join, a business word with another name, an approved budget version, ambiguous words) and attempts against the payroll rule. It has **not** been run on the agent.
- **Sealed:** `load_final_questions` refuses a file that doesn't match its SHA-256; `run_t2sql_eval.py --final` refuses `-q`, a dirty tree and a second run.
- **The rule for steps 20–22:** design from dev failures and the phase B analyses only; never open this file, and no fix may name one of its questions.
- **Limit:** the set was written by the same assistant that will make the fixes, so it is held out from the agent, not from its author. Fixes must therefore stay general, and the step 23 score is weaker evidence than a set written by someone else. Your trainer's reserve questions would be the stronger test.
- **Tests: 23 new** (426 in all).

### ✅ Step 20. Ontology: ambiguous and missing business words
- **Three metrics certified** (11 in all), each checked on the data: operating result (March 2026: 1 181 034,33 € = EBITDA 1 278 366,78 € − class 63), people hired (`hire_date`, January–May 2026: 30), sickness days (`MAL` + `MAL_MUT`, March 2026: 563). Applied to auto-ontology, export regenerated.
- **Five business words** (D68): chiffre d'affaires, résultat, effectif, coût du personnel, meilleurs produits. They come from the certified metrics and the analysed failures (A01–A05).
- **Results (dev, 33 questions):**

  | run | change | right | confidently wrong | time | misses |
  |---|---|---:|---:|---:|---|
  | 13 | reference (after step 17) | 30 | 3 | 10.3 min | S02, S03, X05 |
  | 14 | three metrics | 31 | 2 | 9.9 min | S02, S03 |
  | 16 | business words | 31 | 2 | 9.7 min | S02, S03 |

- **Reading:** the score doesn't prove the fix. X05 passing in run 14 is not a target of the change, and ±1–2 is the noise. The evidence is the mechanism, checked by hand (nothing stored, and these are questions already read): P06 now gives 30 from `hire_date` (38 before); A02 gives 609 under contract and names the paid-people and full-time-equivalent readings (one silent reading before); A03 gives the net result, offers the operating result, and the code adds EBITDA. On run 14's stored dev answers the note fires on A03 only, so it adds no noise to clear questions.
- **Run 15 is void:** it started while `src/rag_calorvia/etl/chunk.py` had an uncommitted edit made outside this work, so it was stopped, flagged dirty and left out. Run 16 is the same commit from a clean checkout.
- **Limit:** one business word (effectif) and the hire definition touch concepts of the sealed set, which their author knew. They were chosen from the metrics and the phase B failures, and no word was added from that set; still, read step 23's ambiguous and hiring results as weaker evidence.
- **Tests: 7 new** (433 in all).

### ✅ Step 21. Better SQL from better checks and cards
- **Join warning** (D69): all 80 foreign keys of the three catalogs are used. Replayed on the 300 distinct queries that had succeeded in the log, it fires on **one**: C02's. Asked again, C02 ran its query, read the warning, rewrote it with `COUNT(DISTINCT e.id_ecriture)` and answered 12 entries (47 before).
- **Rows in the cards** (D70): 11 tables, `pay_elements` among them (`IND_TELE → 623100`).
- **Results (dev, 33 questions):**

  | run | change | right | confidently wrong | queries | time |
  |---|---|---:|---:|---:|---:|
  | 16 | reference (step 20) | 31 | 2 | 40 | 9.7 min |
  | 17 | join warning | 31 | 2 | 40 | 9.7 min |
  | 18 | rows in the cards | 31 | 2 | 35 | 9.4 min |

- **Reading:** no dev answer changes verdict: S02 and S03 still miss, and neither is about joins or mappings. The warning never fired on dev (no query there has the problem), so its evidence is C02 and the replay. The cards shorten X05: 15 tool calls and 69 s become 12 and 46 s, and it stays right. It was already right in run 17, so this shows a shorter path, not a fix proved by the score.
- **Limit:** the sealed set contains counts after a join, by design. The warning was specified from C02 before that set was written, but its author knew those questions when building it.
- **Tests: 20 new** (453 in all).

### ✅ Step 22. Grounding check
- **The check** (`grounding.py`, D71). Replayed on 86 stored answers with queries (runs 11, 12, 16, 18): the first version flagged correct totals of grouped results (15 people, 609 people) and a gap between two dates, so column totals and date gaps became evidence. It then flags **one** case, in two runs: S11's "23 factures", a number no query had produced. The model read it in a table card. It was right, but presented as a result.
- **Results (dev, 33 questions):**

  | run | change | right | confidently wrong | queries | time |
  |---|---|---:|---:|---:|---:|
  | 18 | reference (step 21) | 31 | 2 | 35 | 9.4 min |
  | 19 | small figures | 31 | 2 | 36 | 9.6 min |

- **Reading:** the only change of behaviour is the intended one: S11 is sent back once and runs a fourth query that counts the invoices. No answer ended with a warning, and no verdict moved.
- **Limits:** a number that is in the results but answers something else passes, which is why it could not have caught C02 (47 was a real result) or may not catch a figure taken from the wrong row. Counts are recognised through a list of nouns. With more than 40 numbers in the results, percentages are not checked and sums of two are not accepted. The model still does arithmetic; this step verifies it, it does not move it elsewhere.
- **Tests: 5 new** (458 in all).

### ✅ Step 23. Final measure of phase C
- **Same commit for both runs** (`01106a1`, `experiments/t2sql/phase_c.toml`). Dev regression (run 20): **31/33**, misses S02 and S03. Sealed set, run once (run 21): **29/32** (91 %).

  | category | dev (run 20) | sealed set (run 21) |
  |---|---:|---:|
  | simple ERP | 5/7 | 6/6 |
  | simple accounting | 6/6 | 4/5 |
  | simple payroll | 6/6 | 5/5 |
  | cross-source | 4/4 | 4/4 |
  | ambiguous | 3/3 | 2/4 |
  | impossible | 3/3 | 3/3 |
  | malicious | 4/4 | 5/5 |
  | confidently wrong | 2 | 1 |
  | time, tool calls per question | 9.5 min, 3.3 | 11.6 min, 4.3 |

- **The three misses, read in their traces:**
  - **N08, wrong and confident:** "le compte fournisseurs" read as class 40 (1 109 entries). In this chart 400000 is *Clients* and 440000 *Fournisseurs* (198). The agent never looked at `plan_comptable`. The grounding check passes it: 1 109 is a real result of the wrong query.
  - **N24, one reading:** the stock in units (1 274), neither value nor a question. "Stock" isn't one of the five business words.
  - **N22, borderline:** gives 380 clients and 367 active, so two readings, without naming the third or offering anything. The rule counts it as a miss; read by hand it is defensible, so 29 is the score and 30 the most a generous reading gives.
- **What the fixes did there:** N12 uses `hire_date` (17), N05 counted invoices at once, N23 got the code's note, malicious 5/5 with no leak. N06 shows the check at work: two figures it could not support, 1 202 and 70,9 %, stayed in the answer under a visible warning. Execution errors: 0.
- **A cost to note:** N20 (right) took 19 queries and 104 s, checking VAT numbers one by one to explain a one-client gap. Cross-source questions are the slow ones.
- **How far to trust it.** Not comparable with phase B's 13/18 (15/18 by hand): different questions. The set was written by the author of the fixes, knowing them (step 19), so 91 % is an optimistic estimate; the trainer's reserve questions would be the independent test. The set has now been read: it can't measure anything further.
- **Nothing was changed after reading these answers.**

### ✅ Step 24. Before any real deployment
- **Authentication and verified users** (D72). Checked on the live endpoint: no key and a wrong key get 401, the right key 200; a request claiming `user: someone-else` was saved under the key's name.
- **Old charts:** files named like a chart and older than 30 days (`CHART_MAX_AGE_DAYS`) are deleted when a new chart is drawn. Their old answers lose the image.
- **Payroll** (D73): filtering out one person (`employee_id <> …`) is refused; so is a second query whose rows differ from an earlier one by 1–4 people, in the trial one more day on a hire-date filter. Sickness can be counted over 5 people or more, never listed per person. S09 (an accident at work) still works.
- **Accounting cost centres:** no rule needed today: every cost centre has at least 5 people on every pay run, and a test now checks it.
- **Checked:** of the 90 distinct payroll queries that had succeeded, replayed in order through all the gates, 88 pass. The two refused: a per-code breakdown including sickness, and a count of sick days that differs by a few people from an earlier one. Both are what the rules intend, and the agent can answer without them. The 60 attacks of step 17: same result, 59 refused and the harmless `SELECT 1`.
- **No regression** (run 22, dev, commit `dcf3b82`): **31/33**, same misses (S02, S03), no leak. Its one refused query is a mistyped column in S04, corrected at once. The sealed set was **not** run again: its 29/32 describes the agent before this step.
- **Limits:** a refusal against an answer still says something; the memory of past queries is bounded and lost on restart, so waiting or restarting escapes it; hours worked aren't treated as health data; keys are plain values in `.env`, with no rotation or rate limit; there is no TLS, so anything beyond loopback needs a reverse proxy.
- **Tests: 26 new** (484 in all).

---

## Phase D: role-based access

Design: D74. Requires step 24's API keys (the key gives the user, the user gives the role). None of it is started.

### The roles (D75)

Every role also gets the documents of `employe`. Salaries stay aggregated over at least 5 people for every role, `direction` and `rh` included.

| Role | ERP | Accounting | Payroll | Documents | Rows |
|---|---|---|---|---|---|
| `direction` | all | all | all | every indexed folder | all |
| `finance` | sales and purchase invoices, customers, suppliers, articles, sites | all | pay runs, payslips, pay lines, pay elements, cost centres | `01_Finance`, `00_Direction/CODIR` | all |
| `rh` | salespeople only | none | all | `02_RH`, including `Confidentiel` | all |
| `commercial` | sales orders and invoices, customers, salespeople, articles, prices, shipments | none | none | `05_Commercial`, `04_Qualite/Reclamations` | all |
| `achats` | purchase orders, invoices and receipts, suppliers, articles, stock | none | none | `06_Achats` | all |
| `operations` | production, bills of materials, stock, articles, receipts, shipments | none | none | `03_Production` | all |
| `qualite` | production, receipts, stock movements, articles, suppliers, shipments | none | none | `04_Qualite` | all |
| `responsable_site` (one per site: Gand, Seneffe, Namur, Herstal) | production, stock, receipts, shipments, purchase orders | none | contracts, departments, timesheets (absences as aggregates only) | `03_Production/<site>` where it exists, `03_Production/Procedures` | own site |
| `it` | none | none | none | `07_IT` | – |
| `employe` (default) | none | none | none | `09_Communication`, `10_RSE`, `02_RH/Politiques`, `02_RH/Notes_de_service`, `02_RH/Formation`, `02_RH/Organigrammes` | – |

Left to `direction` alone: `08_Juridique` and `00_Direction`, apart from the CODIR minutes that `finance` also reads. `02_RH/Confidentiel` is shared by `direction` and `rh` only. The annual reviews stay out of the index for everyone (D12).

### ✅ Step 25. Policy file and role logins
- **Policy** in `policy/roles.yaml`; `scripts/apply_roles.py` creates one read-only login per role and source (idempotent, `--dry-run`), the only code using the admin accounts. A login never gets more than `agent_ro`: `*` and column grants are copied from its privileges, so the hidden payroll columns stay hidden. Label tables (`PAR_CODE`, `SOC_SITE`) go to every role reading the ERP.
- **The path of a role:** `USER_ROLES` gives the user's role (nobody listed: `employe`, which reads no database); the endpoint signs a 15-minute token; the agent passes it to the MCP server beside the tool's arguments, hidden from the model; the query runs under that role's login. With `API_KEYS` set, a call without a valid token is refused. Passwords and the signing key are derived from `AGENT_RO_PASSWORD`.
- **Site managers are refused for now:** their logins exist, but they would see every site until step 27.
- **Checked directly on the databases, past validation:** every active role against every table of each source, allowed and forbidden; writes refused; hidden columns refused.
- **Checked live with two roles.** Two bugs appeared that the unit tests had missed: `Agent.ask` didn't accept the token (the tests used a fake agent), and **`commercial`, refused the accounting query, read "12 écritures" in a table card**. Cards, table lists, source lists and value search now follow the role, ahead of step 26. It now answers that the information isn't available, and `finance` still gets 12.
- **No regression** (run 23, dev, local mode, no role): **31/33**, same misses (S02, S03). The evaluation doesn't exercise the roles: that is step 29.
- **Limits, for step 26:** the prompt still lists every table and metric, validation errors can name other tables, and refusals confirm that a source exists. **Don't assign roles to real users before step 29.** `get_sales_commission` needs both the ERP's salespeople and payroll, so it works for `direction` and `rh`, not `finance`.
- **Tests: 56 new** (540 in all).

### ✅ Step 26. Everything the model sees, per role
- **Validation** works on the role's tables only: a forbidden table reads like one that doesn't exist, close-name hints come from the role's tables, and a source it can't read gets the same message as an invented one.
- **Prompt and tools:** table index and metrics limited to the role (a metric needs every table it uses); sentences naming other sources rewritten; `reconcile` removed with fewer than two sources, `get_sales_commission` without both the ERP and payroll. Without a role the prompt is unchanged.
- **Cards** no longer show foreign keys to tables the role can't read. **Other readings** (D68) offer only what the role can compute. **The query log** records user and role.
- **Checked live** with three identities. `commercial` gets the ERP revenue with no mention of accounting, and answers that it doesn't have the draft entries; a user with no role is told no data is available; `finance` still sees both readings. The first live run still named other sources, from the fixed prompt sentences: these were then rewritten.
- **No regression** (run 24, dev, local mode, commit `a393c2a`): **31/33**, same misses (S02, S03).
- **Limits:** the description of a source lists all its subjects (`commercial` can read that the ERP covers purchases), and certified definitions or column comments of a table it can read may name another. Site roles stay refused until step 27, where cards and value search must also follow rows.
- **Tests: 13 new** (553 in all).

### ✅ Step 27. Row-level security
- **Applied by `scripts/apply_roles.py`** (idempotent; rerun it after restoring a source). Site codes are mapped in `policy/roles.yaml` (`GENT` in payroll, `GND` in the ERP). The site roles are now active. The catalog queries skip `access_control`, or `agent_ro` would fail on it.
- **What a site role is shown follows its rows:** table lists, card counts, code values, examples and value search are built per site role; the prompt names its site.
- **Checked on the databases:** for each of the four sites, the rows of every limited table equal the same count computed as `agent_ro`; other roles keep every row. A site login can't change role, disable row security, drop a policy, turn `row_security` off, impersonate `dbo` or edit the mapping.
- **Cost:** counting all of `timesheets` under a site login takes about 0.6 s (0.05 s without the limit); filtered queries about 0.04 s.
- **Checked live:** the Gand manager gets 190 people and 242 sickness days for March, and no figure for Seneffe; Herstal gets 6 people. The payroll rules still apply inside a site.
- **No regression** (run 25, dev, commit `ae0b1cd`): **31/33**, same misses (S02, S03).
- **Limits:** other sites remain visible in the label table `SOC_SITE`; individual timesheet rows other than absences stay readable by the manager of that site.
- **Tests: 64 new** (617 in all).

### ✅ Step 28. Documents
- **Index:** `scripts/apply_document_roles.py` wrote `allowed_roles` on all 6 collections, nothing re-embedded; no chunk is left without a value. A new index writes it too. Rerun the script after changing the documents of the policy.
- **Search:** the role is a required condition inside every prefetch (D77). **Workbook SQL:** one store per role. **Images:** `image_bytes` checks the role. **Chat:** with `API_KEYS` set, `app/chat.py` asks for a key, uses that user's role and final configuration; `.streamlit/config.toml` keeps it on 127.0.0.1.
- **Checked:** for all 13 roles and 10 searches, every result is allowed. Live: `rh` finds the E3 minimum in the salary grid, `commercial` answers "Je ne sais pas"; `finance` finds the 2026 revenue budget, `commercial` doesn't; the Gand manager gets nothing from Seneffe's folder.
- **No regression** (run 134, commit `e3a0df7`, retrieval only, no role): recall@5 **0.939**, hit@5 0.959, trap rate 0.353, the same as run 56 on each of the 122 scored questions. The 15 searches compared before and after the payload update are identical.
- **Limits:** a document's path can name a folder the role has no rule for, when it reads the file through a copy. The chat keeps one key per person, with no expiry. Generation was not rescored: only retrieval changed.
- **Tests: 43 new** (669 in all).

### ⬜ Step 29. Closing the gaps and proving it
- Signed, expiring chart links. Marker values planted per role must never reach another role's answers.
- The evaluation run once per role, and the access matrix in the report.

---

## Phase E: RAG experiments

### ⬜ Step 30. RAG experiments (one run each, judged on the targeted types)
- CODIR actions and decisions in PostgreSQL, for `action_tracking`.
- Rerank each chunk against the question in the chunk's language (Q024).
- A glossary for query translation ("chariots élévateurs" → "heftrucks").
- Docling chunks with the SQL tools, to separate the reader's effect from the tools'.
- Markdown table serialization (Q093). A study of ColPali-style search on page images.

---

## Progress log

| Date | Step | What happened |
|---|---|---|
| 2026-11-16 | – | Statements read, roadmap and quiz files created |
| 2026-11-16 | 0 | Branch `rag/step-00-setup`: `enonces/` untracked, package `rag_calorvia` (config, db, logs, git_state, sql), compose on 5432/6333, tests green |
| 2026-11-16 | 1 | Branch `rag/step-01-inventory`: Docling conversion with cache, `documents` registry, `exclusions.toml`, 12 tests green |
| 2026-11-16 | 2 | Same branch: `etl/metadata.py`, 12 new columns in `documents`, 45 new tests |
| 2026-11-16 | – | Merged steps 1–2 into `main`, tagged `rag/v0.1-inventaire`, pushed |
| 2026-11-16 | 3 | Branch `rag/step-03-eval`: dataset split and alignment, metrics with `trap_hit`, ceiling 101/122, 91 tests green |
| 2026-11-16 | 4 | Branch `rag/step-04-baseline`: generator switched to Qwen3.8-27B; pipeline ported; baseline recall@5 0.783 (context line +10 pts); judged by Gemma 4: correctness 0.762 on text questions; faithfulness judge errors found by hand |
| 2026-11-16 | – | Merged, tagged `rag/v0.2-baseline`, pushed |
| 2026-11-16 | 5 | Branch `rag/step-05-languages`: 5a/5b no gain (5b +2.2 s), 5c kept as new reference; reranker identified as the cross-language bottleneck |
| 2026-11-16 | – | Merged, tagged `rag/v0.3-langues`, pushed |
| 2026-11-16 | 6 | Merging the untrack commit into `main` **deleted `enonces/` from disk** (a merge applies removals of tracked files); restored with `git restore --source=<old commit> --worktree`, all 393 registry hashes verified. Then history purged (D31), backups (mirror + copy) kept in the scratchpad |
| 2026-11-16 | 6 | Incident (your browsing, confirmed): a corpus workbook (`Productierapport Gent 2026-02.xlsx`) was rewritten at 15:46 by something outside the session's code, its totals row emptied; restored from Git (hash = registry). Found because `enonces/` was still tracked: the step 0 untrack had failed; fixed |
| 2026-11-16 | 6 | Branch `rag/step-06-excel`: openpyxl reader (v2 after two fixes), SQL tools on workbook tables (Q158 solved), index fingerprint; judged: tools +4.6 pts on the 22 workbook questions; `tools_tables` is the new reference |
| 2026-11-16 | 7 | Branch `rag/step-07-images`: 66 images/pages transcribed in ≈ 6 min, 10 checked by hand (0 wrong value, 9 omissions, 4 inventions), VLM vs OCR, recall@5 0.783 → 0.934; whole images; judged: image/scan correctness 0.035 → 0.825; `vision_whole_images` is the new reference |
| 2026-11-16 | – | Merged, tagged `rag/v0.5-images`, pushed |
| 2026-11-16 | 8 | Branch `rag/step-08-versions`: content dates fixed; status filter (trap rate 0.471 → 0.353); chronological context; time rules; reference-date filter measured and dropped; judged on 41 target questions: `time_rules` kept |
| 2026-11-16 | – | Merged, tagged `rag/v0.6-versions`, pushed |
| 2026-11-16 | 9 | Branch `rag/step-09-final`: final choice reopened and judged on 77 questions; `status_filter` evaluated once on the test set (correctness 0.823); results exported, report written, chat UI |
| 2026-11-17 | – | Merged, tagged `rag/v1.0`, pushed. Phase A done |
| 2026-11-17 | 10 | Branch `t2sql/step-10-sources`: the three sources restored (ERP on 14330), `text2sql_calorvia` package, schemas and notes in `docs/sources/`, 12/12 starter questions in SQL, `agent_ro` tested read-only on each database (temp tables and SQL Server's missing timeout left for step 11) |
| 2026-11-17 | – | Step 10 merged, tagged `t2sql/v0.1-sources`, pushed. O5 settled: aggregates only (D43) |
| 2026-11-17 | 11 | Branch `t2sql/step-11-mcp`: MCP server (7 read-only tools, HTTP on 9001), four protection layers, payroll rule enforced on the SQL, table cards with PAR_CODE labels, accent/typo/format-tolerant value search, 83 new tests |
| 2026-11-17 | – | Step 11 merged, tagged `t2sql/v0.2-mcp`, pushed |
| 2026-11-17 | 12 | Branch `t2sql/step-12-ontology`: O6 compared (copy 41 FKs vs Trino 0), auto-ontology on local models with five patches, 51 terms generated, 27 certified + 8 metrics; starter questions 0 → 4 → 8/12; scrubbed Ossie export |
| 2026-11-17 | – | Step 12 merged, tagged `t2sql/v0.3-ontologie`, pushed. O4 settled: LangGraph (D50) |
| 2026-11-17 | 13 | Branch `t2sql/step-13-agent`: LangGraph agent over the MCP server, reconcile in Python, grounding check after an invented follow-up figure, OpenAI endpoint on 9000 with streamed steps; starter questions 11/12; 30 new tests |
| 2026-11-17 | – | Step 13 merged, tagged `t2sql/v0.4-agent`, pushed |
| 2026-11-17 | 14 | Branch `t2sql/step-14-eval`: 51-question set (33 dev, 18 test), scoring in code + judge with rules, experiments in PostgreSQL; first scores 33/33 found too lenient by hand and re-scored; with ontology 30 and 29/33 vs 28/33 without, confidently wrong 1 vs 4 |
| 2026-11-17 | 14 | Fixes, one change per run (5–9): repeated-query guard, `pay_elements` certified, `COUNT(*)` validation bug fixed in the MCP server, yes/no-first rule kept; offer-readings rule rejected (its targets still failed). Ontology re-exported (28 terms) |
| 2026-11-17 | – | Step 14 merged, tagged `t2sql/v0.5-eval`, pushed |
| 2026-11-17 | 15 | Branch `t2sql/step-15-bonus`: charts served by the endpoint, conversations and per-user memory in PostgreSQL (memory as data, off in evaluations); grounding check reads k€/M€; scorer reads a date's day, all runs re-scored; regression run 29/33 = run 8 |
| 2026-11-18 | – | Step 15 merged, tagged `t2sql/v0.6-bonus`, pushed |
| 2026-11-18 | 16 | Branch `t2sql/step-16-delivery`: `offer_readings` re-tested and kept (D64); test set run once, 13/18 scored, 15/18 by hand; `RAPPORT_T2SQL.md`, `results/t2sql/`, README quick start |
| 2026-11-18 | – | Step 16 merged, tagged `t2sql/v1.0`, pushed. Phase B done |
| 2026-11-18 | 17 | Branch `t2sql/step-17-privacy`: individual pay reachable past the payroll rule (whole rows, CASE/FILTER in aggregates, people counted on the wrong table, names by salary threshold); rule rewritten as an allowlist (D65); 47 new tests; dev regression 30/33 = run 11. Phase C added to this roadmap |
| 2026-11-18 | – | Step 17 merged into `main`, pushed, tagged `t2sql/v1.1`. The tag first went out by mistake on the commit before the merge (`65a21e7`, without the fix); moved to the merge commit `dacdd9f` by a force-push of that tag, at your request |
| 2026-11-18 | 18 | Branch `improve/step-18-network`: databases and Qdrant bound to 127.0.0.1 (D66), data unchanged, README commands updated; vLLM servers still to restart |
| 2026-11-18 | – | Step 18 merged, pushed; embedder and reranker restarted on 127.0.0.1 |
| 2026-11-18 | 19 | Branch `improve/step-19-test-set`: 32-question final test set, sealed by its fingerprint, one run allowed; not run yet |
| 2026-11-18 | – | Step 19 merged, pushed |
| 2026-11-18 | 20 | Branch `improve/step-20-business-words`: 3 metrics certified, 5 business words with their readings written by code (D68); dev 31/33 (runs 14, 16); P06, A02, A03 fixed by their mechanism |
| 2026-11-18 | – | Step 20 merged, pushed |
| 2026-11-18 | 21 | Branch `improve/step-21-sql-checks`: join warning from the foreign keys (D69), rows of small code tables in their cards (D70); dev 31/33 (runs 17, 18); C02 now corrects itself |
| 2026-11-18 | – | Step 21 merged, pushed |
| 2026-11-18 | 22 | Branch `improve/step-22-grounding`: counts and percentages below 1 000 checked against query results (D71); no false alarm in 86 stored answers after two evidence fixes; dev 31/33 (run 19) |
| 2026-11-18 | – | Step 22 merged, pushed |
| 2026-11-18 | 23 | Branch `improve/step-23-final`: dev 31/33, sealed set run once, 29/32 (one confidently wrong: N08) |
| 2026-11-18 | – | Step 23 merged, pushed |
| 2026-11-18 | 24 | Branch `improve/step-24-deployment`: API keys and verified users (D72), chart cleanup, payroll identifiers, sickness rule, overlap between queries (D73); dev 31/33 (run 22) |
| 2026-11-18 | – | Phase D (role-based access, steps 25–29) added, roles proposed for approval; the RAG experiments moved to Phase E (step 30) |
| 2026-11-18 | – | Roles approved (D75). Step 24 merged, pushed |
| 2026-11-18 | 25 | Branch `access/step-25-roles`: policy file, one login per role and source, signed role token through the agent; a card leak found live and closed; dev 31/33 (run 23) |
| 2026-11-18 | – | Step 25 merged, pushed |
| 2026-11-18 | 26 | Branch `access/step-26-role-view`: validation, prompt, tools, cards, readings and query log follow the role; dev 31/33 (run 24) |
| 2026-11-18 | – | Step 26 merged, pushed |
| 2026-11-18 | 27 | Branch `access/step-27-rows`: row-level security for the four site roles (D76), site views of cards and values; dev 31/33 (run 25) |
| 2026-11-18 | – | Step 27 and the RAG search refactor merged, pushed |
| 2026-11-18 | 28 | Branch `access/step-28-documents`: `allowed_roles` on every chunk, role filter in the search, per-role workbook stores, image check, login on the chat (D77) |
