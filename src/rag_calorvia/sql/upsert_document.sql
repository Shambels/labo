-- Parameters: a dict with the fields of etl.inventory.Document. Re-running the inventory updates the row.
INSERT INTO documents (path, format, size_bytes, sha256, content_hash, page_count, has_text_layer, text_chars, duplicate_of, excluded_reason, department, doc_type, doc_label, doc_date, date_end, date_precision, date_source, version, status, markers, language, source_type)
VALUES (%(path)s, %(format)s, %(size_bytes)s, %(sha256)s, %(content_hash)s, %(page_count)s, %(has_text_layer)s, %(text_chars)s, %(duplicate_of)s, %(excluded_reason)s, %(department)s, %(doc_type)s, %(doc_label)s, %(doc_date)s, %(date_end)s, %(date_precision)s, %(date_source)s, %(version)s, %(status)s, %(markers)s, %(language)s, %(source_type)s)
ON CONFLICT (path) DO UPDATE SET
    format = EXCLUDED.format,
    size_bytes = EXCLUDED.size_bytes,
    sha256 = EXCLUDED.sha256,
    content_hash = EXCLUDED.content_hash,
    page_count = EXCLUDED.page_count,
    has_text_layer = EXCLUDED.has_text_layer,
    text_chars = EXCLUDED.text_chars,
    duplicate_of = EXCLUDED.duplicate_of,
    excluded_reason = EXCLUDED.excluded_reason,
    department = EXCLUDED.department,
    doc_type = EXCLUDED.doc_type,
    doc_label = EXCLUDED.doc_label,
    doc_date = EXCLUDED.doc_date,
    date_end = EXCLUDED.date_end,
    date_precision = EXCLUDED.date_precision,
    date_source = EXCLUDED.date_source,
    version = EXCLUDED.version,
    status = EXCLUDED.status,
    markers = EXCLUDED.markers,
    language = EXCLUDED.language,
    source_type = EXCLUDED.source_type,
    inventoried_at = now();
