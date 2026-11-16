# Quizzes

One quiz per step of `ROADMAP.md`. Try to answer before opening the collapsed answer.

---

## Warm-up: understanding the problem (before step 0)

Based on the two statements and the dataset presentation.

**1.** Why does the RAG statement insist on "one change at a time" and on storing every experiment with its git commit?

<details><summary>Answer</summary>

So that any difference in scores can be attributed to a single cause. If two things change between runs, you can't tell which one helped or hurt (they may even cancel out). The git commit (plus `git_dirty = false`) makes a run reproducible: you know exactly which code produced the numbers in the report.
</details>

**2.** What is the held-out test set, how is it defined here, and what mistake does it protect you from?

<details><summary>Answer</summary>

The 31 questions whose number is a multiple of 5 (`int(q["id"][1:]) % 5 == 0`). You tune only on the other 127 (the dev set) and evaluate the final configuration on the reserve once. It protects against **overfitting to the eval set**: tuning the system to the questions rather than to the problem. If test scores are much lower than dev scores, that is what happened.
</details>

**3.** Give three reasons a naive RAG would answer "the ERP goes live on April 1st" when the right answer is June 1st (June 15th for Ghent).

<details><summary>Answer</summary>

- **Decisions change over time**: the older CODIR minutes with "1er avril" are still in the corpus and may match the question just as well.
- **Reminders of old values**: newer minutes say "Pour rappel, la mise en production avait été fixée au 1er avril…", so even the right chunk contains the wrong value.
- **Versions**: there are ERP schedules v1, v2, v3; the context can mix them.
Nothing in plain similarity search prefers the most recent document.
</details>

**4.** A question in French asks about forklift speed in the Ghent warehouse; the answer is in a Dutch document. Which half of hybrid search can find it, and why can't the other?

<details><summary>Answer</summary>

**Dense** search, provided the embedder is multilingual (bge-m3 is): it compares meanings, so "vitesse des chariots" and "snelheid van de heftrucks" land close together. **BM25** (lexical) compares words; the French question and the Dutch passage share almost none, so it scores ~0. Fixes explored in step 5: translate the question, per-language stemmers.
</details>

**5.** Docling reads an Excel percentage cell as `-0.00681316572305923`. Why is that a problem for a RAG, and what does Excel show instead?

<details><summary>Answer</summary>

Excel shows the value formatted by the cell's number format: `-0,7 %`. The minutes and the questions talk about "-0,7 %", so neither BM25 nor the LLM connects them to the raw float, and the LLM may misread it. Docling also loses the sheet name and copies merged titles into every column. Step 6 reads workbooks with openpyxl and formats values like Excel does.
</details>

**6.** What does `trap_hit` measure, and is a higher value better or worse?

<details><summary>Answer</summary>

For questions that list `traps` (passages with a wrong or outdated answer: a draft, an old version, a minute corrected later), it is true when at least one retrieved chunk comes from the trap document **and** contains all the trap's snippets. The rate is the share of such questions with a trap in the top k. **Lower is better.**
</details>

**7.** Why must the registry *exclude* files (with an `excluded_reason`) rather than delete them from the corpus?

<details><summary>Answer</summary>

The corpus is the source data; deleting is irreversible and hides the decision. Excluding in the registry keeps the decision explicit, documented and reversible, and you can measure its effect (index with and without). It also matters for privacy reviews: you can show *why* `02_RH/Confidentiel/…` is not indexed.
</details>

**8.** In the text-to-SQL project, the database account is already read-only. Why add sqlglot validation and read-only transactions on top?

<details><summary>Answer</summary>

Defence in depth: each layer has blind spots. `default_transaction_read_only` can be switched off by a simple `SET` in the session; a SQL parser can miss an unusual construct. With several independent layers, a malicious question, a prompt injection hidden in data, or a model mistake has to beat all of them at once. The statement asks for tests proving a write fails even when validation is bypassed.
</details>

---

## Step 0: project setup

**1.** `git rm -r --cached enonces` removed the folder from Git. What happened to the files on disk, and what about the copies already pushed to GitHub?

<details><summary>Answer</summary>

`--cached` only removes them from the **index** (what the next commit contains); the files stay on disk. Once committed, the folder is gone from the new tree, and the `.gitignore` entry stops Git from offering it again. But every past commit (here `a33c2a6`) still contains it, so anyone can check out that commit on the public repo. Removing it for good means rewriting history (`git filter-repo`) and force-pushing: that is open decision O7.
</details>

