-- Parameters: a dict with the fields of etl.inventory.Document. Re-running the inventory updates the row.
INSERT INTO documents (path, format, size_bytes, sha256, content_hash, page_count, has_text_layer,
                       text_chars, duplicate_of, excluded_reason)
VALUES (%(path)s, %(format)s, %(size_bytes)s, %(sha256)s, %(content_hash)s, %(page_count)s,
        %(has_text_layer)s, %(text_chars)s, %(duplicate_of)s, %(excluded_reason)s)
ON CONFLICT (path) DO UPDATE SET
    format = EXCLUDED.format, size_bytes = EXCLUDED.size_bytes, sha256 = EXCLUDED.sha256,
    content_hash = EXCLUDED.content_hash, page_count = EXCLUDED.page_count,
    has_text_layer = EXCLUDED.has_text_layer, text_chars = EXCLUDED.text_chars,
    duplicate_of = EXCLUDED.duplicate_of, excluded_reason = EXCLUDED.excluded_reason,
    inventoried_at = now();
