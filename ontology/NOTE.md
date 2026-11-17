# The Calorvia ontology: choices (step 12)

The ontology of the three sources, built with [NVIDIA auto-ontology](https://github.com/NVIDIA/auto-ontology)
(commit `a630ebd`), on local models only, then corrected and certified by hand.

| File | What it is |
|---|---|
| `export/ontology.yaml`, `export/mapping.yaml`, `export/semantic_model.yaml` | The Apache Ossie export (`scripts/export_ontology.py`), personal sample values removed |
| `certification.yaml` | Every correction and certified metric, with the generated name it replaced (`was:`) |
| `catalog_summary.sql` | What the ingest stored per source (tables, columns, foreign keys) |
| `docker-compose.yaml`, `trino/` | The two ways tried for SQL Server (O6): a PostgreSQL copy and Trino |
| `auto-ontology.override.yaml`, `auto-ontology.env.example`, `ao.sh` | How auto-ontology runs here |
| `patches/` | Five patches to auto-ontology, each explained below |

## 1. SQL Server: a PostgreSQL copy, not Trino (O6, D47)

auto-ontology has no SQL Server connector. Two ideas were built far enough to run its ingest on the ERP:

| Ingest of the ERP | (a) PostgreSQL copy (`scripts/copy_erp.py`) | (b) Trino (SQL Server connector) |
|---|---|---|
| Tables / columns / types | 23 / 211 / equivalent | 23 / 211 / equivalent |
| **Foreign keys** | **41** | **0**: Trino exposes no constraints, auto-ontology's connector says so |
| Ingest time | 2.9 s (+ 2.9 s for the copy, 139 308 rows) | 4.7 s |
| Freshness | frozen at the copy | live |
| Extra pieces | one script, one PostgreSQL | one JVM container, three catalog files |

**Chosen: the copy.** The keys are what auto-ontology builds its join paths from; through Trino it would have to
guess all 41 from the data. The copy's usual cost, staleness, is zero here: the ERP is a final snapshot (extracted
31/05/2026, replaced by Atlas the next day). Table and column names are lower-cased in the copy, which works
unquoted on both engines (SQL Server's collation is case-insensitive), so a term's mapping reads the same on the
real ERP. The copy is read by its own read-only account (`ontology_ro`, same settings as `agent_ro`).

A third idea, describing the ERP by hand in YAML, was not built: it gives up the generation step for the largest
source, which is what the tool is for.

## 2. Local models only

No Calorvia data leaves the machine (statement). Checked in the code: the only outbound paths are KumoRFM (off as
long as `KUMO_RFM_API_KEY` is unset), Databricks (unused) and Next.js telemetry (disabled by its Dockerfile).

| Role | Model | How |
|---|---|---|
| Reasoning and non-reasoning | Qwen3.8-27B (llama-server, port 8000, 32k context) | served as `openai/qwen3.8-27b`: the `openai/` prefix makes auto-ontology use `ChatOpenAI`, whose structured output (json_schema) llama-server supports |
| Embeddings | bge-m3 (vLLM, 8001) | OpenAI `/embeddings`; the extra `input_type` field is accepted |
| Reranking | bge-reranker-v2-m3 (vLLM, 8002) | a URL ending in `/rerank` selects the `{query, documents}` → `results[].relevance_score` format, which is vLLM's: no adapter |

Ports: auto-ontology's own PostgreSQL on 5435 (5432 is the course's), the app on 3000-3002, all on 127.0.0.1.

## 3. Patches to auto-ontology

