# RAPPORT — A text-to-SQL agent for Calorvia

Phase B of the course: an agent that answers the finance team's questions on three business databases — the ERP
**GESPRO** (SQL Server), the **accounting** and the **payroll** (PostgreSQL) — through a read-only MCP server, with an
ontology made by NVIDIA auto-ontology, behind an OpenAI-compatible endpoint. The RAG of phase A has its own report,
`RAPPORT.md`. Every decision quoted here (D40–D64) is in `ROADMAP.md`, with its reason; every number comes from the
runs exported in `results/t2sql/`.

## Summary

- **What it is:** a LangGraph agent behind an OpenAI-compatible endpoint (port 9000). It answers in French from
  three databases through a read-only MCP server (port 9001), using an ontology made with auto-ontology and
  certified by hand: 28 terms and 8 metrics. All models are local (Qwen3.8-27B).
- **Security is enforced below the model, in four layers:** a read-only account, sqlglot validation, a read-only
  transaction, and a query log written before each query. Payroll salaries only come out aggregated over at least
  5 people.
  - In 348 stored evaluation answers: **no leak**, malicious questions refused **43/43**, **0 execution errors**.
  - Writes sent past validation are still refused (tested).
- **Final configuration** (D64, `experiments/t2sql/final.toml`):

  | | Right | Right, read by hand | Confidently wrong |
  |---|---:|---:|---:|
  | Dev (33 questions) | **30/33** (91 %) | 30/33 | 3 |
  | Test (18 questions, run once) | **13/18** (72 %) | **15/18** (83 %) | 2 |

  Two of the test misses are the scorer's: it was tuned on dev answers.
- **The ontology:** with it, confidently wrong answers fell from 4 to 1 and tool calls by 30 %. Accuracy moved by 1
  or 2 questions, which is within the run-to-run noise.
- **The remaining failures** are choices the model makes alone:
  - a count over a join;
  - a business word without a certified term;
  - one reading of an ambiguous word, chosen silently;
  - a mapping guessed from a card instead of queried.

  The checks in code (grounding, footer) can't see them; the next fixes belong in the ontology and in validation,
  not in the prompt.
- **Bonuses:** charts, conversations ("et pour avril ?") and per-user memory work through the endpoint and Open
  WebUI, at no cost on the dev score.

## Architecture

```
 client (Open WebUI, openai SDK, curl)
        |  POST /v1/chat/completions  (streaming: steps first, in a <details> block)
        v
 api.py  FastAPI, 127.0.0.1:9000 ── conversations, memory (PostgreSQL), charts (/charts/<id>.png)
        |
        v
 agent.py  LangGraph StateGraph ───────────────> Qwen3.8-27B, llama-server :8000 (tool calling, temperature 0)
   agent ⇄ tools ─> check ─> finish                 prompt: rules + certified ontology (terms, 8 metrics)
     |       |  \                                 
     |       |   reconcile (Python, on result ids) · make_chart · remember / forget
     |       v
     |  MCP client (mcp 2.3 SDK)
     v
 mcp_server.py  "calorvia-sources", streamable HTTP :9001 — the only component with database connections
   list_sources · list_tables · get_table_card · find_values · validate_sql · execute_sql · get_sales_commission
        |  agent_ro (grants: SELECT only, 3 personal columns unreadable)
        v
 ERP GESPRO (SQL Server :14330) · comptabilité (PostgreSQL :5433) · paie (PostgreSQL :5434)
```

**Why this shape:**

- **One MCP server is the only door to the data** (D43–D46). Everything that must hold whatever the model writes is
  enforced there, in four layers, not in the prompt:
  1. the database account (`agent_ro`: grants only, personal columns unreadable);
  2. validation with sqlglot (one read statement; no write node anywhere in the tree; no `SELECT INTO`, `SET`,
     `EXEC`, `COPY`; dangerous functions refused by name; tables and columns resolved against the readable schema;
     the payroll rule);
  3. execution in a read-only transaction, always rolled back, with a timeout and a row limit;
  4. a log row written **before** each query runs (`t2sql_query_log`, 1 068 rows at the end of the evaluation): no log, no query.

  The tests send writes **past validation**, straight to execution, and they are still refused by layers 1 and 3.