**2.** The old `.gitignore` already listed `enonces/*`, yet the files were tracked. Why?

<details><summary>Answer</summary>

`.gitignore` only applies to **untracked** files. Files committed before the rule existed, or added with `git add -f`, stay tracked and Git keeps recording their changes. Hence the need for `git rm --cached`.
</details>

**3.** In `git_state.py`, what does `git status --porcelain` return on a clean tree, and why use `--porcelain` rather than plain `git status`?

<details><summary>Answer</summary>

An empty string on a clean tree; otherwise one line per modified, staged or untracked file (`" M a.txt"`, `"?? new.py"`). `--porcelain` is a format guaranteed stable for scripts, independent of the user's language and git version, unlike the human-readable output. So `!= ""` is a reliable "dirty" check.
</details>

**4.** Why does `start_experiment` call `conn.commit()` immediately after the `INSERT`, before the experiment has even run?

<details><summary>Answer</summary>

So the row with status `running` is visible (and stays) even if the run crashes halfway. Without the commit, an exception would roll the insert back and the failed run would leave no trace. `finish_experiment` later sets `done` or `failed` and the duration.
</details>

**5.** `Settings` declares `postgres_url: str` with no default, but `qdrant_url` has one. What happens if `.env` lacks `POSTGRES_URL`? And what does `extra="ignore"` do?

<details><summary>Answer</summary>

pydantic-settings raises a `ValidationError` as soon as `settings = Settings()` runs (on import of `config.py`): a required field is missing. You fail fast instead of discovering it at the first query. `extra="ignore"` lets `.env` contain keys the class doesn't declare (`DB_USER`, `DB_PASSWORD`, `DB_NAME`, which only docker-compose reads) without an error.
</details>

**6.** `db.load_sql` uses `importlib.resources.files("rag_calorvia")` instead of a path like `Path("src/rag_calorvia/sql")`. Why?

<details><summary>Answer</summary>

`files()` finds the folder inside the **installed package**, wherever the program is started from and however it is installed. A relative `Path` only works if the current directory is the repo root.
</details>

**7.** Why does `test_git_state.py` build a throwaway repository in `tmp_path` instead of calling `git_state()` on the real repo?

<details><summary>Answer</summary>

The real repo's state changes all the time (it's dirty while we work, clean after a commit), so a test on it can't assert a known result. A temporary repo gives a controlled state: clean after one commit, then deliberately modified or given an untracked file. The test becomes deterministic and isolated.
</details>

**8.** `test_db.py` skips when PostgreSQL is down. What kind of test is it, and why delete the experiment in a `finally` block?

<details><summary>Answer</summary>

An **integration test**: it exercises our code together with a real external service (PostgreSQL), unlike the unit tests on `git_state`. The `finally` removes the test row even if an assertion fails, so test runs don't pollute the `experiments` table that the report will read. A rollback wouldn't do it, since `start_experiment` commits on its own.
</details>

**9.** Why pin `qdrant/qdrant:v1.19.1` instead of `latest`?

<details><summary>Answer</summary>

Reproducibility. `latest` changes when a new image is published: a `docker compose pull` months later could bring a version whose API or storage format differs, and experiments would no longer be comparable or might break. A pinned tag gives everyone the same server.
</details>

**10.** In `pyproject.toml`, what does `module-name = ["rag_calorvia"]` under `[tool.uv.build-backend]` do, and why was it needed?

<details><summary>Answer</summary>

It tells the uv build backend which package(s) under `src/` to build and install. By default it expects a package named after the project (`labo`, i.e. `src/labo/`), which we removed. As a list, it lets one project ship several packages: `text2sql_calorvia` will be added to it in phase B.
</details>

---

## Step 1: inventory

**1.** No two files of the corpus have the same SHA-256, yet `99_Archives/Doublons/Copie de Tarif 2026.xlsx` is a copy of `05_Commercial/Tarifs/Tarif 2026.xlsx`. What differs between their bytes?

<details><summary>Answer</summary>

An XLSX (like a DOCX or PPTX) is a **zip archive** of XML files. The sheets are identical, but `docProps/core.xml` stores the created/modified dates and author, and the zip headers store each member's timestamp. One different byte changes the whole SHA-256. PDFs do the same with their `CreationDate` and `/ID`. That is why we added `content_hash`, computed on the text.
</details>

