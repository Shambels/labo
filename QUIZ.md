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

`--cached` only removes them from the **index** (what the next commit contains); the files stay on disk. Once committed, the folder is gone from the new tree, and the `.gitignore` entry stops Git from offering it again. But every past commit (here `ad75e6c`) still contains it, so anyone can check out that commit on the public repo. Removing it for good means rewriting history (`git filter-repo`) and force-pushing: that is open decision O7.

*Postscript (step 6):* in this repo the untrack actually **failed**, see the next question.
</details>

**1b.** The step 0 commit was `git rm -r --cached enonces` followed by `git commit -m "…" -- enonces .gitignore`. All 7706 files were still tracked afterwards. Why?

<details><summary>Answer</summary>

`git commit <paths>` (the `--only` mode) ignores what is staged for those paths and commits them **as they are in the working tree**. The files still existed on disk, so committing "enonces as in the working tree" put them back: the staged removal was thrown away, only `.gitignore` changed. The right sequence is `git rm -r --cached enonces` then a plain `git commit` (which commits the index). It went unnoticed because `git status` never lists unchanged tracked files; it surfaced in step 6 when a corpus file changed on disk and showed up as modified. Lesson: verify the effect (`git ls-files enonces | wc -l`), not just the command.
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

---

## Step 5: languages

**1.** The notebook says the detected language must choose the stemmer but must **never** be used as a search filter. Why?

<details><summary>Answer</summary>

The questions are always in French, but their answer may be in a Dutch or English document (the `multilingual` questions). A filter `language = fr` would remove exactly those documents from the search. Language is a property of the text, used to process it correctly (stemming, stopwords) and to analyse results, not a criterion of relevance.
</details>

**2.** What does a stemmer do, and why does a Dutch chunk stemmed with the French stemmer index worse?

<details><summary>Answer</summary>

A stemmer reduces words to a common root so that inflected forms match (`entrepôts` and `entrepôt` → same token). It applies rules of one language. The French rules don't know Dutch suffixes (`magazijnen`/`magazijn`, `heftrucks`/`heftruck` stay distinct) and the French stopword list doesn't remove Dutch function words (`de`, `het`, `van`), which then count as terms and distort BM25's IDF. With `[sparse] language = "per_chunk"`, each chunk is tokenized with its own language's rules.
</details>

**3.** 5a (per-language stemmer) changed nothing. Why could it not help *alone*?

<details><summary>Answer</summary>

BM25 compares the **query's** tokens with the chunk's. The query is French, stemmed as French: whatever happens to the Dutch chunk's tokens, they still share almost no word with the French question. A correct Dutch stemming only pays off when a **Dutch query** meets Dutch chunks, which is what 5b adds.
</details>

**4.** In 5b, how many searches does Qdrant run for one question, and how are they combined?

<details><summary>Answer</summary>

Six prefetches: for each version of the question (fr, nl, en), one dense search (its own embedding) and one BM25 search (with the stemmer of its language), each returning 30 candidates. One `RrfQuery` fuses the six rankings: each chunk scores Σ 1/(60 + rank) over the lists it appears in, so a chunk found by several versions rises. Then the reranker keeps 5.
</details>

**5.** On Q024, the translation brought the contract's price chunk from outside the candidates to rank 4, yet recall didn't improve. What happened, and what does it tell you about where the bottleneck is?

<details><summary>Answer</summary>

The reranker scored the 30 candidates against the **French** question, and the Dutch price chunk ("18 400 euro excl. btw per jaar") ended up 11th, out of the top 5. Translation fixed the candidate stage; the cross-encoder, comparing French and Dutch text, is the bottleneck for cross-language passages. A fix to try: rerank each chunk against the version of the question in the chunk's language (one reranker call per language).
</details>

**6.** `translate_question` falls back to `{"fr": question}` on malformed JSON. Why is that the right failure mode?

<details><summary>Answer</summary>

Translation is an **addition**: the original question must always be searched. If an LLM glitch (invalid JSON, a missing key) could stop the search, an optional improvement would become a new way to fail. Degrading to the baseline search (and logging a warning) keeps the worst case equal to the baseline.
</details>

**7.** The translation turned "chariots élévateurs" into "reachstackers" while the Ghent documents say "heftrucks". Why is this a typical problem, and what could reduce it?

