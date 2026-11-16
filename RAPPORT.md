# RAPPORT — A documentary assistant for Calorvia

A RAG over the shared drive of Calorvia SA (393 files: DOCX, PDF, scans, XLSX, images, HTML, PPTX, CSV; French,
Dutch, English), evaluated on the course's 158-question set: 127 development questions for every experiment,
31 held-out test questions evaluated **once**, at the end. Everything is reproducible from the repository and the
commits listed below; the step-by-step story, with every decision, is in `ROADMAP.md`.

## Summary

| | baseline (step 4) | **final: `status_filter`** | final on the **test** set |
|---|---|---|---|
| recall@5 (deterministic) | 0.783 | **0.939** | 0.850 |
| trap_hit@5 (lower is better) | 0.353 → 0.471 with images | **0.353** | 0.500 (2 of 4) |
| correctness (LLM judge, 31-question sample) | 0.658 | **0.784** | **0.823** (all 31) |
| image and scan questions, correctness | 0.035 (20, before images: run 33) | **0.820** (20) | **0.860** (5) |
| median latency | 2.7 s | 3.0 s | 3.0 s |

- **The final configuration** (`experiments/status_filter.toml`): 256-token chunks with a context line (type, date,
  file, folder); workbooks read with openpyxl (tables, units, Excel formats) and SQL tools on their tables; 66 images,
  scanned pages and PDF charts transcribed once by a VLM, one image = one chunk; hybrid search (bge-m3 dense + BM25,
  RRF k = 60), 30 candidates, bge-reranker-v2-m3, top 5; drafts and archives excluded from the search;
  Qwen3.8-27B (Q4) at temperature 0 with a French prompt that cites its extracts.
- **The largest gains came from reading what was unreadable:** the images and scans (+15 recall points, image
  correctness 0.035 → 0.82), then the context line (+10 recall points), then the SQL tools on the workbooks
  (+4.6 correctness points on the 22 workbook questions).
- **Most retrieval and prompt refinements changed nothing or hurt** (languages, reference dates, chronological
  context, time rules): measured, explained, not kept.
- **Test vs dev:** answer correctness is as good on the held-out questions (0.823 vs 0.784), retrieval is lower
  (0.850 vs 0.939), partly a measurement effect (two right answers found in other documents than the listed
  evidence). No sign of tuning to the dev questions.

## Method

- **Services** (one 24 GB GPU): Qwen3.8-27B Q4_K_XL generator (llama-server, port 8000), bge-m3 embedder and
  bge-reranker-v2-m3 (vLLM, 8001/8002), Qwen3.5-9B + mmproj as VLM for the ETL only, Gemma 4 26B-A4B as judge
  (8003; another model family than the generator, to avoid self-preference). PostgreSQL 17 (registry, experiments),
  Qdrant 1.19.1.
- **Registry** (`documents` table): 393 files, 379 indexed; 14 excluded with a reason (7 duplicates found by
  content hash, 4 noise, 2 templates, 1 personal data); metadata extracted from paths, names and text (type, date
  with precision and source, version, status, language, source type).
- **One change at a time:** every experiment is a TOML file differing from its parent by one key (diffs in
  `ROADMAP.md`); each run is stored with its config, prompt text and **git commit**; the runner refuses
  uncommitted code (`git_dirty = false` for every run below).
- **Deterministic metrics** on every run (dev, 122 questions with evidence): hit, MRR, recall, nDCG at 3/5,
  `trap_hit@k`, redundancy, refusals, answer language, citations; eval paths aligned with the registry
  (duplicates, a file-name convention), numbers normalized (`4 568` = `4568`).
- **LLM judge** (DeepEval: correctness, faithfulness, answer relevancy, contextual precision/recall) on a fixed
  sample of 2 questions per type (31), and on **every** question of the types a change targets (`--types`): with 2
  questions, one wording moves a type's mean by 0.4. Refusals are not judged on faithfulness.
- **The ceiling** (`scripts/check_eval.py`): the share of dev questions whose evidence is in the indexed text at
  all: 101/122 from text, 121/122 with the transcriptions.

## Comparison of the experiments

Retrieval metrics on the 127 dev questions; correctness on the 31-question judge sample (see the next section for
the like-for-like comparison of the final candidates). Commits are those of the rewritten history (`git log`).

