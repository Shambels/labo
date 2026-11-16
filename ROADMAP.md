# Roadmap: Calorvia chatbots

Two chatbots for the fictional company **Calorvia SA**, built one after the other in this repo:

| Phase | Source of knowledge | Statement |
|---|---|---|
| **A. RAG** | 393 documents from a shared drive (DOCX, PDF, scans, XLSX, images, HTML, PPTX…) in French, Dutch and English | `enonces/calorvia_rag/laboratoire_calorvia_enonce.md` |
| **B. Text-to-SQL** | 3 relational databases: the old ERP (SQL Server), accounting and payroll (PostgreSQL) | `enonces/calorvia_t2sql/projet_text2sql_enonce.md` |

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
| D6 | `enonces/` in Git (was O1) | Untracked (`git rm --cached`) and git-ignored. **The step 0 commit failed** (`git commit -- enonces .gitignore` re-added the files from the working tree); really untracked in step 6. The hints notebook stays in `enonces/` rather than being copied to `notebooks/` | The repo is **public** and this is course material with (fake) personal data. It remains in the history of commit `a33c2a6` |
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
| D9 | Porting strategy | Port each hospital_rag module **in the step that needs it** (step 0: config, db, logs; step 3: evaluation; step 4: ETL and RAG) | Nothing unused or untested sits in the repo |

### Open decisions (to settle with you when we reach them)

| # | Question | When |
|---|---|---|
| O7 | Purge `enonces/` from the public history (`git filter-repo` + force push)? Destructive, rewrites `main`. | Whenever you want |
| O3 | Which VLM: candidates in `~/models` are `qwen3.5-9b` (if its `mmproj` is there), `gemma4-12b`, `glm-ocr`, `paddleocr-vl-1.6`. | Step 7 |
| O4 | Agent framework for phase B: LangGraph (Python, testable) or n8n (visual, already installed). | Step 13 |
| O5 | Payroll privacy rule: may the agent show a named person's salary? | Step 11 |
| O6 | How to feed SQL Server to auto-ontology: Trino, a copy into PostgreSQL/DuckDB, or a hand-written YAML description. | Step 12 |

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
- **Result, retrieval** (127 dev questions, commit `24f7201`, runs 13–14):

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

### ⬜ Step 7. Images and scans → `etl/vision.py`
- Serve the VLM (O3); transcribe every image and every scanned PDF page **once**, cached, with timings.
- Read the charts of the two PDFs that have them.
- Image chunks: context line + transcription; payload has the image path and page.
- Check 10 transcriptions by hand; compare VLM vs Docling OCR on `scan_ocr` (quality, time).
- Bonus: show the source image under the answer.
- **Tag `rag/v0.5-images`.**

### ⬜ Step 8. Time and versions
The hardest part. Each idea measured on its own, then combined:
1. Registry status → Qdrant `must_not` filter on drafts, duplicates, noise; `valid_from` / `valid_to` on old versions.
2. Reference date extracted from the question by the LLM; the code applies `date <= reference`.
3. Chunks sent to the LLM in chronological order, each with its date.
4. Prompt rules (latest decision wins, a draft is not authoritative, a corrected minute beats the one it corrects).
5. More candidates for decision-thread questions.
6. CODIR decisions and action-tracking tables extracted to PostgreSQL; `action_tracking` answered in SQL.
- Measure: `decision_*`, `board_resolution`, `version_trap`, `action_tracking`, and **trap rate before/after**.
- **Tag `rag/v0.6-versions`.**

### ⬜ Step 9. Final evaluation and delivery
- Pick the best configuration (quality, latency, indexing cost); run it **once** on the 31 test questions.
- Export results to `results/*.csv`; write `RAPPORT.md` (comparison table with commits, per-type and per-format results, trap rate, VLM time and error rate, what didn't help, three failures analysed) and the README.
- A small chat UI (Streamlit) for the demo.
- **Tag `rag/v1.0`.**

---

## Phase B: the text-to-SQL agent

Deliberately more open than phase A: the steps below are a skeleton we will refine when we get there.

### ⬜ Step 10. Sources
- Restore the three databases with `enonces/calorvia_t2sql/sources_calorvia/docker/` (ports 1433, 5433, 5434); connect with the read-only `agent_ro` account; explore; run the 12 starter questions by hand in SQL.
- **Tag `t2sql/v0.1-sources`.**

### ⬜ Step 11. The MCP server (FastMCP)
- Tools: `list_sources`, `list_tables`, `get_table_card`, `find_values`, `validate_sql` (sqlglot, `tsql` / `postgres`), `execute_sql`.
- Read-only in layers: DB account, sqlglot validation, read-only transaction rolled back + timeout + row limit, logging of every query. Tests proving a write is refused even when validation is bypassed.
- Payroll privacy rule (O5).
- **Tag `t2sql/v0.2-mcp`.**

### ⬜ Step 12. The ontology (NVIDIA auto-ontology)
- Run it with local models only (structured output, rerank API format), on non-conflicting ports, KumoRFM off.
- SQL Server support (O6): compare at least two options.
- Certify the key terms (revenue, EBITDA, customer, headcount…) with before/after examples; YAML export + note.
- **Tag `t2sql/v0.3-ontologie`.**

### ⬜ Step 13. The agent and the OpenAI-compatible endpoint
- Agent (O4) using the ontology and the MCP server: pick sources, write dialect-correct SQL, self-correct with a bounded retry, cross-source reconciliation in Python, show its queries, refuse or ask when ambiguous.
- `GET /v1/models`, `POST /v1/chat/completions` (streaming if possible).
- **Tag `t2sql/v0.4-agent`.**

### ⬜ Step 14. Evaluation
- ≥ 40 questions: simple per source, cross-source, ambiguous, impossible, malicious; expected answer and reference SQL.
- Metrics: accuracy with a tolerance on amounts, valid-SQL rate, execution errors, behaviour on impossible/malicious questions, latency. Experiments logged with git commit; at least *with* vs *without* ontology.

### ⬜ Step 15. Bonuses
- Chart tool (image served by the app, Markdown link).
- Memory: conversations in PostgreSQL, follow-up questions, learned preferences.

### ⬜ Step 16. Delivery
- `RAPPORT.md`, README, `results/`. **Tag `t2sql/v1.0`.**

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
| 2026-11-16 | 6 | Incident: a corpus workbook (`Productierapport Gent 2026-02.xlsx`) was rewritten at 15:46 by something outside the session's code, its totals row emptied; restored from Git (hash = registry). Found because `enonces/` was still tracked: the step 0 untrack had failed; fixed |
| 2026-11-16 | 6 | Branch `rag/step-06-excel`: openpyxl reader (v2 after two fixes), SQL tools on workbook tables (Q158 solved), index fingerprint; judged: tools +4.6 pts on the 22 workbook questions; `tools_tables` is the new reference |
