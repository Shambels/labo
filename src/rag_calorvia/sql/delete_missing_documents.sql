-- Parameters: the list of paths present in the corpus. Removes the rows of files that no longer exist.
DELETE FROM documents WHERE path <> ALL(%s);