| run | experiment | change | commit | recall@5 | MRR@5 | trap_hit@5 | correctness (sample) | median latency |
|---|---|---|---|---|---|---|---|---|
| 13 | `baseline` (retrieval) | exercise 3's best + context line | ff76258 | 0.783 | 0.709 | 0.353 | – | 0.18 s |
| 14 | `no_context_line` | without the context line | ff76258 | 0.684 | 0.582 | 0.412 | – | 0.18 s |
| 15 | `baseline` | generation (Qwen3.8-27B) | ff76258 | 0.783 | 0.709 | 0.353 | 0.658 | 2.68 s |
| 18 | `bm25_per_language` | BM25 stemmer per chunk language | 29d502e | 0.779 | 0.705 | 0.353 | – | 0.18 s |
| 21 | `translate_question` | + question in nl/en, 6 searches, RRF | 9be35da | 0.766 | 0.707 | 0.353 | – | 2.43 s |
| 23 | `prompt_multilingual` | prompt rule for nl/en extracts | 0613df0 | 0.783 | 0.709 | 0.353 | 0.655 | 2.72 s |
| 30 | `excel_openpyxl_v2` | workbooks read with openpyxl | f2bfb82 | 0.783 | 0.714 | 0.412 | 0.648 | 2.61 s |
| 33 | `tools_tables` | + SQL tools on the workbook tables | ed1f788 | 0.783 | 0.718 | 0.412 | 0.687 | 2.90 s |
| 44 | `vision` | + VLM transcriptions (256-token chunks) | ccea8bb | 0.934 | 0.854 | 0.471 | 0.800 | 2.82 s |
| 47 | `vision_whole_images` | one image = one chunk (≤ 1024 tokens) | dde0716 | 0.934 | 0.862 | 0.471 | 0.803 | 3.06 s |
| 53 | `dates_fixed` (retrieval) | content dates fixed (7 documents) | 306f5ef | 0.934 | 0.862 | 0.471 | – | 0.18 s |
| **56** | **`status_filter`** | **drafts and archives out of the search** | **f0f1e20** | **0.939** | **0.871** | **0.353** | **0.784** | **2.97 s** |
| 57 | `chronological` | + extracts sorted by date | f0f1e20 | 0.939 | 0.867 | 0.353 | 0.790 | 2.97 s |
| 58 | `time_rules` | + prompt rule on time and versions | f0f1e20 | 0.939 | 0.871 | 0.353 | 0.781 | 3.10 s |
| 62 | `reference_date` | + date filter from the question's period | e5184b5 | 0.910 | 0.847 | 0.353 | – | 4.10 s |
| **66** | **`status_filter__test`** | **the final config on the 31 test questions** | **4c90d97** | **0.850** | **0.651** | **0.500** | **0.823** (31) | **3.0 s** |

Every run, with its options: `results/experiments.csv`; every metric per run and question type:
`results/summary_by_type.csv`.

### Choosing the final configuration

The last candidates were judged on the same 77 questions (the sample, every image/scan question, every
decision/version question):

| correctness | 47 `vision_whole_images` | **56 `status_filter`** | 57 `chronological` | 58 `time_rules` |
|---|---|---|---|---|
| 31-question sample | 0.803 | 0.784 | 0.790 | 0.781 |
| 20 image/scan questions | 0.825 | 0.820 | 0.765 | 0.690 |
| 41 decision/version questions | 0.785 | 0.768 | 0.780 | 0.790 |
| **77 questions judged in all four** | **0.806** | **0.794** | 0.788 | 0.779 |

47 and 56 are level (one verdict ≈ 0.013); 56 keeps drafts and archives away from the model (trap rate 0.471 →
0.353) without relying on the model to ignore them: chosen. 57 and 58 hurt the image questions (below).

## Results by question type and by document format

The final configuration on the dev set (recall on 122 questions; correctness on every judged question, n in
parentheses: types the step 6–8 changes targeted were judged in full, the others only on the sample), against
the baseline. On all 22 workbook questions, the workbook configuration family scored 0.841 with the SQL tools
(step 6, run 33).

| type | recall@5 baseline → final | correctness final (n) |
|---|---|---|
| action_tracking | 0.955 → 0.955 | 0.727 (11) |
| board_resolution | 0.833 → **1.000** | 0.900 (6) |
| decision_current | 0.786 → 0.857 | 0.643 (14) |
| decision_history | 0.833 → **1.000** | 0.900 (6) |
| decision_reason | 1.000 → 1.000 | 0.600 (2) |
| excel_lookup | 1.000 → 0.923 | 0.600 (2) |
| excel_reasoning | 0.900 → 0.900 | 1.000 (2) |
| factual | 1.000 → 0.938 | 0.850 (2) |
| image_in_document | 0.000 → **1.000** | 1.000 (1) |
| image_only | 0.000 → **0.923** | 0.777 (13) |
| meeting_detail | 1.000 → 1.000 | 0.900 (2) |
| multi_doc | 0.800 → 0.800 | 0.950 (2) |
| multilingual | 0.929 → 0.929 | 0.700 (2) |
| out_of_corpus | – | 1.000 (2) |
| scan_ocr | 0.167 → **1.000** | 0.883 (6) |
| version_trap | 1.000 → 1.000 | 0.925 (4) |

