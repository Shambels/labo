-- The copies dropped by the inventory, with the document kept in their place.
SELECT path, duplicate_of FROM documents WHERE duplicate_of IS NOT NULL ORDER BY path;