<details><summary>Answer</summary>

A general-purpose LLM translates a word in isolation, without knowing the company's vocabulary; "chariot élévateur" has several Dutch equivalents depending on the machine. Ideas: give the translation prompt a short glossary of the corpus's terms (heftruck, magazijn, comité PBW…), extracted from the Dutch documents; or translate the **chunks** at indexing time instead of the questions (the notebook's other idea), so the vocabulary comes from the documents themselves.
</details>

**8.** Why did `--retrieval-only` crash on 5b, and why is "change only what you mean to change" the fix?

<details><summary>Answer</summary>

The script replaced the whole `[generation]` section with `{"enabled": False}`, which also removed `model`. Question translation, a retrieval step, needs the LLM's served name from that section: `KeyError: 'model'`. Setting only `config["generation"]["enabled"] = False` turns generation off and keeps everything else. Overwriting a whole structure to change one field silently deletes the other fields.
</details>

**9.** 98 of 127 answers are identical between `baseline` and `prompt_multilingual`. Can you attribute all 29 differences to the new prompt rule?

<details><summary>Answer</summary>

No. Exercise 3 showed that llama-server isn't reproducible even at temperature 0 (batching and floating-point order change the logits slightly), so part of the differences would appear between two runs of the same config. To attribute a change to the prompt, look at metrics on many questions, ideally against the spread of repeated baseline runs, and at answers that change *in the direction the rule predicts* (Q117: a refusal becoming an honest partial answer).
</details>

**10.** Why does the new `answer_in_french` metric skip answers whose language can't be detected, instead of counting them as French?

<details><summary>Answer</summary>

`detect_language` returns `None` when it can't tell: fewer than 3 words (an answer like "6,3 % [1]." or "BRV-19-04417."), or a probability under 0.9 (numbers and codes carry no language). Such an answer isn't evidence of French or of another language: counting it as French would inflate the metric, counting it as non-French would penalize short exact answers. A metric should average only the cases it can measure, and report n. (Refusals like "Je ne sais pas." have 4 words and are detected as French: they count.)
</details>

**11.** Why must `baseline.toml` never be edited, even to add a new option with its default value?

<details><summary>Answer</summary>

Each run stores its full config, and `check_same_config` refuses a new run under an existing name if the config differs. Adding `[sparse] language = "french"` to `baseline.toml` would make it differ from the stored one, so the baseline could no longer be rerun under its name, and the file would no longer describe what produced the stored results. New options get their default in code (`config.get("sparse", {}).get("language")`), so old configs keep their exact meaning.
</details>

---

## Step 6: Excel files

**1.** Why does `load_workbook(path, data_only=True)` matter, and what would you read without it for a cell `=SUM(B2:B6)`?

<details><summary>Answer</summary>

Without `data_only=True`, openpyxl returns the **formula** text (`=SUM(B2:B6)`). With it, it returns the value the spreadsheet application computed and saved with the file. Caveat from the notebook: a workbook produced by a script and never opened in Excel/LibreOffice may have no saved values: the cell reads `None`. (All the corpus workbooks have their values.)
</details>

**2.** A cell holds `-0.00681316572305923` with the number format `0.0%`. What does `display_value` return, and why do it rather than keep the raw value?

<details><summary>Answer</summary>

`-0,7 %`: the value × 100, with as many decimals as the format has after the point, a comma as decimal separator and a `%`. That is what a reader of the workbook sees, and how minutes and questions write it ("écart de -0,7 %"). The raw float matches neither the words of the question nor what the LLM should quote.
</details>

**3.** How does `sheet_blocks` decide what is a title, a header, a data row and a note?

<details><summary>Answer</summary>

Rows are grouped into blocks separated by empty rows. A row with **one** non-empty cell is a title (before a table; consecutive ones are joined: "Reporting mensuel · mars 2026 · Montants en k€") or a note (after a table's rows). The first row with **several** cells is the header; the following ones are data rows. One-cell lines that never meet a table become a `TextBlock` (a "Commentaires" sheet).
</details>

**4.** What went wrong with `Heures de formation à la sécurité | 620`, and how was it fixed?

<details><summary>Answer</summary>

The line has two cells, so the reader took it for the **header** of a new table; no data row followed, so the table had no rows and was skipped: the information was lost (Docling had at least kept it as text). Fix: a "table" without data rows is a key/value line, turned into text: `Heures de formation à la sécurité : 620`. Found by checking that every eval snippet of a workbook still appeared in some chunk of the new reader.
</details>

**5.** Small tables get one sentence per row *and* the table as Markdown; big tables get Markdown groups and a summary, no row sentences. Why the difference?

<details><summary>Answer</summary>

A row sentence (`onglet « Ventes par région » · … · Région : Flandre ; CA du mois : 4568`) is a precise retrieval target: the question's words sit next to the number. The whole table in one chunk lets the LLM compare rows. For a 214-row list, one sentence per row would make hundreds of near-identical chunks that crowd the top k; grouped rows with the header repeated keep each chunk readable, and a summary chunk describes the table as a whole.
</details>

**6.** What does the summary chunk of the 214-row recall list contain, and which kind of question does it serve that no group of 20 rows can?

<details><summary>Answer</summary>

The table's heading, its row count, its columns, and for each column with at most 10 distinct values the count per value: `Statut : Réparée (211), Introuvable (installateur en cessation d'activité) (3)`. It answers **count** questions ("combien d'unités…") on the whole table, which a chunk holding 20 of the 214 rows can't.
</details>

**7.** The excel reader was fixed, the config didn't change, and the chunk count changed by one. Why was that lucky, and what protects us now?

<details><summary>Answer</summary>

The collection name only depends on config options. `index_corpus` reused a collection when its point count matched the chunk count: the rebuild happened only because the fix added one chunk. A fix that kept the same count would have left the **old chunks** in Qdrant and the experiment would have measured stale data, silently. Now every point carries a **fingerprint** (a hash of every chunk's document, index and text); a different fingerprint triggers a rebuild.
</details>

**8.** In `rag/tables.py`, why are the tables built from **raw** values (`raw_value`) rather than the displayed ones?

<details><summary>Answer</summary>

SQL computes on types: `SUM`, `MAX`, `ORDER BY` need numbers. `"-0,7 %"` and `"4 568"` are text: they would sort alphabetically and couldn't be added. Raw values keep numbers as REAL (percentages as fractions, which the `run_sql` description tells the LLM) and dates as ISO text, which sorts chronologically.
</details>

**9.** SQLite returned `[]` with no error for `SELECT "Chiffre" FROM t001` when no column is named `Chiffre`. What happened, and why is it dangerous for an LLM tool?

<details><summary>Answer</summary>

For backwards compatibility, SQLite treats a double-quoted identifier that matches no column as a **string literal**: the query selected the constant `'Chiffre'` (on an empty table: no rows). If the LLM misspells a column, the query "works" and returns a wrong answer, with no error to correct. `conn.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DML, False)` turns that off: an unknown name becomes an error the LLM sees and can fix.
</details>

**10.** The store refuses writes in two ways. Which, and why both?

<details><summary>Answer</summary>

1. `run_sql` accepts only one statement starting with `SELECT` or `WITH` (no `;` inside).
2. `PRAGMA query_only = ON` after loading: SQLite itself refuses any write on that connection.

The regex check gives the LLM a clear error message; the pragma protects even if the check has a hole (a test calls `store.execute("DELETE …")` directly and expects SQLite to refuse). Defence in depth: the same principle as phase B's read-only layers.
</details>

**11.** The tool loop allows `MAX_TOOL_ROUNDS = 5`. What happens in the last round, and why not let the model call tools until it's done?

<details><summary>Answer</summary>

In the last round the request is sent with `tool_choice = "none"`: the model must answer with what it has. Without a cap, a model that keeps calling tools (a query that always errors, a loop between `find_tables` calls) would never return and would consume tokens and time. A bounded loop guarantees an answer and a bounded latency.
</details>

**12.** Why is `tools_tables` (tools + a new prompt rule) acceptable as *one* experiment, despite the "one change at a time" rule?

<details><summary>Answer</summary>

The two parts are inseparable: tools without the rule that allows their results (rule 1 said "only from the extracts") and says when to use them would be ignored or misused; the rule without tools refers to tools that don't exist. The unit of change is "the LLM can compute on the tables". What matters is that nothing else changes (same chunks, same retrieval), and that the roadmap says so.
</details>

**13.** On the 2-per-type sample, `excel_lookup` correctness fell from 0.85 to 0.45 with the new reader. On all 13 `excel_lookup` questions it fell from 0.769 to 0.715. Which number should drive the decision, and why?

<details><summary>Answer</summary>

The second. With 2 questions, one verdict moves the mean by 0.5 × (change of that verdict): Q017 alone ("six personnes" vs "6 ETP", 1.0 → 0.2) made the 0.85 → 0.45 drop. On 13 questions the same answer moves the mean by about 0.06. A change aimed at some question types must be judged on **all** their questions (`--types`); the sample is for broad comparisons. Even 13 questions is small: read the questions that changed, not only the mean.
</details>

**14.** The reader alone (0.764) scores below Docling (0.795) on the 22 workbook questions, the reader + tools above (0.841). What can you conclude about the reader, and what experiment is missing?

<details><summary>Answer</summary>

That the gain comes from the **tools**, not from the reader's chunks; the reader is a means (raw typed values for SQL, units, percentages), not a gain by itself on this dev set. The missing run: **Docling chunks + tools** (the SQL store reads the workbooks with openpyxl independently of the chunking). Only that run tells whether the reader's chunks add anything on top of the tools. An honest report states the gap instead of crediting the reader.
</details>

**15.** After `git rm -r --cached enonces` on a branch and a commit there, the files were still on disk. Merging that branch into `main` deleted them. Why the difference?

<details><summary>Answer</summary>

`git rm --cached` only changes the index: the files stay on disk as untracked (and ignored). But the resulting commit **records a deletion**. On `main`, where those files were still tracked, merging applies that deletion like any other change: Git removes tracked files that the merged commit deletes, from the index *and* the working tree. Untracking files that must stay on disk on several branches means: untrack on one branch, then after merging, check the disk (or restore with `git restore --source=<an older commit> --worktree -- path`, which writes the files without tracking them again).
</details>

**16.** `git filter-repo` rewrote every commit to remove `enonces/`. What else had to be updated so that experiments stay reproducible, and how?

<details><summary>Answer</summary>

Each experiment row in PostgreSQL stores its `git_commit`: after the rewrite, those hashes pointed to commits that no longer exist in the history. filter-repo writes `.git/filter-repo/commit-map` (old hash → new hash); every `git_commit` was replaced through it, then each one was checked with `git cat-file -e`. The tags were moved by filter-repo itself; the hashes quoted in the docs were rewritten with the same map. Then `main` and the tags had to be **force**-pushed, since the new history doesn't contain the old one.
</details>

---

## Step 7: images and scans

**1.** What does llama-server need to serve a vision model, and what is the `mmproj` file?

<details><summary>Answer</summary>

Two files: the language model (`Qwen3.5-9B-UD-Q4_K_XL.gguf`) and its **multimodal projector** (`mmproj-F16.gguf`, passed with `--mmproj`). The projector turns the image's patches (after the vision encoder) into vectors in the language model's embedding space: "image tokens" the LLM reads like text tokens. The image is sent in the chat message as a base64 `data:` URL, through the same OpenAI-compatible API.
</details>

**2.** Why is every transcription cached, and why does the cache key include the model and the prompt?

<details><summary>Answer</summary>

Transcribing costs 5 to 14 s per image and needs the VLM on the GPU; it's an ETL step, done **once**, after which chunking and experiments read the JSON files without any model. The key includes the model and the prompt because the transcription depends on both: changing either must produce new transcriptions instead of silently reusing ones made with the old prompt (the same staleness problem as the Qdrant fingerprint of step 6).
</details>

**3.** `transcription(target, compute=False)` returns `None` when nothing is cached, and `vision_chunks` then raises an error. Why not just call the VLM there?

<details><summary>Answer</summary>

Chunking runs inside every indexing and experiment; the VLM usually isn't even running then (the generator or the judge holds the GPU). A hidden VLM call would fail obscurely, or worse, succeed with a different model or prompt and change the index without anyone noticing. Separating "transcribe" (an explicit script, with the VLM up) from "chunk" (reads only) keeps each step predictable, and the error message says exactly what to run.
</details>

**4.** The hand check of 10 transcriptions found 0 wrong numbers but 9 omissions and 4 inventions. What does that tell you about how to use VLM output?

<details><summary>Answer</summary>

The VLM rarely **misreads** what it copies (even the blurry 1120 °C and handwriting), but it **skips** text that doesn't sit in an obvious block (labels along the lines of a diagram, a maker's name, a footnote) and can **add** plausible content (a "Description" column on a plan). So: a missing value is more likely than a wrong one (Q034 is unanswerable because 500 Mbit/s was never copied); the descriptions are less reliable than the transcriptions; and showing the image next to the answer (the bonus) lets the user check.
</details>

**5.** Docling's OCR and the VLM both found 7/7 evidence snippets on the scans. Why keep the VLM, which is slower?

<details><summary>Answer</summary>

The snippet score only checks a few short strings; a word-level comparison of one page showed the OCR garbling two whole lines, one of them the L4 investment resolution, exactly what board questions ask about. The VLM got every line, and it's one tool for scans *and* images (handwriting, charts, diagrams). A metric that only samples a few strings can hide quality differences: look at the text too.
</details>

**6.** With the 256-token budget, 45 of the 65 images or pages were split in several chunks. Why is that worse for an image than for a text document, and how did `vision_max_tokens = 1024` show it?

<details><summary>Answer</summary>

A text document has headings and paragraphs; a cut usually falls between ideas. An image's transcription is a single unit whose meaning is often in **relations** (a box under its manager in an org chart, a value next to its label in a table). Cutting it can separate the two halves of a fact: Q056's answer needs "Céline Moreau" and "Thomas Lambert" together, and they ended up in different chunks. With a 1024-token budget only 1 image is cut, and Q056 is answered (purchasing reports to Thomas Lambert).
</details>

**7.** `vision_whole_images` fixed Q056 but lost Q087 (a workbook value), and Q056 now also has a trap in its top 5. Explain both.

<details><summary>Answer</summary>

Longer chunks compete differently: a whole image chunk carries many words and can outrank a short workbook chunk (Q087's emissions value was pushed out of the top 5, probably by the "Emissions par scope" chart). The trap of Q056 is the **September 2025** org chart, where purchasing still reported to the CFO; whole, it is as complete and relevant as the April 2026 one. Retrieval found both versions; choosing the current one is a matter of dates (step 8), not of chunking.
</details>

**8.** The refusal rate on `out_of_corpus` dropped from 5/5 to 4/5 with the images indexed. Was it a hallucination?

<details><summary>Answer</summary>

No: Q116 ("quel ERP le bureau de Lille utilisait-il avant 2011 ?") was answered "the extracts say GesPro 7 since 2011, but don't say what Lille used before": an honest partial answer, as prompt rule 2 asks. The `refusal` metric only recognizes the exact sentence "Je ne sais pas", so it counts this as "not refused". Read the answers behind a metric before concluding; the judge's correctness on `out_of_corpus` measures the right thing.
</details>

**9.** The bonus `answer_images()` returns the images of the **cited** extracts only. Why not all the images in the top 5?

<details><summary>Answer</summary>

The top 5 often holds images the answer didn't use (the other org charts, a neighbouring chart). Showing them would mislead the reader about the source of a value. The citations ([2]) say which extracts the answer relies on; showing only their images lets the user check exactly what the VLM read for this answer. When the answer cites nothing, all the images are shown, as a fallback.
</details>

**10.** To stop the generator, `P=$(pgrep -f "llama-server .*Qwen3.8-27B.*--port 8000")` returned two PIDs and nothing was stopped, yet the script printed "generator stopped". What went wrong, and what is the safe way?

<details><summary>Answer</summary>

`pgrep -f` matches the full command line of every process, including the shell running the command, whose own command line contains the pattern. `kill` refused the two-line value, and the wait loop tested an invalid PID, so `kill -0` failed and the loop concluded "stopped". Safe way: list the processes, pick the exact PID, kill it, then verify both that the PID is gone and that the resource is freed (GPU memory, port). Never trust a success message whose check could fail for another reason.
</details>

---

## Step 8: time and versions

**1.** Recall@5 was already ≈ 1.0 on the decision questions. Why is step 8 still needed, and what does `trap_hit@5` measure that recall doesn't?

<details><summary>Answer</summary>

Recall says the **right** passage is in the top 5; it says nothing about **wrong** passages next to it. On a changing decision, the top 5 also holds the old value (an earlier minute, a draft, an old version), and the LLM must pick. `trap_hit@5` counts the questions whose top 5 contains a passage listed as a trap (outdated, draft, corrected later): 9 of 17 at the start of the step.
</details>

**2.** The ERP specification was dated 31/12/2026. Where did that date come from, and what rule fixed it without breaking the other 82 content dates?

<details><summary>Answer</summary>

`content_date` took the first date in the text: "Son éditeur arrête le support le 31 décembre 2026", the end of GesPro's support, not the date of the document. The fix: skip a date whose preceding 30 characters contain a cue that the date is a deadline, a start or a postponement ("jusqu'", "à compter", "report", "prévu", "support le", "from", "vanaf", "tot"), and keep scanning. The audit (all 89 content-dated documents read with their context) and a diff of the registry before/after showed exactly 7 documents changed.
</details>

**3.** The first version of the cue list contained Dutch "van". What broke, and what is the general lesson about cue words?

<details><summary>Answer</summary>

"van" means "of": it appears in "stand van zaken" (status as of) and "Revisie A van 10/04/2025", both genuine document dates, which were then skipped. Cue words must be specific to the meaning you want ("vanaf" = from, "tot" = until), not frequent function words, and each one deserves a test with a real phrase that must *not* trigger it.
</details>

**4.** Why exclude drafts and archives with a Qdrant `must_not` filter rather than removing them from the index or filtering after the search?

<details><summary>Answer</summary>

Removing them would lose them for good (the registry decides, the index keeps everything: a later question might need a draft, e.g. to explain an error). Filtering **after** the search would leave fewer than 5 eligible chunks whenever drafts took places among the 30 candidates. A `must_not` inside every prefetch means all 30 candidates are already eligible, and the freed places go to other documents: recall even rose (0.934 → 0.939).
</details>

**5.** After the status filter, Q063 got a **new** trap. Which, and why can't a status filter catch it?

<details><summary>Answer</summary>

The freed place went to the CODIR minute of 17 November 2025 ("vitesse limitée à 8 km/h"), superseded in January 2026 by 6 km/h. That minute is signed and final: its *status* is fine, its *content* is outdated. Only time-aware handling can deal with it: order by date, a prompt rule that the latest decision wins, or a structured view of decisions.
</details>

**6.** With `order = "chronological"`, why do the retrieval metrics still use the reranker's order, while the stored chunks and the citation checks use the chronological one?

<details><summary>Answer</summary>

Retrieval metrics (MRR, nDCG, hit@k) measure the **ranking**: changing the order given to the LLM must not change them, or the experiment would mix a retrieval effect into a generation change. Citations [n] refer to the numbering the LLM saw: checking `[2]` against the reranker's second chunk would be checking the wrong passage. So the pipeline returns both `chunks` (ranked) and `context` (as shown).
</details>

**7.** The reference-date filter (8.4) lowered recall from 0.939 to 0.910. Explain with Q093 why filtering on the document date is wrong for "what happened in May 2026?".

<details><summary>Answer</summary>

The May 2026 phishing simulation is reported in the quarterly cybersecurity report **dated 3 July 2026**: the source of an event is written after it. The filter `doc_date ≤ 31 May 2026` removed the only document holding the answer. A document's date says when it was written, not which period it covers. A correct version would need the period each document covers (`date_end` of a report, the meeting date of a minute that reports on earlier facts…) and would still fail on summaries written later.
</details>

**8.** The reference-date experiment is "not kept". Why record it in the report anyway?

<details><summary>Answer</summary>

Because the statement asks for "ce qui n'a rien changé, ou a dégradé les résultats", and because a negative result with its cause is knowledge: the next person who thinks of filtering by date learns why it fails here (event date ≠ document date) and what it would take to make it work. A report that only lists gains hides how much was tried and makes the gains look more certain than they are.
</details>

**9.** In 8.4, who decides what: the LLM or the code? Why split it that way?

<details><summary>Answer</summary>

The LLM only **extracts** a date from the question (a JSON `{"date": …}`, parsed and validated: an impossible date becomes `None`). The **code** decides what to do with it: build the Qdrant condition, keep undated chunks, combine with the status filter. The LLM is good at reading "en décembre 2025"; the code is predictable, testable and auditable. A malformed answer degrades to "no filter", never to a wrong filter. (Statement, exercise 3: "le LLM extrait, le code décide".)
</details>

**10.** On the 41 target questions, `time_rules` scores 0.790 against 0.785 for the reference, but loses on `decision_history` (0.933 → 0.817). Should it be kept? What did reading the answers show?

<details><summary>Answer</summary>

The overall difference is within noise (one verdict ≈ 0.02), so the decision rests on the per-type pattern and on the answers. Rule 8 ("mention the old value only to explain the change") made answers leaner: Q043 lost the earlier budget versions, Q066 part of the October context, Q149 the year. The judge penalizes missing details, but no answer became wrong. Meanwhile the rules help where traps matter most (current decisions, action tracking, board resolutions). Kept, with the trade-off written down; a rule tweak ("for a question about the past, give the full sequence") would be the next experiment.
</details>

---

## Step 9: final evaluation and delivery

**1.** Step 8 chose `time_rules` after judging the 41 decision/version questions. Step 9 judged it on the full sample and the image questions and dropped it. What was the methodological mistake?

<details><summary>Answer</summary>

Judging a change only on the questions it **targets** shows its benefit, never its side effects. Date ordering and a "latest wins" rule act on every answer, so they must be judged on every kind of question they can touch, and compared on the **same** question set. The image questions, which the 41 didn't include, lost 0.135. Rule: targeted judging (`--types`) to see if a change helps where intended, plus the broad sample (and any type it could plausibly hurt) before adopting it.
</details>

**2.** At one point the step 8 runs scored 0.770 on "the sample" and the reference 0.803. Why was that comparison meaningless?

<details><summary>Answer</summary>

The step 8 runs had been judged on only 10 of the 31 sample questions (those of the target types), the reference on all 31: two means over different question sets. Compared on the same 10, the gap was the known Q026/Q043 differences. Always compare means over the same questions (a join on question id), and print n next to every mean.
</details>

**3.** Why is the test set evaluated **once**, after the final choice, and not on the two finalists to pick the better one?

<details><summary>Answer</summary>

Choosing between configurations with the test set makes it part of the tuning: its score then overestimates performance on new questions, exactly what the held-out set exists to measure. The choice is made on dev (here between 47 and 56, judged on 77 questions); the test only reports how that choice generalizes.
</details>

**4.** On test, recall@5 is 0.850 (dev 0.939) but correctness 0.823 (dev 0.784). Is the system overfitted to the dev questions?

<details><summary>Answer</summary>

No sign of it: the statement's warning is "if the test scores are clearly lower". The answers are as good; only retrieval is lower, with 30 questions (≈ 3 points each), and two of the five misses are right answers built from documents the eval doesn't list (sales quotes, a SQL computation). Overfitting would show as answers that rely on tricks tuned to dev questions failing on new ones.
</details>

**5.** Q020 ("capacité nominale du chariot impliqué dans l'accident de Gand") is answered "Je ne sais pas". Why can't a single search find its answer, and what would?

<details><summary>Answer</summary>

It is a **chained** question: the incident report says which truck (nr. 9), and only then can the nameplate photo of truck nr. 9 be found. The question names neither, so no single query ranks the photo. A second hop is needed: decompose ("quel chariot ?", then "chariot nr. 9 capacité"), or link entities in the registry (truck → photo).
</details>

**6.** Why were the question and expected-answer texts removed from `results/final_answers.csv`?

<details><summary>Answer</summary>

They are the course's eval set, and the repository is public: the same reason `enonces/` was untracked and purged from the history. The ids and types are enough to join the results with `data/calorvia_eval.json` locally. The export must serve the report without republishing someone else's material.
</details>

**7.** While writing `RAPPORT.md`, four figures turned out wrong (a commit hash that doesn't exist, two scores, a per-type value from another run). What practice caught them?

<details><summary>Answer</summary>

Checking every number of the report against the database before committing, instead of trusting what was remembered or copied from an earlier table. A report is read as the truth about the experiments; one wrong figure undermines the rest. The commits, the scores and the n of each mean come from queries, not from memory.
</details>

---

## Step 10: the three sources

**1.** `test_postgres_refuses_writes_even_without_the_read_only_default` first runs `SET default_transaction_read_only = off`, then a `DELETE`. Why test it that way rather than just sending the `DELETE`?

<details><summary>Answer</summary>

A plain `DELETE` is refused by the read-only default *and* by the grants, so the test can't tell which layer stopped it. The default is a session setting that any user can turn off in one statement, and an injected or mistaken query could do just that. Turning it off first leaves only the grants in play, so the test proves the layer that can't be bypassed from inside the session.
</details>

**2.** `agent_ro` can run `SELECT TOP 1 * INTO #tmp FROM PAR_CODE` on SQL Server, but not `SELECT … INTO dbo.X`. Why the difference, and why must step 11 refuse both?