| evidence format | recall@5 baseline → final | correctness final (n) |
|---|---|---|
| docx | 0.947 → 0.947 | 0.765 (26) |
| pdf (text) | 0.921 → 0.921 | 0.750 (6) |
| scan (PDF without text layer) | 0.000 → **1.000** | 0.900 (3) |
| xlsx | 0.962 → 0.962 | 0.800 (3) |
| jpg | 0.000 → **1.000** | 0.914 (7) |
| png | 0.000 → **0.889** | 0.733 (9) |
| html | 1.000 → 1.000 | – |
| mixed (several formats) | 0.887 → 0.919 | 0.790 (21) |

## Traps: before and after step 8

`trap_hit@5` = share of the 17 dev questions with traps (draft, old version, minute corrected later) that have a
trap passage in their top 5.

| | trap_hit@5 | of which `board_resolution` | `version_trap` |
|---|---|---|---|
| baseline (text only) | 0.353 | 1.000 | 0.667 |
| before step 8 (`vision_whole_images`: scans now readable, including the minute with the 1,2 M€ error) | 0.471 | 1.000 | 1.000 |
| **after step 8 (`status_filter`)** | **0.353** | **0.333** | **0.667** |

- **Answers rarely take the trap value**, even with the trap in context: the 27B ignores the draft minutes, the
  draft price list and the old budget versions, and usually states the current value with the old one as
  history (Q043, Q048, Q089, Q153). The remaining case is **Q023**: it always states the 1,2 M€ of the November
  minute first, then its correction to 1 250 000 € (judged correct, but the order is wrong).
- **What the status filter can't catch:** an outdated decision in a signed, final minute (Q063: the 8 km/h of
  November, superseded by 6 km/h in January). Only time-aware generation could, and the two attempts hurt other
  questions (below).

## Reading images and scans

- **66 targets** (54 images, 9 pages of the 8 indexed scans, 3 charts inside 2 PDFs) transcribed once with
  Qwen3.5-9B Q4 + mmproj: **≈ 6 minutes in total**, 5.3 s per image on average, 11–14 s per scanned page; cached
  in `data/vision/` (key = path, page, model, prompt).