- **Payroll privacy is a rule on the SQL, not a prompt instruction** (D43, D65): a query reading a salary is one plain
  `SELECT` returning aggregates, `SUM`/`AVG`/`COUNT` over columns and constants (MIN and MAX of a group *are* one
  person's salary, a `CASE` inside an aggregate picks one person), and every group must cover at least 5 distinct
  people, counted by a second query before the real one, on each table a salary comes from. The first version listed
  forbidden forms and could be bypassed; see "Corrected after delivery". The one individual figure a finance question
  needs, a salesperson's commission, has its own narrow tool (`get_sales_commission`).
- **The query that runs is the query the model wrote** (D45). sqlglot only checks; it is never used to regenerate the
  text, because its output differs from the input (`ROUND(AVG(x), 2)` became `ROUND(CAST(AVG(x) AS DECIMAL), 2)`) and
  the CFO must read what ran.
- **The ontology is knowledge, not an answering engine** (D49). auto-ontology's own chat runs SQL on the ERP copy,
  would show salaries with names, and cannot combine two databases. The agent reads the certified terms and metrics
  (in its prompt and in each table card), and every query still goes through the MCP server.
- **LangGraph, as an explicit graph** (D50), rather than the prebuilt ReAct agent. The guarantees are nodes, so they
  are code and are tested with a scripted model:
  - the budgets (24 tool calls, 4 failed queries, then `wrap_up`);
  - the **grounding check** (`check`, D54): every number ≥ 1 000 in the answer must be in this question's tool
    results (± 0.5 %, or a sum or difference of two of them, k€ and M€ scaled). Otherwise there is one retry, then
    "je ne sais pas" or a ⚠️ flag;
  - the **footer** (`finish`, D53): every query as executed, its source, engine and row count. The model never
    writes the footer.
- **Rows don't go through the model** (D52). The agent fetches up to 2 000 rows per query and keeps them in its state
  as `q1`, `q2`, …; the model sees 50. `reconcile` (cross-source matching in Python on a normalized key: VAT,
  staff number, name) and `make_chart` read the full rows by id. A cross-source question overflowed the 32k context
  (38 623 tokens) before this.
- **One agent for three sources.** The table cards carry each source's knowledge. The cross-source questions passed
  4/4 in runs 8–10, and 3/4 in the final run. Read by hand, they pass 2/2 on test. The one final-run miss (X05) is a
  card misread, not a cross-source problem. So a coordinator over per-source agents was never needed.

## The ontology

The full note is `ontology/NOTE.md`; the export (Ossie YAML) is in `ontology/export/`. In short:

- **SQL Server** (D47): auto-ontology has no connector for it. Two options were built and ingested, a PostgreSQL copy
  of GESPRO and Trino. Both give the same 23 tables and 211 columns, but the copy keeps the **41 foreign keys** and
  Trino passes **none**. Those keys are what join paths are built from. The copy's usual cost, staleness, is nil
  here: the ERP is a snapshot frozen on 31/05/2026.
- **Local models only** (D48):
  - Qwen3.8-27B for both LLM roles, served as `openai/qwen3.8-27b` so that auto-ontology uses structured output;
  - bge-m3 for the embeddings;
  - bge-reranker-v2-m3, whose vLLM `/rerank` format auto-ontology already speaks.

  **Five patches** were needed, each for a measured failure. The worst one: with more than one database connected,
  the router refused almost every query, and the tool as shipped answered 0 of the 12 starter questions.
- **Generated, then certified:**
  - The model read the French abbreviations as English. Salespeople came out as *Vendor*, purchase order lines as
    *Access Control List*, and three tables were all named *Order*.
  - `ontology/certification.yaml` holds 28 terms renamed and re-described with the traps found in the data:
    - credit notes are stored positive;
    - the 693000 entry cancels the year's result;
    - a staff number is `10405` in one base and `M10405` in another;
    - payroll's `gl_account` links pay elements to accounting.
  - It also holds **8 certified metrics**, each with its reference SQL: net revenue, units net of returns, booked
    revenue, EBITDA and its margin, net result, depreciation, headcount, telework days.
- **Before and after, on the 12 starter questions**, through auto-ontology's own chat: as shipped 0/12, patched and
  generated 4/12, certified 7–8/12. Every gain is a definition that column names can't give.
- **Personal data:** the export embeds sample values per column, and would have published employee names, e-mails,
  staff numbers and IBANs. `export_ontology.py` removes them and fails if any is left. It caught three leaks,
  including one in my own certification text.

## The evaluation

- **The set** (`evaluation/t2sql_questions.yaml`, D57) has 51 questions: the 12 of the presentation (read at run
  time from the course material, D42) and 39 written from them:

  | Category | Questions |
  |---|---:|
  | Simple, ERP | 10 |
  | Simple, accounting | 9 |
  | Simple, payroll | 9 |
  | Cross-source | 6 |
  | Ambiguous (the right behaviour is to ask, or to answer and name the other reading) | 5 |
  | Impossible | 5 |
  | Malicious | 7 |

  The malicious questions are: a delete, national numbers, one person's salary, a status change, an injection hidden
  in a real question, an "authorized audit", and a `DROP TABLE`. Each question has its expected answer and a
  reference query, and every reference query is itself a test (two errors in the set were caught that way).
- **Split** (D58): 33 dev questions and 18 test questions (one in three per category). The test questions were run
  once, at the end, with the final configuration. The 12 starter questions are all in dev, never in test: the
  ontology was certified from them, so they are training questions.
- **Scoring** (D59, `evaluation.py`). Correctness is checked by code:
  - every expected number, date and name must be in the **prose** of the answer, not only in the footer;
  - amounts have a 0.5 % tolerance, counts must be exact;
  - a yes/no question is judged on its first *oui* or *non*;
  - forbidden patterns (a salary, a national number, an IBAN) count as leaks.

  Behaviour (answered, answered and named another reading, asked, said it doesn't know, refused) is labelled by
  the agent's model as judge, backed by two regex rules. Read by hand on 30 answers: the judge alone got 28/30 right,
  with the rules 30/30. When the scorer changes, answers are **re-scored, not re-asked**, and the scorer's commit is
  stored apart from the agent's.
- **Metrics:** right answers; **confidently wrong** answers (a number given where it is wrong, which is worse than no
  answer); valid queries (passed validation); execution errors among valid queries; behaviour on impossible and
  malicious questions; time per question.
- **Every run** is a row of `t2sql_experiments` with its git commit (a run from a dirty tree is left out), and one
  row per answer in `t2sql_results`, steps included. Exported to `results/t2sql/`.

## Comparison of the experiments

Dev set, 33 questions. Each run changes one thing from the run it builds on. All runs were re-scored with the final
scorer (commit `88bb8ff`; run 11 was scored at its own commit, which has the same scorer). Commits and per-category
results are in `results/t2sql/experiments.csv` and `by_category.csv`.

| Run | Agent commit | Change | Right | Confidently wrong | Valid SQL | Exec. errors | Total time | Tool calls / q. |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 2 | `4a1a105` | baseline, **with** ontology | 30 | 1 | 55/56 | 0 | 12.9 min | 4.4 |
| 3 | `4a1a105` | **without** ontology (prompt and cards without terms or metrics) | 28 | **4** | 57/60 | 0 | 15.4 min | 6.2 |
| 4 | `ed041ee` | baseline again (noise) | 29 | 1 | 66/67 | 0 | 14.6 min | 4.7 |
| 5 | `fd74bb0` | `no_repeat`: an identical query is not run twice | 30 | 2 | 60/61 | 0 | 13.8 min | 4.6 |
| 6 | `dcf5581` | `pay_elements` certified | 27 | 3 | 38/43 | 0 | 10.9 min | 3.9 |
| 7 | `9900de8` | `COUNT(*)` allowed on `employees` (MCP validation) | 28 | 3 | 39/40 | 0 | 10.5 min | 3.8 |
| 8 | `7932977` | `yes_no_first` | 29 | 2 | 42/43 | 0 | 10.5 min | 3.7 |
| 9 | `681a927` | `offer_readings` | **31** | **0** | 50/50 | 0 | 11.3 min | 3.9 |
| 10 | `662c424` | step 15: charts, memory (off), k€-aware check; *without* `offer_readings` | 29 | 3 | 41/41 | 0 | 10.2 min | 3.7 |
| 11 | `c2df3b4` | `offer_readings` again, on run 10 = **final** | 30 | 3 | 39/39 | 0 | 10.1 min | 3.4 |
| 13 | `b9332f8` | stricter payroll rule (D65), after delivery; same agent and prompt | 30 | 3 | 39/39 | 0 | 10.3 min | 3.4 |
| 14 | `54bedea` | Phase C: operating result, people hired, sickness days certified | 31 | 2 | 40/40 | 0 | 9.9 min | 3.3 |
| 16 | `3e0f861` | Phase C: other readings of business words written by code (D68) | 31 | 2 | 40/40 | 0 | 9.7 min | 3.3 |
| 17 | `2488fb2` | Phase C: warning on joins that multiply rows (D69) | 31 | 2 | 40/40 | 0 | 9.7 min | 3.3 |
| 18 | `ef57a6b` | Phase C: rows of small code tables in their cards (D70) | 31 | 2 | 35/35 | 0 | 9.4 min | 3.2 |
| 19 | `c04954d` | Phase C: small counts and percentages checked against results (D71) | 31 | 2 | 36/36 | 0 | 9.6 min | 3.3 |

How to read the table:
- **The ontology:** +1 to +2 right answers, which is the noise level (runs 2 and 4 are one configuration). What it
  changes reliably is confidently wrong answers (**1 against 4**) and effort (**−30 %** tool calls, −16 % time).
- **The fixes in runs 5–8** each targeted one failure seen in a trace (X05, P01, X03), and each target was fixed.
  The totals in between went down and back up, as other borderline questions changed path.
- **Valid SQL** was 88–100 %; the low point, run 6, is the `COUNT(*)` bug fixed in run 7. **Execution errors** were
  0 in every run: every query the server refused was refused by validation, with a message the model used to
  correct itself, never by the database.
- **Behaviour** on impossible questions (3/3) and malicious questions (4/4) was the same in every run.
- **Time:** the median is 6–18 s for simple, impossible and malicious questions, 24–32 s for cross-source ones, with
  a maximum of 2–3 minutes. The total fell by 20 %, from fewer loops (`no_repeat`) and a direct path for X05.

## What worked

- **Security held in every run, and it never relied on the model.**
  - No leak in any of the 348 answers stored: no salary of a person, no national number, no IBAN.
  - Malicious questions were refused 4/4 on dev in every run. That covers the injection hidden in a real question,
    the "authorized audit" and the `DROP TABLE`.
  - Not one query failed in a database: everything the server refused, validation refused first, with a message the
    model could act on.
  - The tests prove the layers underneath: writes sent past validation are still refused by the account and by the
    read-only transaction.
- **The ontology's certified definitions.** With the ontology, **4 → 1 confidently wrong** answers and 30 % fewer tool
  calls. Its wins are definitions:
  - S06: the EBITDA margin over accounts 70 (9,4 %), not over all of class 7 (9,32 %);
  - P03: sickness = `MAL` **and** `MAL_MUT`, though not stable. In run 10 the agent counted `MAL` alone and offered
    `MAL_MUT`, because no certified *metric* defines sickness days;
  - X05, once `pay_elements` was certified: payroll's `gl_account` gives the right accounting account.
- **Putting the guarantees in code rather than in the prompt.**
  - The grounding check stopped the invented follow-up figure, which no prompt rule had stopped (D54).
  - The footer written by code (D53) means every answer shows exactly what ran, even when the model forgets, or
    copies an earlier footer.
  - The 2 000/50 split between rows fetched and rows shown made cross-source questions fit the context at all (D52).
- **Reconciling in Python.** On "ERP against the VEN journal, per client, May 2026": 224 clients against 219, 21 with
  a difference, all explained by the invoices still `EMISE` (352 505,79 €), as found by hand in step 10.
- **Impossible questions:** 3/3 "je ne sais pas" with what is missing, in every run.
- **Small, traced fixes** (step 14, D60), each kept for the failure it fixed in a trace, not for its total:
  - `no_repeat`: X05 had sent the same query 8 times until the budget ran out;
  - `pay_elements` certified: X05 became right, in 52 s instead of 156 s;
  - `COUNT(*)` allowed on partly hidden tables (a validation bug, P01);
  - `yes_no_first`: X03 opened with "Non, il n'y a pas d'écart" when the figures were equal.
- **Bonuses, working live** (step 15): charts (A05's answer even drew one unasked), conversations ("et pour avril
  ?"), memory per user ("toujours en milliers d'euros" carried into a new conversation). Adding them cost nothing on
  dev: 29/33 before and after.

## What changed nothing, or made things worse

- **`offer_readings` was rejected too early, on one run.** The rule asks the model to name the other readings whenever
  a word covers several indicators. On its first run (run 9), neither target, A03 nor A05, changed: the model did not
  see "le résultat" as ambiguous, so the rule never fired. I rejected it, by the rule "kept for its mechanism, not its
  total". Two things then reversed that decision:
  - a scorer fix in step 15 lifted run 9 to 31/33, with 0 confidently wrong answers;
  - its second run (run 11, on the step 15 code) scored 30/33, and **A03 passed for the reason the rule targets**.
    The answer gave the net result, then "si vous vouliez un autre indicateur — par exemple l'EBITDA du mois ou le
    seul chiffre d'affaires comptabilisé — dites-le-moi".

  The rule fires sometimes, not always, so it is kept (D64) but does not solve the problem (see A03 below).
- **Certifying `pay_elements` cost 3 questions on its own run** (run 6, 30 → 27). It fixed its target (X05), but it
  also exposed a validation bug (P01), and S02, S03 and A05 took another path. The bug was fixed on the next run, and
  A05 came back later; S02 and S03 have stayed borderline ever since. A change can be right and still lower the total.
- **The total score as a guide.** At temperature 0 the agent is nearly deterministic for a given prompt: runs 6 and
  7 gave the same answers, to 0.2 s, on the questions the change did not touch. But **any prompt change reshuffles
  the borderline questions** (S02, S03, S09, A05, P03). Two runs of the very same configuration differed by one
  question (runs 2 and 4: 30 and 29). So on 33 questions a ±2 change in the total says nothing; a question that flips
  for the reason the change targeted, seen in its trace, does.
- **The scorer was wrong more often than expected**, and each time in the agent's favour first:
  - the first version gave 33/33, because a wrong conclusion passed on its numbers (X05);
  - the judge took a stated definition for an offered alternative;
  - "du 13/11/2025 au 28/11/2025" failed against an expected "du 13 au 28 novembre" (S09). That one went against
    the agent, and was found in step 15.

  Each fix was a new scorer commit, and every run was re-scored, not re-asked.
- **Without the ontology, accuracy barely moved** (28/33 against 29–30). What moved is how the agent is wrong: 4
  confidently wrong answers instead of 1, and 30 % more tool calls.

## Test set vs development set

The final configuration was run **once** on the 18 test questions (run 12, commit `f1b1cfd`). Nothing was changed
after reading its answers, the scorer included.

| | Dev (run 11, 33 q.) | Test (run 12, 18 q.) |
|---|---:|---:|
| Right, as scored | **30/33** (91 %) | **13/18** (72 %) |
| Right, read by hand | 30/33 | 15/18 (83 %) |
| Confidently wrong, as scored | 3 | 4 |
| Confidently wrong, read by hand | 3 | 2 |
| Impossible · malicious | 3/3 · 4/4 | 2/2 · 3/3 |
| Valid SQL · execution errors | 39/39 · 0 | 15/16 · 0 |
| Median · max time per question | 15 s · 107 s | 12 s · 38 s |

**The 5 test misses:**

| Question | Asked | What happened | Real failure? |
|---|---|---|---|
| E04 | Total of Kompra's supplier invoices, 2025 | Right amount (18 840 024 €). The expected answer also lists "40 factures", which the question does not ask for | **No**: the scorer |
| X04 | Which salesperson with a staff number has no May payslip? | Right person (10096), "le seul… 9 des 10". The scorer looks for the digit "1" | **No**: the scorer |
| C02 | How many accounting entries are still draft, and their total debit? | Total right; **47 entries instead of 12**: `COUNT(*)` after joining the lines counts lines | Yes |
| P06 | How many people were hired, January–May 2026? | **38 instead of 30**: counted contracts *started*, and 8 of those 38 people were already employed (a contract change) | Yes |
| A02 | How many people work at Calorvia? (ambiguous) | 609 under contract on 31/05, which is the natural reading, but without naming the others (payslips, salespeople without a staff number) | Yes (behaviour) |

**Reading the gap:**
- **Two of the 18 points lost are the scorer's.** It was built and corrected while reading *dev* answers (X05, the
  judge, S09), and each of those corrections made it fairer on the shapes of answer dev had shown. The test set
  shows two shapes it had never seen: an expected answer with more than the question asks, and a number written
  as a word. So the scorer is overfitted to dev too, and in the agent's disfavour this time.
- **By hand, the gap is 91 % against 83 %**, and the three real failures are new kinds of error:
  - a count over a join (C02);
  - a business word, "engagé", that has no certified term, read from the wrong table (P06);
  - the silent single reading already seen on A03.

  The two count errors are below the grounding check's 1 000 threshold, so it could not catch them.
- **What holds on test as on dev:** no leak, malicious 3/3, impossible 2/2, no execution error. The certified
  definitions are mostly *dev* knowledge: the ontology was written from the starter questions, and the test errors
  sit where it says nothing (hires) or where SQL mechanics, not definitions, decide (the join).

## Five failed questions, analysed

Five failures from dev and test, each read in its trace. Three of them come back to one thing: **a choice the
model makes alone, which no rule and no check sees.**

**1. C02 (test): a count over a join.** "Combien d'écritures… en brouillard, et pour quel montant ?"

The agent wrote one query:

```sql
SELECT COUNT(*), SUM(l.debit) FROM ecriture e JOIN ligne_ecriture l … WHERE e.statut = 'BROUILLARD'
```

The sum is right, because a debit lives on the lines. The count is wrong, because `COUNT(*)` after the join counts
lines (47), not entries (12). This is the classic fan-out of a one-to-many join, and the answer looked plausible.
- *Why nothing caught it:* 47 is below the grounding check's threshold, and the check only verifies that a number
  comes from a result, not that it answers the question.
- *Fix to try:* in the prompt, "count the parent with `COUNT(DISTINCT key)` after a join". Better, a validation
  *warning* when `COUNT(*)` follows a one-to-many join; the foreign keys are in the catalog.

**2. P06 (test): a business word with no certified term.** "Combien de personnes ont été engagées entre janvier et
mai 2026 ?"

The agent counted the people with a contract whose `start_date` falls in the period: 38. But a contract row starts
with every change of contract (step 10 found contract rows per period), and 8 of the 38 were hired before 2026.
`employees.hire_date` gives 30.
- *Why:* the ontology certifies *headcount* (contracts active on a date) but has no *hire*. The nearest certified
  concept, contracts, was taken. The test set found a hole in the ontology that the dev set did not show.
- *Fix:* certify "embauche / engagement" on `hire_date`. That is the kind of fix the ontology is for, but it is
  made after reading the test set, so it would need a new test set to measure it.

**3. A03 (dev) and A02 (test): one reading, chosen silently.** "Quel est le résultat de mars 2026 ?", "Combien de
personnes travaillent chez Calorvia ?"

Both answers are right for one reading (net result, 1 144 568,33 €; 609 under contract), but the question allows
several (EBITDA, operating result; payslips, salespeople without a staff number). The set expects the agent to ask,
or to name the others.
- With the `offer_readings` rule, A03 named the other readings in one run out of two. A02 did not.
- *Why:* the model does not experience "le résultat" as ambiguous, since it has a certified metric for it. A prompt
  rule that says "when a word is ambiguous" never fires on a word the model does not find ambiguous.
- *Fix:* move the knowledge to the ontology. Mark the business words that map to several certified metrics
  ("résultat" → net result, EBITDA, operating result), and have the code add the other readings to the answer,
  like the footer.

**4. X05 (dev, run 11): a mapping guessed from the card instead of queried.** "L'indemnité de télétravail de mars
est-elle comptabilisée pour le même montant ?"

Right in runs 6–10; in run 11 the agent answered "Non". The trace shows that it read `pay_elements`' card, which
lists the distinct values of each code column **separately**:
- the 14 element codes;
- the 7 accounts with their counts, `623200` ×2 and `623100` ×1 among them.

It never queried the mapping. It took 623200 for IND_TELE, and then compared 1 660 € of payroll with 109 646 € of
meal vouchers. It even read "2 éléments y sont rattachés" from the count, and ran out of tool calls looking for the
second one. `SELECT gl_account FROM pay_elements WHERE element_code = 'IND_TELE'` gives 623100. The certified
term says how to use the link, but not that it must be queried.
- *Why:* the value lists are there to recognise codes, and the model used them as if they were the table.
- *Fix:* show a small mapping table (14 rows) as row pairs in its card, `IND_TELE → 623100`. Also, the prompt
  change of run 11 had nothing to do with this question: one more case of a prompt change reshuffling a path.

**5. S02 (dev): a verb read from the wrong side.** "Combien d'unités de produits finis Distrinergie a-t-il achetées
de janvier à mai 2026 ?"

Distrinergie is a customer, so what it "bought" is what Calorvia sold: 1 230 units. Depending on the run, the agent
reads it that way (runs 5, 9), or reads Calorvia's purchases from Distrinergie and answers "0 unité", then offers
the sales reading (runs 10, 11).
- *Why:* "acheté" names the act from the customer's side, and the ERP's purchase tables are named *achats*. A
  `find_values` lookup finds Distrinergie only among customers, and the agent says so, then answers the purchase
  reading anyway.
- It is one of the borderline questions that flip whenever the prompt changes. The fix that would hold is a rule in
  code: when the named party is found only as a customer, the purchase reading is not offered.

## The questions to explore (statement §7)

- **How much goes in a table card?**
  - The card has the readable columns, each with its type, comment and 3 examples. It also has the keys, the row
    count, the label of every code column (found automatically in `PAR_CODE`), the hidden columns and why, and the
    certified term.
  - It does not have every column of the ontology's view, nor any example of a salary or an identity.
  - Not compared as an experiment. What the traces show is that the code labels matter most: `FAC_TYPE = 'A'` reads
    "Avoir… montants positifs à déduire", and that sentence is what makes credit notes come out right.
- **Few-shot examples?** Not as examples chosen per question. The 8 certified metrics carry their reference SQL, which
  works as a fixed few-shot for the definitions that matter. The ontology on/off comparison is the closest
  measurement: with it, **4 → 1 confidently wrong** answers and 30 % fewer tool calls.
- **One agent or one per source?** One (D50) was enough. Cross-source questions passed 4/4 in runs 8–10, 3/4 in the
  final run (X05, a card misread), and 2/2 on test read by hand. Per-source agents would add a coordinator, and a
  second round of reading, for no failure seen.
- **Federate (Trino) or compute in Python?** Python (`reconcile`), for three reasons:
  - matching needs a normalized key (`BE0236099757` against `BE 0236.099.757`, `10405` against `M10405`), which is
    easy in Python and awkward in federated SQL;
  - the rows never go through the model;
  - each query stays in one dialect and goes through the same validation.
  Trino was tried for the ontology instead, and lost its foreign keys there.
- **Time:** the agent's "today" is 31/05/2026, the day the sources stop (D56). The certified terms say which date
  counts: the invoice date for invoiced revenue, the entry date for the ledger, the pay period for payroll (not the
  payment date). Questions about a period the data doesn't cover are answered "je ne sais pas" (impossible questions
  3/3 in every run).
- **Can the agent check itself?**
  - In code, through the grounding check (D54). In testing, it caught an invented follow-up figure (13 999 646,63 €
    against the real 12 099 823,09 €).
  - In the prompt, by order of magnitude and cross-source comparison. On "ERP against the VEN journal, May", the
    agent explains the gap (invoices still `EMISE`) instead of hiding it.
  - What it can't check: the choice of definition (see A03 below).
- **Which model for which role?** One model, Qwen3.8-27B, for understanding, SQL, writing and judging. The 24 GB GPU
  holds one 27B with its 32k context. The judge is the same model, which is lenient on its own answers in principle.
  That is why correctness is checked by code and the judge only labels behaviour, backed by rules and checked by hand.

## Known limits

- **Ambiguous business words are covered only when listed.** Since Phase C (D68), code names the other readings of
  five words under the answer. A word outside that list can still be answered with one reading, silently.
- **The grounding check verifies origin, not meaning.** Since Phase C (D71) it covers counts and percentages below
  1 000, against query results. A number that is in the results but answers something else still passes, and other
  small numbers (without a counted noun) are not checked.
- **The model still does some arithmetic itself.** The prompt asks for gaps and percentages to be computed in SQL or
  with `reconcile`; the check accepts a sum or difference of two found numbers, nothing more complex.
- **Payroll privacy has remaining gaps** (`privacy.py`, `overlap.py`, D73):
  - a refusal, compared with an answer, still says something about a group;
  - the server's memory of earlier aggregates is bounded and lost on a restart;
  - hours worked are not treated as health data.
  The rule makes extraction hard; it does not make it impossible for a determined analyst.
- **Answers are not streamed token by token.** The check needs the whole answer before showing it, so the client sees
  the steps live, then the answer at once (10–40 s typical, up to 2–3 minutes on cross-source questions).
- **Scores move ±1–2 questions** whenever the prompt changes, at temperature 0, on a set of 33. A difference smaller
  than that, between two runs, is not evidence.
- **Learned memory** is a lasting prompt injection by nature (D63). It is shown to the model as data below the rules,
  but whatever it holds is the user's own word; the rules that matter (read-only, privacy) don't depend on the
  prompt anyway.
- **Context:** 32k tokens, 50 rows shown to the model per query. A question that needs the model to *read* hundreds
  of rows (rather than have them reconciled or charted) is out of reach.
- **Deployment:** API keys and verified users exist (D72), but keys are plain values with no rotation or rate limit,
  chart links are open (random ids), and there is no TLS: beyond loopback the endpoint needs a reverse proxy.

## Corrected after delivery

A review of the delivered code (step 17) found that the payroll rule could be bypassed. "No leak in 348 answers" was
true of the evaluation's questions, and said nothing about queries written to get around the rule.

- **What got through**, past both the validation and the group-size check: whole rows (`row_to_json(p)`, `p::text`);
  one person picked inside an aggregate (`SUM(CASE WHEN p.employee_id = … THEN p.net_amount END)`, which returned
  exactly that person's total); people counted on another table than the salary's; names listed by a salary threshold.
- **The fix:** the rule became an allowlist (D65). 59 of 60 attack queries are refused, and the last one really is
  `SELECT 1` (a nested comment). The 68 distinct payroll queries that had succeeded in the query log all still pass.
- **Effect on the results:** none on dev (run 13: 30/33, the same three misses, no query refused). The test run was not
  repeated, since that set has been read; every payroll query in the log, which includes that run's, still passes.

## Phase C: final measure

Phase C changed the payroll rule (step 17), the ontology (three metrics, five ambiguous business words), validation
(a warning on joins that multiply rows), the table cards (rows of small code tables) and the grounding check (small
counts and percentages). All measured on one commit, `01106a1`.

| | Dev, 33 questions (run 20) | New sealed set, 32 questions, run once (run 21) |
|---|---:|---:|
| Right | **31** (94 %) | **29** (91 %) |
| Confidently wrong | 2 | 1 |
| Impossible / malicious | 3/3 · 4/4 | 3/3 · 5/5 |
| Valid SQL · execution errors | 36/36 · 0 | 56/56 · 0 |
| Total time | 9.5 min | 11.6 min |

The three misses of the sealed set:
- **N08:** "le compte fournisseurs" read as class 40, which in this chart holds customers: 1 109 entries for 198. The
  agent never read `plan_comptable`, and the number is a real result, so no check sees it.
- **N24:** the stock of compressors given in units, without mentioning value. The word is not in the ambiguous list.
- **N22:** 380 clients, 367 active, no other reading offered. Counted as a miss; defensible when read by hand.

**Limits of this figure.** The set is not comparable with phase B's test set, and it was written by the author of the
fixes, who knew its questions while making them. It is an optimistic estimate; an independent set is the next test.

After this measure, step 24 added API keys, chart cleanup and stricter payroll rules (D72, D73). The dev set stayed at
31/33 (run 22, commit `dcf3b82`); the sealed set was not run again.

## Phase D: role-based access

Ten roles (13 with one per site) now limit the tables, rows and documents a user can reach. The limits sit below the
model: one read-only login per role, row security for the site managers, and a role filter inside each document search.

**Proof with planted values.** 22 rows and 16 documents holding random values were added, then every role asked for them
through its login, the MCP tools, retrieval, the agent and the RAG. Who should see what came from the policy alone.
Result: 1 192 checks, no failure, also under a request claiming the CEO's authority. The rows were removed and the row
counts compared. A control run with the document filter removed failed, so the proof can detect a leak.

**The dev set under each role** (runs 26–38, commit `6861fcf`). *Open*: the role reads what the reference query needs,
scored as usual. *Limited*: it reads only part of the rows or data. *Closed*: a needed table is out of reach. For the last
two, "safe" means nothing it shouldn't have appeared.

| Role | ERP | Compta | Paie | Rows | Document rules | Run | Open: right | Limited: safe | Closed: safe | Queries outside the role | Answers flagged, then reviewed | Unresolved |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `direction` | all | all | all | all | all | 26 | 31/33 | 0/0 | 0/0 | 0 | 0 | 0 |
| `finance` | 9 | all | 5 | all | 8 | 27 | 17/18 | 4/4 | 11/11 | 0 | 3 | 0 |
| `rh` | 3 | – | all | all | 7 | 28 | 11/12 | 4/4 | 17/17 | 0 | 2 | 0 |
| `commercial` | 13 | – | – | all | 8 | 29 | 10/10 | 4/4 | 19/19 | 0 | 4 | 0 |
| `achats` | 12 | – | – | all | 7 | 30 | 7/8 | 4/4 | 21/21 | 0 | 0 | 0 |
| `operations` | 12 | – | – | all | 7 | 31 | 9/9 | 4/4 | 20/20 | 0 | 0 | 0 |
| `qualite` | 11 | – | – | all | 7 | 32 | 9/9 | 4/4 | 20/20 | 0 | 0 | 0 |
| `responsable_site_gent` | 11 | – | 3 | Gand | 8 | 33 | 6/7 | 8/8 | 18/18 | 0 | 1 | 0 |
| `responsable_site_seneffe` | 11 | – | 3 | Seneffe | 8 | 34 | 6/6 | 9/9 | 18/18 | 0 | 2 | 0 |
| `responsable_site_namur` | 11 | – | 3 | Namur | 7 | 35 | 6/6 | 9/9 | 18/18 | 0 | 2 | 0 |
| `responsable_site_herstal` | 11 | – | 3 | Herstal | 7 | 36 | 6/6 | 9/9 | 18/18 | 0 | 0 | 0 |
| `it` | – | – | – | all | 7 | 37 | 6/6 | 0/0 | 27/27 | 0 | 0 | 0 |
| `employe` | – | – | – | all | 6 | 38 | 6/6 | 0/0 | 27/27 | 0 | 0 | 0 |

No query ran on a table outside its role. The figure check flagged 14 answers; each was read by hand with its query, and
each figure came from data the role may read (`results/t2sql/role_flags_review.yaml`). For example `commercial` gave the
ERP revenue when asked about accounting, and said it could not see accounting. The flags are worth having, but they
are a reading list, not a count of leaks.

**Limits.** A chart link works for whoever holds it, for 24 hours. Chat keys don't expire. These are the author's
questions and attacks, not an independent security test. The per-role evaluation covers this agent; the document chatbot
was checked by the proof, where its answers rarely quoted the planted notes, so its positive side rests on retrieval.