<details><summary>Answer</summary>

`dbo.X` would be a table in GESPRO, which needs `CREATE TABLE`, and `db_datareader` doesn't have it. `#tmp` lives in tempdb, which is open to every login. It can't damage the business data, but it is still a write: it uses server resources, and it means the "read-only" account can do something besides read. Defence in depth means the validation layer refuses every `SELECT INTO` rather than relying on where the table would end up.
</details>

**3.** Why does `columns_postgres.sql` read `pg_attribute` with `has_column_privilege` instead of `information_schema.columns`?

<details><summary>Answer</summary>

`information_schema.columns` only lists the columns the current user has some privilege on, so `national_number`, `iban` and `street_address` would silently disappear. Reading `pg_attribute` lists every column and flags the unreadable ones. The schema stays complete, and step 11's table card can show only the readable columns on purpose, with the model told why (no `SELECT *` on `employees`).
</details>

**4.** For question 2, the invoice lines give 1,230 units and the credit-note lines 270. Why is the answer 1,230 and not 960?

<details><summary>Answer</summary>

The 270 units are on a single credit note with reason `REGUL_TARIF`, which `PAR_CODE` describes as a price adjustment "sans retour de marchandise": it repeats quantities to compute a price difference, but no goods came back. Only `RETOUR` credit notes reduce the quantities. The column names can't tell you this, but the code list can, which is why the ontology and the table cards must carry code labels.
</details>

