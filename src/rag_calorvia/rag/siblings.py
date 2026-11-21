"""Siblings (step 40): the other chunks of the documents the reranker kept, scored, and the best of the newest added.

"Où en est le rappel préventif des pompes à chaleur Aéris 12 ?" (Q008): the reranker's top 10 held the December 2025
launch nine times and, 10th, the decisions table of the 2 March 2026 minutes ("La campagne de rappel de l'Aéris 12 sera
clôturée le 31 mars 2026"). The same minutes' agenda item "4. Aéris 12 : clôture du rappel" ("211 unités sur 214 ont
été réparées") was never among the 30 candidates: the folder holds dozens of chunks about the recall, and this one says
"rappel" once. Scored, it gets 0.585: below every chunk of the top 10, and 6th among the 38 other chunks of the top 10's
documents. Step 36 showed that reordering the candidates can't bring it in.

A document the reranker keeps is relevant; its other chunks are where its details are. Among those that also score
well, the newest document's come first: an older document's details are the ones a newer document updates.
"""
from qdrant_client import models

from rag_calorvia.etl.index import collection_name, get_qdrant
from rag_calorvia.etl.translate import search_text
from rag_calorvia.rag.rerank import NO_RERANKER, precise_date, score_in_languages

MAX_CHUNKS = 400   # siblings fetched per question at most: a workbook can hold hundreds of row chunks


def with_filter(query_filter, documents):
    """The question's filter (statuses, role, reference date) and "one of these documents"."""
    condition = models.FieldCondition(key="document", match=models.MatchAny(any=documents))
    if query_filter is None:
        return models.Filter(must=[condition])
    return models.Filter(must=[*(query_filter.must or []), condition], must_not=query_filter.must_not)


def fetch_siblings(chunks, config, query_filter):
    """The indexed chunks of the chunks' documents, the chunks themselves left out."""
    have = {(chunk["document"], chunk["chunk_index"]) for chunk in chunks}
    documents = list(dict.fromkeys(chunk["document"] for chunk in chunks))
    points, _ = get_qdrant().scroll(collection_name(config), scroll_filter=with_filter(query_filter, documents),
                                    limit=MAX_CHUNKS, with_payload=True)
    return [point.payload for point in points if (point.payload["document"], point.payload["chunk_index"]) not in have]


def pick(scored, count, min_score):
    """At most `count` siblings scoring at least min_score: the newest document first (dates to the day or month),
    then the best score. An undated chunk comes after the dated ones."""
    good = [chunk for chunk in scored if chunk["rerank_score"] >= min_score]
    good.sort(key=lambda chunk: (precise_date(chunk), chunk["rerank_score"]), reverse=True)
    return good[:count]


def add_siblings(question, chunks, config, query_filter=None, versions=None):
    """[reranker] siblings = N: the chunks, then up to N siblings (score >= sibling_min_score, 0.5 by default).

    Added after the reranker's chunks, so the retrieval metrics @5 don't change; each is scored against the question
    in its language when translations were made."""
    options = config["reranker"]
    count = options.get("siblings", 0)
    if not count or not chunks or options["model"] == NO_RERANKER:
        return chunks
    siblings = fetch_siblings(chunks, config, query_filter)
    if not siblings:
        return chunks
    scores = score_in_languages(options["model"], question, [{**s, "text": search_text(s)} for s in siblings],
                                versions or {}, range(len(siblings)))
    scored = [{**siblings[i], "rerank_score": s, "sibling": True} for i, s in scores]
    return chunks + pick(scored, count, options.get("sibling_min_score", 0.5))