**2.** What does `normalize_text` keep, and why does that make the DOCX and PDF of the telework policy v3 hash the same?

<details><summary>Answer</summary>

It applies NFKC normalization, lower-cases with `casefold()`, then removes everything that is not a letter or a digit (`re.sub(r"[\W_]+", "", text)`): spaces, line breaks, punctuation, underscores. The DOCX and the PDF differ in **layout** (line breaks, spacing, bullets as Docling renders them), not in their words and numbers. Once layout is gone, the two strings are equal.
</details>

**3.** What would go wrong if `describe()` hashed the normalized text even when it is empty?

<details><summary>Answer</summary>

Every image and every scan has empty text, so they would all share `sha256(b"")`: 54 images + 9 scans would form one big "duplicate" group, and all but one would be excluded. That's why the code falls back to the file's `sha256` when there's no text. A test of this would need real files, so it isn't covered by the unit tests: worth remembering.
</details>

**4.** Why is a scanned PDF not marked `empty`, while a DOCX with no text is?

<details><summary>Answer</summary>

`is_empty` requires `has_text_layer is not False`. A scan has no text layer (`False`), so its emptiness only means Docling couldn't read it without OCR: its content is in the image and the VLM will read it in step 7. A DOCX has no "image" side: no text means nothing to index. Images (`jpg`, `png`) aren't Docling formats at all, so they're never `empty` either.
</details>

**5.** In `apply_exclusions`, duplicates are grouped only among documents with no `excluded_reason` yet. Give a case where grouping *all* documents would be wrong.

<details><summary>Answer</summary>