- **10 transcriptions checked by hand** against the images (network diagram, SWOT whiteboard, Pareto chart, Herstal
  plan, RSE chart, org chart, nameplate, invoice, handwritten delivery note, Gantt): about 75 numbers and 40 names
  compared. **0 wrong number, 0 wrong name** (1 accent typo). **9 omissions** (the 6 bandwidths drawn along the
  lines of the network diagram, a nameplate's maker and subtitle, a whiteboard footnote) and **4 invented cells**
  (a "Description" column on a plan). The VLM rarely misreads; it skips text that isn't in a block, and its
  free-text descriptions are less reliable than its transcriptions.
- **VLM vs Docling OCR (RapidOCR) on the scans:** both find all 7 dev evidence snippets; the OCR is faster (46 s
  vs 77 s on CPU) but garbled two whole lines of a board minute, one of them the L4 investment resolution. VLM
  kept: one tool for scans, images, handwriting and charts.
- **One image = one chunk:** at 256 tokens, 45 of the 65 images were cut, separating a person from their manager
  in the org charts (Q056); at 1024 tokens, 1. Image/scan correctness 0.765 → 0.825.
- **The chat shows the images** the answer cites (`app/chat.py`), so a value read by the VLM can be checked.

## What changed nothing, or made things worse

| change | effect | why |
|---|---|---|
| exercise 3's header removal, made generic (drop text repeated in ≥ 5 documents) | not run | the repeated texts were CODIR action rows and attendance lists (evidence); Docling already drops page headers/footers |
| BM25 stemmer per chunk language | recall 0.783 → 0.779 | the query is French: a Dutch chunk's stems never meet it |
| question translation (nl/en, RRF) | recall 0.766, **+2.2 s** | the baseline already finds Dutch documents (dense search + French context line); the translation brought a Dutch price chunk into the candidates, but the reranker, comparing it with the French question, ranked it 11th; and "chariots élévateurs" became "reachstackers" |
| prompt rule for nl/en extracts | neutral (kept) | all 127 answers were already in French |
| openpyxl reader alone | correctness 0.795 → 0.764 on 22 workbook questions | one loss ("6 ETP" read as six people); its value is what it enables: typed values for the SQL tools |
| reference date of the question → `doc_date ≤ reference` | recall 0.939 → **0.910**, +1 s | **the date a question is about is not the date its source was written**: the May phishing test is in the July report |
| extracts sorted by date | image correctness 0.820 → 0.765 | the order changed how the question was read: "la première cause de non-conformité" understood as *chronologically* first (Q107) |
| prompt rule "the latest decision wins" | image correctness → 0.690; leaner history answers | mixed two org charts (Q056), one degenerate answer `[3]` (Q014); history answers dropped earlier values |

## Test set vs development set

| | dev (127 / 77 judged) | test (31) |
|---|---|---|
| recall@5 / hit@5 / MRR@5 | 0.939 / 0.959 / 0.871 | 0.850 / 0.867 / 0.651 |
| correctness | 0.784 (sample) / 0.794 (77) | **0.823** |
| faithfulness / answer relevancy | – / – | 0.879 / 1.000 |
| refusals | 6/127 (4 of the 5 out_of_corpus refused, the 5th answered honestly in part) | 2/31 (the 1 out_of_corpus, and 1 wrong: Q020) |
| answers in French | 1.000 | 1.000 |

The answers are **as good on the held-out questions**: the system was not tuned to the dev questions. Retrieval
is lower, with a 30-question denominator (one question ≈ 3 points), and two of its five "misses" are right answers
built from other documents than the evidence: Q095 takes the Aéris 9's 2026 catalogue price (8 750 €) from the
sales quotes, Q125 computes the highest budgeted month with SQL. The three real failures are analysed below.

## Three failures of the final configuration

**Q020 (test, `multi_doc`, correctness 0.0): "Quelle est la capacité nominale du chariot impliqué dans l'accident
de Gand, et de quelle année date-t-il ?"** — answered "Je ne sais pas.".
- *Where:* **retrieval**, on a **chained** question. The incident report (Dutch) says which truck it was (nr. 9,
  Lyftec LE-20); the capacity (2 000 kg) and year are on the photo of truck nr. 9's nameplate. The question names
  neither the truck nor the photo, so no single search can rank the nameplate: the top 5 is the November
  minutes, the audit and a newsletter.
- *Fix:* question decomposition with a second hop (exercise 3's gated decomposition: find "which truck", then
  search "chariot nr. 9 plaque"), or an entity link in the registry (truck number → its photo).

**Q060 (test, `multi_doc`, 0.5): "Lors de la tentative de fraude du 13 janvier 2026, quel IBAN l'attaquant
voulait-il imposer et quel est l'IBAN légitime du fournisseur ?"** — gives the fraudulent IBAN, "les extraits ne
mentionnent pas l'IBAN légitime".
- *Where:* **retrieval**, top 5 crowded by one document: three of the five chunks are the incident report, the
  others the CODIR and the board; the legitimate IBAN is on the two Tôlerie Mosane invoice photos (transcribed
  correctly: `BE47 0689 4412 7380`).
- *Fix:* a cap per document in the top 5 (exercise 3's diversity step), or decomposition into the two facts the
  question asks for.

**Q008 (dev, `decision_current`, 0.2): "Où en est le rappel préventif des pompes à chaleur Aéris 12 ?"** —
describes the start of the recall (214 units, the faulty valve batch), not its end.
- *Where:* **retrieval of the latest state**: the closure on 31 March 2026 (211 repaired, 3 untraceable) is in
  later minutes, but every minute of the thread resembles the question, and the oldest (the most detailed) win.
  The status filter can't help (all are signed minutes), and date ordering hurt other questions.
- *Fix:* for a decision thread, more candidates and a "latest per thread" step (the registry knows the dates), or
  the structured route of the statement: CODIR decisions and actions extracted into PostgreSQL and queried by
  date.

## Limits

- **The judge is fallible:** faithfulness verdicts were checked by hand in step 4 and 4 of 5 penalties were judge
  errors; correctness proved reliable but is read with its reasons. One run per configuration, and llama-server
  is not fully reproducible at temperature 0 (98/127 identical answers between two prompt variants).
- **Small numbers:** 2 questions per type in the sample, 4 to 14 per targeted type; differences under ≈ 0.03 on
  the 77 judged questions are noise.
- **What was not tried:** CODIR actions and decisions in SQL; reranking against the question in the chunk's
  language; a glossary for the translation; Docling chunks + SQL tools (to separate the reader's effect from the
  tools'); ColPali-style search on page images.
- **Time spent:** the ETL (Docling conversion 42 s, VLM ≈ 6 min) is cheap; the judge is the bottleneck (≈ 20 s per
  question), which shaped the evaluation design.