**5.** In accounting, classes 6 and 7 of 2025 add up to exactly 0. What happened, and what does it imply for an agent computing "le résultat net de 2025"?

<details><summary>Answer</summary>

On 31/12/2025, the appropriation entry `OD-2025-00041` debits 693000 ("bénéfice à reporter", class 6) and credits 140000 (equity) for the profit of 5,412,000 €, which balances the income statement to zero. The net result is classes 6–7 *without* 693000. An agent that applies the textbook formula (products − charges) will confidently answer 0, so the definition belongs in the certified ontology.
</details>

**6.** ERP revenue for May 2026 is 11,299,581.08 € and accounting revenue 10,947,075.29 €. What explains the gap, and how should the agent present it?

<details><summary>Answer</summary>

23 May invoices are still `EMISE` in the ERP (issued, not yet transferred to accounting). They total 352,505.79 €, exactly the gap. The agent should give both figures with their source and definition (invoiced vs booked) and explain the difference instead of picking one. This is also why "le chiffre d'affaires de mai" is ambiguous and deserves a clarifying question.
</details>

**7.** Question 12 links the ERP and payroll. Name the two things that must be normalized or interpreted to get 731.38 € from 731,384.61 €.

<details><summary>Answer</summary>

(1) The key: the ERP stores the staff number as `10405`, payroll as `M10405`, so the two must be normalized before matching (in Python, since no SQL join crosses the engines). (2) The unit: `payslip_lines.rate` is `0.1000`, a **percentage** (0.1 %), not a fraction. 731,384.61 × 0.1 / 100 = 731.38. A third detail is the period: the March monthly run pays commission on February's sales, and there's also a February correction run paid in March.
</details>

**8.** Why does `scripts/run_starter.py` read the expected answers from `enonces/` at run time instead of from a fixture in `tests/`?

<details><summary>Answer</summary>

The repo is public, and the questions and answers are the course's material (D39, D42). Reading them at run time keeps them out of Git. The unit tests of the checker (`tests/test_starter.py`) use synthetic answers, so they run anywhere, even without the course files.
</details>
