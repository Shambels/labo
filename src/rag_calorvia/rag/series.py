"""Series (step 41): when the reranker keeps a document of a series, the next documents of that series are read too.

The CODIR meets weekly, the COPIL of Atlas every two weeks, the reports are monthly: a decision, a project's state or a
figure is written in one document and updated in the next ones. Q008 ("Où en est le rappel de l'Aéris 12 ?") gets the
2 March 2026 minutes, which say the recall "sera clôturée le 31 mars 2026"; the minutes after it, which say what
happened, never reach the context, because the reranker only sees the 30 candidates of the search and the search
favours the many chunks that say "rappel" most. Siblings (step 40) read the other chunks of the kept documents; this
reads the documents that follow them in their series.

A series is the documents of one periodic type in one folder (the year folders ignored: CODIR/2025 and CODIR/2026 are
one series), from the registry. For each series among the kept chunks, the documents dated after the newest kept one
are read (the next `series_follow`, all when 0); their chunks scoring at least `series_min_score` are candidates, and
`newer_in_series` of them are added after the others, the newest document first, as for the siblings: the later a
document, the more it has the last word. Q008's answer is four meetings later: the 30 March minutes ("Clôturée.
Campagne clôturée : 211 unités réparées, 3 introuvables"). The question's filter applies: no draft, no document the role can't
read, nothing after the question's reference date.
"""
import re
from functools import cache

from rag_calorvia import db
from rag_calorvia.etl.index import collection_name, get_qdrant
from rag_calorvia.etl.translate import search_text
from rag_calorvia.rag.rerank import NO_RERANKER, score_in_languages
from rag_calorvia.rag.search import within
from rag_calorvia.rag.siblings import pick

PERIODIC = {"codir_minutes", "board_minutes", "copil_minutes", "safety_committee", "monthly_report",
            "management_comments", "production_report", "sales_meeting", "newsletter", "dashboard"}
MAX_CHUNKS = 400


def series_key(path, doc_type):
    """(type, folder without its year folders), or None for a document that is not periodic."""
    if doc_type not in PERIODIC:
        return None
    return doc_type, re.sub(r"/20\d\d(?=/|$)", "", path.rpartition("/")[0])


@cache
def registry_series():
    """{series key: [(date, path, status)], oldest first} from the registry."""
    with db.connect(read_only=True) as conn:
        documents = db.load_indexable_documents(conn)
    series = {}
    for document in documents:
        key = series_key(document["path"], document["doc_type"])
        if key and document["doc_date"]:
            series.setdefault(key, []).append((document["doc_date"].isoformat(), document["path"], document["status"]))
    return {key: sorted(members) for key, members in series.items()}


def next_documents(chunks, series, follow=0, excluded=()):
    """The documents after the newest kept one in each series the chunks belong to (the next `follow`, all when 0);
    statuses in `excluded` (drafts, archives) are skipped, as the search skips them."""
    newest = {}
    for chunk in chunks:
        key = series_key(chunk["document"], chunk.get("doc_type"))
        if key in series and chunk.get("doc_date"):
            newest[key] = max(newest.get(key, ""), chunk["doc_date"][:10])
    documents = []
    for key, date in newest.items():
        after = [path for day, path, status in series[key] if day > date and status not in excluded]
        documents += after[:follow] if follow else after
    return documents


def add_newer(question, chunks, config, query_filter=None, versions=None):
    """[reranker] newer_in_series = N: the chunks, then up to N chunks of the next documents of their series."""
    options = config["reranker"]
    count = options.get("newer_in_series", 0)
    if not count or not chunks or options["model"] == NO_RERANKER:
        return chunks
    documents = next_documents(chunks, registry_series(), options.get("series_follow", 0),
                               config["search"].get("exclude_status", []))
    if not documents:
        return chunks
    have = {(chunk["document"], chunk["chunk_index"]) for chunk in chunks}
    points, _ = get_qdrant().scroll(collection_name(config), scroll_filter=within(query_filter, documents),
                                    limit=MAX_CHUNKS, with_payload=True)
    later = [p.payload for p in points if (p.payload["document"], p.payload["chunk_index"]) not in have]
    if not later:
        return chunks
    scores = score_in_languages(options["model"], question, [{**c, "text": search_text(c)} for c in later],
                                versions or {}, range(len(later)))
    scored = [{**later[i], "rerank_score": s, "newer": True} for i, s in scores]
    return chunks + pick(scored, count, options.get("series_min_score", 0.5))