| Patch | Problem found | Fix |
|---|---|---|
| `embed-dimensions.patch` | Vector size fixed at 2048 (NVIDIA's embedder); bge-m3 gives 1024: every insert would fail | `EMBED_DIMENSIONS` setting |
| `column-grants.patch` | A table read through column grants (payroll `employees`, personal columns revoked) was **silently dropped**: the connector kept only tables with `has_table_privilege` | `has_any_column_privilege` for tables, `has_column_privilege` for columns: the table comes in with its 12 readable columns |
| `profiling.patch` | Profiling sampled tables with `SELECT *`, refused on `employees`; an all-NULL key column (`budget.code_centre`) crashed the probe and skipped the table | Name the catalogued columns; guard the empty result |
| `multi-database-routing.patch` | **With more than one database, almost no question could be answered**: `retrieve` searches every database, so the tables seen during an episode span several, and the router refused to run any query ("no database to run on") | Route on the tables the submitted SQL references |
| `bind-host.patch` | Under host networking (needed: the firewall blocks Docker's bridge from the host's model servers), the backend and ingestion service, which have no authentication, listened on every interface | `BIND_HOST=127.0.0.1` |

## 4. Generation, then certification

Semantic compilation of the three sources: 29 minutes, 51 terms (one per table), with the 27B.

**What the model got wrong** (the French abbreviations read as English words): `vdr_vendeur` (salespeople) named
*Vendor*, i.e. supplier; `ach_cde_lig` (purchase order lines) *Access Control List*; `ach_recep_lig` (goods receipt
lines, `RECUE` = received) *Recovery Link*; `immobilisation` *Real Estate Asset*; `tiers` *Tier*; three different
tables all named *Order*; supplier invoices described as customer invoices.

**Certified** (`certification.yaml`, applied by `scripts/certify_ontology.py`): 27 terms renamed and re-described
with the business rules found in step 10, and 8 metrics as SQL attributes: net invoiced revenue, units sold net of
returns, booked revenue, EBITDA (and its margin), net result, depreciation, headcount on a date, telework days.

### Before and after, on the 12 starter questions

`scripts/ask_ontology.py` asks auto-ontology's chat API each question and checks every number and date of the
expected answer against the rows and the prose (same check as step 10's hand-written SQL). Runs are in
`data/ontology_runs/` (git-ignored: they hold the questions).

| Q | as shipped (multi-database bug) | generated | certified | + 2 definitions |
|---|---|---|---|---|
| 1 net revenue | ✗ | ✗ invoices only, credit notes excluded | ✓ | ✓ |
| 2 units bought by a customer | ✗ | ✗ purchase order lines | ✗ 2 817: every article, not only finished goods | ✗ read "achetées" as Calorvia's purchases |
| 3 lot received / returned | ✗ | ✗ reception line only (0 refused) | ✗ 600 / 386 right, dates missing | ✗ same |
| 4 missing compressors | ✗ | ✓ | ✓ | ✗ shortfall read on the order line after the balance |
| 5 net result 2025 | ✗ | ✗ 7 425 716 | ✓ 5 412 000 | ✓ |
| 6 EBITDA and margin | ✗ | ✗ margin 9.32 % on class 7 | ✓ 9.4 % on accounts 70 | ✓ |
| 7 depreciation 2025 | ✗ | ✗ 239 rows counted | ✗ same | ✓ amount summed |
| 8 headcount per site | ✗ | ✓ | ✓ | ✓ |
| 9 work accident | ✗ | ✓ | ✓ | ✓ |
| 10 telework April and May | ✗ | ✗ one total for both months | ✗ same | ✗ same |
| 11 revenue ERP vs ledger | ✗ | ✗ gave up (two databases) | ✗ gave up | ✓ two exploratory queries, answered in prose |
| 12 commission | ✗ | ✓ | ✓ | ✓ |
| **correct** | **0/12** | **4/12** | **7/12** | **8/12** |
| mean time | 129 s | 50 s | 52 s | 44 s |

- **"As shipped"** is auto-ontology with three databases connected and no routing patch: 11 of 12 questions ran
  out of tool calls (`budget_exhausted`) and gave up; Q8's trajectory shows why, its correct query refused twice
  with "no database to run on". The fix, not the ontology, took it from 0 to 4.
- **Certification took it from 4 to 7-8**, and every gain is a definition the model could not guess from column
  names: credit notes are positive and must be subtracted (Q1), the appropriation entry 693000 cancels the result
  (Q5), EBITDA's account ranges and the margin on accounts 70 (Q6), "les amortissements" means the amount (Q7).
- **Run to run, ±2 questions change** with the same ontology and temperature 0 (Q4 and Q11 between the last two
  runs; Q11 was answered once by two exploratory queries). Read 7 vs 8 as equal.
- **Still wrong, and why:** Q2 is a wording trap (a customer "bought" = our sales, the model sometimes reads our
  purchases); Q3 answers the quantities without the dates; Q10 wants a split per month. These are about reading the
  question, not about the ontology, and are left to the agent's own prompt (step 13).
- The starter questions are also what we certified *from*: 8/12 here is a training score, not an evaluation. The
  agent's evaluation (step 14) uses 40+ other questions.

## 5. How the agent will use it

auto-ontology answers questions itself, but the agent of step 13 will not use its answers: it runs SQL on the
ERP *copy* (not the real ERP), returns individual payroll amounts with names (our privacy rule, D43, would be
bypassed), and cannot combine two databases (Q11). The agent uses the ontology as **knowledge**: terms,
definitions, certified metrics and join paths, read from the export or from auto-ontology's MCP server
(`search_terms`, `get_term`, ...), while every query goes through our MCP server.

## 6. Personal data in the export

auto-ontology's export embeds up to five sample values per column. In a public repository that would publish
employee names, work e-mails, cities and staff numbers (fictional, to be treated as real). `export_ontology.py`
empties the samples of every payroll table, of the ERP's salesperson table, and of any IBAN, e-mail or address
column, then fails if a staff number, work e-mail or IBAN is still in the files.
