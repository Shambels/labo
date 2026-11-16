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