If a blank template (excluded as `template`) had the same content as a file in the archives, grouping everything could pick the template as the kept copy (it's outside `99_Archives/`) and mark the archive file as its duplicate: both would end up excluded and the content lost. Grouping only the survivors guarantees that each group keeps exactly one indexed copy. `test_excluded_file_never_becomes_the_kept_copy` checks it.
</details>

**6.** Read `canonical_rank`. Which copy is kept for (a) the ERP grid in the CODIR annexes vs in `06_Achats`, (b) the telework v3 DOCX vs PDF, (c) a file vs its copy in `Doublons/`? Why does the key end with `document.path`?

<details><summary>Answer</summary>

The tuple compares element by element, and `False < True`:
- (a) Neither is archived nor PDF; the `06_Achats` path is shorter, so it is kept.
- (b) `format == "pdf"` is `True` for the PDF, so the DOCX wins.
- (c) The `99_Archives/` copy has `True` as first element, so it loses.

The final `document.path` breaks ties between paths of equal length, so the result never depends on the order the files were read: the inventory is **deterministic**.
</details>

**7.** Why is personal data excluded with a rule on one file rather than on the `02_RH/Confidentiel/` folder?

<details><summary>Answer</summary>

Because the folder holds two different things: `Entretiens annuels 2025 - synthese.xlsx` names employees with their evaluation and raise (personal data), while `Grille salariale 2026.xlsx` only gives salary ranges per job class (no person). The grid is legitimately useful (an eval question needs it). A folder rule would be simpler but would throw away valid information: the decision should follow the content, and the note in `exclusions.toml` records why.
</details>

**8.** `upsert_document.sql` uses `INSERT … ON CONFLICT (path) DO UPDATE`, and `save_documents` then runs `DELETE … WHERE path <> ALL(%s)`. What property do these two give the inventory?

<details><summary>Answer</summary>

**Idempotence**, and a registry that mirrors the corpus. Running the inventory twice gives the same table: the second run updates the existing rows instead of failing on the primary key or creating duplicates. The `DELETE` removes rows for files that have disappeared from the corpus, so the table never describes files that no longer exist.
</details>

**9.** In `convert.py`, why is the conversion written to a `.tmp` file and then renamed with `tmp.replace(target)`?

<details><summary>Answer</summary>

`convert_documents` skips any document whose JSON already exists. If the program crashed halfway through writing, a truncated JSON would exist and would be skipped forever, then fail to load later. Writing to a temporary file and renaming is **atomic** on the same filesystem: the target is either absent or complete, never half-written.
</details>

**10.** Why are conversions stored as `data/conversions/<relative path>.json` instead of `data/conversions/<file name>.json` as in hospital_rag?

<details><summary>Answer</summary>

Two files of the Calorvia corpus can have the same name in different folders (the statement warns about it, and the eval uses relative paths as ids for that reason). With file names only, the second conversion would overwrite the first. Mirroring the tree keeps one JSON per file, and the relative path stays the single id used everywhere (registry, payloads, eval).
</details>

---

## Step 2: metadata

**1.** `document_date` tries three sources in a fixed order. Which, and why is a bare year in the file name last?

<details><summary>Answer</summary>

1. `filename_date`: precise patterns in the name (photo, day, compact day, DD-MM-YYYY, quarter, month, year range).
2. `content_date`: the first date in the first 600 characters of the text (only the title line for workbooks).
3. `filename_year`: a year alone in the name.

A bare year is the weakest signal. It is often part of a code (`NC-2025-047`, `REC-2026-017`, `CAPEX-2025-014`) rather than the date of the document, and even when it is meant as a date (`Tarif 2026`) it's only a year. The content usually says more (`Date d'ouverture 02/12/2025`).
</details>

**2.** Why does the month pattern end with `(?![\d-])`? Give two names it must not match.

<details><summary>Answer</summary>

It's a negative lookahead: after `YYYY-MM`, the next character must not be a digit or a dash. It matters for **codes**: `TM-2025-0391` contains `2025-03` (a valid month: March 2025) followed by `9`, and `NC-2025-047` contains `2025-04` followed by `7`. Without the lookahead they would be dated March and April 2025. Year ranges like `2025-2026` are already rejected by the month check `0[1-9]|1[0-2]` (the "month" would be `20`); the lookahead is a second safety for them.

The `(?<!\d)` lookbehind at the start does the same job on the left side.
</details>

**3.** A photo is named `IMG_20260311_Presse_plieuse.jpg`. Why is its `date_source` `photo` and not `filename`?

<details><summary>Answer</summary>

The date is when the picture was taken, not the date of what it shows (a nameplate shows the machine's year of manufacture, for instance). The statement lists this trap ("la date du nom de fichier ne veut pas toujours dire la même chose"). Keeping the meaning in `date_source` lets later steps decide, e.g. not to use photo dates in a "decision valid at date X" filter.
</details>

**4.** Why store both `doc_date` and `date_end`, and what is `date_end` for `Reporting 2026-03.xlsx` and `Commentaires de gestion T4 2025.pdf`?

<details><summary>Answer</summary>

A document can cover a period rather than a day. `date_end` is the last day covered: 2026-03-31 for the March report (computed with `calendar.monthrange`), 2025-12-31 for Q4 2025. In step 8 a question "in December 2025" will filter on dates; with only the start date, a Q4 report (starting 1 October) and a 31 December minute couldn't be told apart from what they cover.
</details>

**5.** In `content_date`, the text contains `Publiée le 04/05/2026. Prise de fonction le 1er juin 2026.` Which date wins, and how does the code decide between a numeric and a written date?

<details><summary>Answer</summary>

04/05/2026. The code runs both searches (`numeric` and `written`), keeps each match with its **position** (`m.start()`), and returns the one that appears first (`min(..., key=position)`). The date of a document is in its heading, so the earliest is the best guess.
</details>

**6.** Why does `make_date` wrap `date(...)` in a `try/except ValueError`?

<details><summary>Answer</summary>

Regexes check the *shape* (`\d\d/\d\d/\d{4}`), not validity: `31/02/2026` or a month `13` match. `date()` raises `ValueError` on them; catching it turns an impossible date into `None` so the next source is tried, instead of crashing the inventory. `test_invalid_dates_are_ignored` checks it.
</details>

**7.** Why does `(?<![A-Za-z])[vV](\d+)\b` find the version in `PV_CODIR_2025-11-17_v2.docx` when `\b[vV](\d+)\b` didn't?

<details><summary>Answer</summary>

`\b` is a boundary between a word character (`[A-Za-z0-9_]`) and a non-word character. The underscore is a **word** character, so there is no boundary between `_` and `v`. The lookbehind `(?<![A-Za-z])` only requires that `v` is not preceded by a letter (so `Rev2` or `nov2` don't match), and accepts `_`, space or `-`.
</details>

**8.** `99_Archives/Doublons/Budget 2026 v2 FINAL.xlsx`: what are its `version`, `markers` and `status`? Why isn't "final" a status?

<details><summary>Answer</summary>

`version = "v2"`, `markers = ["duplicate_folder", "archive", "final_in_name"]`, `status = "copy"`. "FINAL" is a **claim** made by whoever named the file, and here it is false: the file holds version 2, not the approved budget. A status must reflect facts we trust (the folder says it's a duplicate). The marker is kept so we can analyse this trap, but it never makes a document authoritative.
</details>

**9.** The order of `DOC_TYPES` matters. Give two pairs of rules whose order would change a result if swapped.

<details><summary>Answer</summary>

- `codir_annex` before `codir_minutes`: `CODIR/Annexes/…` files sit under `CODIR/`, and the annex rule must catch them first.
- `contract` before `price_list`: `Avenant tarifaire Distrinergie` contains "tarif" but is a contract amendment.
- `photo` before `strategy`: `Strategie/Photo tableau SWOT…` is a photo of a whiteboard.
- `workbook` last: it's a fallback for any `.xlsx`/`.csv` that no specific rule matched.
</details>

**10.** Why does `content_date` read only the first line of a workbook, and what went wrong before?

<details><summary>Answer</summary>

In a workbook, the first line is the title and the following lines are **data**. `Liste numeros de serie concernes.xlsx` was dated 2025-11-03, which is the production date of the first unit in the list, not the date of the list. The title line still gives a correct date when there is one (`Tarif 2026 · en vigueur au 01/01/2026`).
</details>

**11.** `detect_language` loads the py3langid model lazily, in a module-level `_identifier`. What does that buy, and why `set_languages(["fr", "nl", "en", "de"])`?

<details><summary>Answer</summary>

Lazy loading: importing `metadata.py` (e.g. in the unit tests, which never call it) doesn't pay the model's loading time; it's loaded once, on the first call, then reused. `set_languages` restricts the classifier to the languages that can occur in a Belgian company's documents. Out of ~97 languages, short or number-heavy texts are otherwise often classified as some unrelated language; with 4 candidates the probabilities are renormalized among plausible answers.
</details>

**12.** The schema changed (12 new columns), and we ran `DROP TABLE documents` instead of writing `ALTER TABLE … ADD COLUMN`. When is that acceptable, and when would it not be?

<details><summary>Answer</summary>

Acceptable because the registry is **derived data**: `scripts/inventory.py` rebuilds it entirely from the corpus in seconds, so nothing is lost. It would not be acceptable for data that can't be recreated, like the `experiments`, `answers` and `scores` tables (runs take time, and old runs reflect old code). Those need a migration (`ALTER TABLE … ADD COLUMN IF NOT EXISTS …`) that keeps existing rows.
</details>

---

## Step 3: evaluation adapted to Calorvia

**1.** `load_questions("test")` raises `PermissionError` unless `allow_test=True`. Why enforce this in code rather than just remembering not to look?

<details><summary>Answer</summary>

Because a single accidental look ruins the test set for good: once you've seen scores (or answers) on the 31 held-out questions, every later choice is influenced by them, and the final test score no longer estimates performance on unseen questions. A rule in code makes the mistake impossible by default and makes the exception visible (`allow_test=True` in a diff is easy to spot in review).
</details>

**2.** In `metrics.py`, what do `hit@k`, `mrr@k`, `recall@k` and `ndcg@k` each answer? Which one cares about grade-1 evidence?

<details><summary>Answer</summary>

- `hit@k`: is there at least one grade-2 chunk (one that contains the answer) in the top k?
- `mrr@k`: 1 / rank of the first grade-2 chunk: is the best chunk near the top?
- `recall@k`: share of the needed **facts** (distinct `fact` numbers of grade-2 items) found in the top k. Interchangeable sources of one fact count once.
- `ndcg@k`: overall ranking quality with graded gains (grade / log2(rank + 1)), divided by the ideal ranking.

Only nDCG gives credit to grade-1 ("useful context") items.
</details>

**3.** Why must `judge_chunk` check the chunk's document and not only that the snippets are in its text? Use a Calorvia example.

<details><summary>Answer</summary>

Because the same words appear in documents that don't prove the answer. A CODIR minute of February 2026 says "Pour rappel, la mise en production avait été fixée au 1er avril": the snippet "1er avril" is in it, but that minute isn't the evidence for "the go-live was set to April 1st in December"; and a newsletter repeating a decision isn't the decision. Requiring the document keeps the ground truth tied to the source the eval designers checked.
</details>

**4.** What does `trap_hit@k` measure, and why does `test_trap_needs_its_document` matter?

<details><summary>Answer</summary>

For a question with `traps`, `trap_hit@k = 1` when a chunk of the top k comes from a trap document **and** contains all its snippets: a wrong or outdated answer reached the LLM's context. Averaged over the questions with traps, lower is better. The test shows that the *new* minute recalling the old value ("Pour rappel… 1er avril") isn't counted as a trap: only the outdated document itself is. Otherwise we'd penalize retrieving the right document.
</details>

**5.** `normalize_numbers("4 568")` gives `"4568"` and `"41,5"` gives `"41.5"`. Why apply it to **both** the chunk and the snippet? And why did it change nothing on the ceiling yet?

<details><summary>Answer</summary>

The comparison is `normalize(snippet) in normalize(chunk_text)`: if only one side were normalized, `4568` (snippet) would never be found in `4 568` (chunk), or the reverse. Normalizing both sides makes the comparison independent of the number rendering. It changed nothing yet because the snippets were written from Docling's rendering and our text **is** Docling's. It will matter in step 6, when our own Excel reader displays numbers as Excel does (`4 568`, `41,5 %`).
</details>

**6.** In the regex `(?<=\d)[   ](?=\d{3}\b)`, what are ` ` and ` `, and why does `du 13 au 28 novembre` stay unchanged?

<details><summary>Answer</summary>

` ` is a no-break space and ` ` a narrow no-break space: Word and Excel use them as French thousands separators. The space is removed only when it has a digit before it (lookbehind) and **exactly three digits then a word boundary** after it (lookahead). In "13 au 28" the space follows "13" but is followed by "au", not three digits, so nothing changes.
</details>

**7.** `align_with_registry` rewrites the eval's paths before scoring. What two problems does it fix, and why fix the questions rather than the metrics?

<details><summary>Answer</summary>

1. **File-name convention:** the corpus writes `_` for `'` (`Test d_etancheite Aeris.pdf`), the eval set kept the apostrophe: 2 evidence paths pointed to files that don't exist.
2. **Duplicates:** we index one copy of each duplicate group; evidence citing the excluded copy is redirected to the kept one (identical text, so the snippet check still holds). Items that become identical are merged, otherwise nDCG's ideal ranking would count the same item twice.

Fixing the data once, at load time, keeps `metrics.py` simple and identical to exercise 3's (well-tested) logic: every metric automatically benefits, and the fix is visible in one place.
</details>

**8.** What is the "ceiling" computed by `scripts/check_eval.py`, and why is it worth computing before building any search?

<details><summary>Answer</summary>

For each dev question, whether every needed fact has an evidence item whose snippets are all present in the **whole** converted text of its document: the best any chunking and search could do with the text we have. It separates problems: a question unreachable here fails because of conversion or missing vision, never because of search. On the dev set: 101/122 reachable; all the unreachable ones need vision (images, scans, a chart inside a PDF). It also caught a data bug (the apostrophes) that would otherwise have looked like a retrieval failure.
</details>

**9.** The judge sample takes "the first 2 ids of each type", sorted. Why not a random sample?

<details><summary>Answer</summary>

Every experiment must be judged on **the same questions**, otherwise differences between experiments mix the effect of the change with the effect of different questions. A fixed rule (sorted ids, first two per type) is deterministic and reproducible without storing a seed. Covering every type (31 questions) ensures each kind of difficulty is represented, even rare ones like `image_in_document`.
</details>

**10.** Why does `chunk_body` strip the first line only if it starts with `[` and ends with `]`, and what would happen to the redundancy metric without it?

<details><summary>Answer</summary>

The context line added to every chunk (`[PV du CODIR du 13 octobre 2025 · …]`) is shared by all chunks of a document. Without stripping it, two unrelated chunks of the same minute would share its shingles and look partly redundant. Checking both brackets avoids stripping a real first line that merely starts with `[` (a citation like `[1] …`).
</details>

**11.** A test failed with `0.16 == 0.1` after porting the redundancy test from exercise 3. What was wrong, and what does it tell you about the change in `redundancy_scores`?

<details><summary>Answer</summary>

The test's filler chunks (`texte 0 a b c`, `texte 1 a b c`…) share the shingle `a b c`: Jaccard 1/5 = 0.2 for each of their 3 pairs, so the mean became (1 + 3 × 0.2) / 10 = 0.16. In exercise 3 those chunks had different *scopes* (different notices), so their similarity was forced to 0. We removed the per-patient scope (every pair is compared now), and the test's assumptions had to change with it: the code was right, the fixture wasn't.
</details>

---

## Step 4: baseline

**1.** Write the context line of the chunks of `03_Production/Gent/Maandrapporten/Productierapport Gent 2026-02.xlsx`. Which fields of the registry does `context_line()` use?

<details><summary>Answer</summary>

`[Rapport de production de février 2026 · Productierapport Gent 2026-02 · 03_Production/Gent/Maandrapporten]`. It uses `doc_label`, the date fields (`doc_date`, `date_end`, `date_precision`, `date_source`, through `french_date()`), and the path (split into folder and file name without extension). A month-precision date becomes "de février 2026".
</details>

**2.** Removing the context line dropped recall@5 from 0.783 to 0.684, and `multilingual` from 0.93 to 0.43. Why does a *French* context line help find *Dutch* documents?

<details><summary>Answer</summary>

The French question shares almost no words with a Dutch chunk, so BM25 can't find it and only dense search helps. The context line adds French words to the Dutch chunk (`Rapport de production`, `Comité de sécurité`) and the folder (`03_Production/Gent/…`), which the question often names ("à Gand", "production"). The reranker also sees them. It's a cheap form of translation of the chunk's *topic*.
</details>

**3.** `meeting_detail` went from 1.000 to 0.550 without the context line. What kind of question is it, and why does it depend so much on the line?

<details><summary>Answer</summary>

Questions about one precise meeting ("Qui présidait le CODIR du 13 octobre 2025 ?", "Quel indicateur … lors de la séance du …"). Many minutes have nearly identical chunks (attendance, indicators, "Néant."); only the date distinguishes them. Without the context line, a chunk from the middle of a minute doesn't say which meeting it belongs to, so neither search nor the reranker can pick the right one.
</details>

**4.** Why does the context line keep the file name even though the label already says "PV du conseil d'administration du 18 novembre 2025"?

<details><summary>Answer</summary>

The file name carries status information the label doesn't: `Projet PV CA 2025-11-18` (a draft), `signé`, `v1`, `FINAL`, `Tarif 2026 - projet v1`. It gives the lexical search those words and lets the LLM see that a chunk comes from a draft. It's also the most precise identifier for documents with a generic label ("Classeur").
</details>

**5.** Why was the "drop repeated texts" idea (exercise 3's header removal made generic) abandoned before any experiment?

<details><summary>Answer</summary>

Looking at the data first: the texts repeated in 5+ documents weren't footers (Docling already leaves page headers and footers out of the chunks) but `Néant.`, the attendees of the Ghent safety committee (9 meetings), the sales-meeting participants, and **a row of the CODIR action table repeated across 5 minutes** while its status didn't change. Dropping them would delete exactly the evidence of `action_tracking` and `meeting_detail` questions. Repetition ≠ lack of information.
</details>

**6.** In `chunk_document()`, why is `reserved = count_tokens(line) + 1` subtracted from `max_tokens` before creating the `HybridChunker`?

<details><summary>Answer</summary>

`HybridChunker` makes chunks of at most N tokens (headings + text), but the context line is added **after** chunking. Without reserving its tokens (+1 for the newline), the final chunk would exceed `max_tokens` (256), and the embedder would see a different size than configured. It's also why the no-context-line index has fewer chunks (1359 vs 1449): with more room per chunk, documents are split less.
</details>

**7.** `collection_name()` builds `calorvia__bge-m3__256` or `calorvia__bge-m3__256__no-context-line`. What would go wrong if a new chunking option weren't added to the name?

<details><summary>Answer</summary>

Two configurations producing different chunks would share one collection. `index_corpus` would find a collection with the "right" name (and, if the chunk count happened to match, consider it complete) and the second experiment would silently search the first one's chunks: its scores would measure the wrong index.
</details>

**8.** In hybrid search, what do the two `Prefetch` and the `RrfQuery(k=60)` do?

<details><summary>Answer</summary>

Each prefetch runs one search independently: dense (cosine on bge-m3 vectors) and sparse (BM25), each returning `candidates` (30) points. RRF (Reciprocal Rank Fusion) then merges the two rankings: each chunk gets Σ 1/(k + rank) over the lists it appears in, and the result is sorted on that score. It only uses ranks, not raw scores, so it doesn't matter that cosine and BM25 scores are on different scales. k = 60 dampens the advantage of the very first ranks.
</details>

**9.** The reranker reorders the 30 candidates and keeps 5. What does a cross-encoder do that the embedder can't?

<details><summary>Answer</summary>

The embedder encodes the question and each chunk **separately** into vectors, then compares them: fast (chunk vectors are computed once, at indexing) but coarse. A cross-encoder reads the question and the chunk **together**, so attention links words of both, and outputs one relevance score. Much more precise, but it must run once per (question, chunk) pair at query time: that's why it only reranks a short candidate list.
</details>

**10.** `run_experiment()` now refuses to start on a dirty tree. What happened that made this guard worth adding, and why isn't it enough on its own?

<details><summary>Answer</summary>

Two reruns were launched right after a commit, and `uv add deepeval` modified `pyproject.toml` seconds later, before the runs started: they were stamped `git_dirty = true` and had to be redone. The guard checks the state **when a run starts**; it can't see files edited *while* the run executes (Python has already loaded the code, but the commit no longer describes everything around it). Hence the rule: don't touch the repository until every run of a batch has started.
</details>

**11.** `find_experiment.sql` now sorts with `ORDER BY git_dirty, started_at DESC`. What does that change for `scripts/report.py baseline`?

<details><summary>Answer</summary>

`false` sorts before `true`, so the most recent **clean** run of that name is returned, even if a dirty trial ran after it. A dirty run is only returned when no clean run of that name exists. The report shows reproducible results by default.
</details>

**12.** For the 2 `out_of_corpus` questions of the judge sample, only `correctness` is judged. Why not `contextual_recall` or `faithfulness`?

<details><summary>Answer</summary>

The expected answer is a refusal ("the corpus doesn't say"). `contextual_recall` asks whether the retrieved chunks contain what the expected answer needs: there's nothing to contain, so the score is meaningless. `faithfulness` checks that every claim of the answer is supported: "Je ne sais pas." has no claim. `correctness` (does the answer match the expected one, i.e. refuse?) is the one question that matters.
</details>

**13.** Why is the judge Gemma 4 rather than Qwen3.8-27B, which judged exercise 3?

<details><summary>Answer</summary>

Qwen3.8-27B is now the generator. A model judging its own outputs tends to prefer them (**self-preference bias**: its own phrasing and reasoning look right to it). A judge from another family (Google's Gemma vs Alibaba's Qwen) removes that bias. The cost: judge scores aren't directly comparable with exercise 3's.
</details>

**14.** Gemma gave faithfulness 0 to Q043's answer "280 k€ [4][5]". The answer was checked by hand and is right. What does this tell you about using an LLM judge, and what should you do with that metric?

<details><summary>Answer</summary>

An LLM judge is itself a model that makes mistakes: here it read the wrong chunk (the capex follow-up says "Budget = 280" but "Statut = En cours") and missed the cited ones. 4 of the 5 claim-based faithfulness penalties of the baseline were such errors. So: **check a sample of the judge's verdicts by hand before trusting a metric**; treat faithfulness as a noisy lower bound, compare experiments only on large differences, and give more weight to metrics that proved reliable (correctness here, and the deterministic recall/hit/trap_hit).
</details>

**15.** Why was "Je ne sais pas." scored 0 on faithfulness, and why is the fix to *skip* the metric rather than score it 1?

<details><summary>Answer</summary>

DeepEval's faithfulness extracts the claims of the answer and checks each against the context; the judge treated "Je ne sais pas" as an unsupported claim. A refusal makes **no** claim, so the question "is every claim supported?" doesn't apply: scoring it 1 would inflate the mean with answers that said nothing, scoring it 0 penalizes honesty. Skipping it keeps the mean about answers that make claims. Whether the refusal was *right* is measured elsewhere: correctness, and the `refusal` metric (right on `out_of_corpus`, wrong otherwise).
</details>
