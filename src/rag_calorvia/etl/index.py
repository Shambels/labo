"""Indexing: chunks -> dense (embedder) and sparse (BM25) vectors in Qdrant, one collection per index."""
import hashlib
import logging
import time
from functools import cache

from openai import OpenAI
from qdrant_client import QdrantClient, models

from rag_calorvia.config import settings
from rag_calorvia.etl.chunk import chunk_corpus

logger = logging.getLogger(__name__)

EMBED_BATCH = 64
UPSERT_BATCH = 256

# Payload fields later steps filter on: an index makes the filter fast and lets Qdrant plan the query.
# status (step 8: drafts, copies), language (step 5), doc_date/date_end (step 8: reference date of the question)
PAYLOAD_INDEXES = {
    "document": models.PayloadSchemaType.KEYWORD,
    "department": models.PayloadSchemaType.KEYWORD,
    "doc_type": models.PayloadSchemaType.KEYWORD,
    "status": models.PayloadSchemaType.KEYWORD,
    "language": models.PayloadSchemaType.KEYWORD,      # of the chunk; doc_language is the document's
    "source_type": models.PayloadSchemaType.KEYWORD,
    "sheet": models.PayloadSchemaType.KEYWORD,         # workbooks read with openpyxl (step 6)
    "doc_date": models.PayloadSchemaType.DATETIME,
    "date_end": models.PayloadSchemaType.DATETIME,
}


@cache
def get_qdrant():
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


@cache
def get_embedder():
    return OpenAI(base_url=settings.embeddings_url, api_key="EMPTY")  # vLLM asks for no key


def embed(texts, model):
    """Dense vectors of a list of texts, from the embeddings server. Used for chunks here and questions in search."""
    vectors = []
    for start in range(0, len(texts), EMBED_BATCH):
        response = get_embedder().embeddings.create(model=model, input=texts[start:start + EMBED_BATCH])
        vectors.extend(item.embedding for item in response.data)
    return vectors


# Snowball stemmers of Qdrant's BM25, by language code
STEMMERS = {"fr": "french", "nl": "dutch", "en": "english", "de": "german"}


def bm25(text, language="fr"):
    """Sparse BM25 vector, computed by the Qdrant server: tokens, stopwords and stemming of `language`.

    A Dutch text stemmed as French keeps 'magazijnen' and 'magazijn' apart, and its stopwords ('de', 'het', 'van')
    count as words. A chunk and the query that should find it must use the same language's stemmer.
    """
    return models.Document(text=text, model="qdrant/bm25", options={"language": STEMMERS.get(language, "french")})


def sparse_language(chunk, config):
    """The stemmer language of a chunk: French for all (baseline), or the chunk's own ([sparse] language = "per_chunk")."""
    return chunk["language"] if config.get("sparse", {}).get("language") == "per_chunk" else "fr"


def collection_name(config):
    """One collection per index: only [chunking], [sparse] and the embedder change the stored points.

    Any new option that changes the chunks or their vectors must be added here, or two indexes would share a name.
    """
    chunking = config["chunking"]
    name = f"calorvia__{config['embedder']['model']}__{chunking['max_tokens']}"
    if not chunking["context_line"]:
        name += "__no-context-line"
    if config.get("sparse", {}).get("language") == "per_chunk":
        name += "__bm25-per-language"
    if chunking.get("excel", "docling") == "openpyxl":
        name += "__excel-openpyxl"
    if chunking.get("vision", False):
        name += "__vision"
    return name


def fingerprint(chunks):
    """A hash of every chunk's document, index and text: changes whenever the chunking code changes its output."""
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(f"{chunk['document']}\x00{chunk['chunk_index']}\x00{chunk['text']}\x00".encode())
    return digest.hexdigest()[:16]


def stored_fingerprint(qdrant, name):
    """The fingerprint written in the collection's points (None for a collection built before fingerprints)."""
    points, _ = qdrant.scroll(name, limit=1, with_payload=["index_fingerprint"])
    return points[0].payload.get("index_fingerprint") if points else None


def index_corpus(config, force=False):
    """Build the collection of this config if it doesn't exist or doesn't hold these exact chunks.

    The collection name only says which options built it; a change in the chunking *code* (etl/excel.py fixed,
    say) keeps the name. Each point carries the fingerprint of the whole chunk list, so stale chunks are detected
    and rebuilt instead of being silently searched.
    """
    qdrant = get_qdrant()
    name = collection_name(config)
    chunks = chunk_corpus(config)  # a few seconds, and gives the expected points
    current = fingerprint(chunks)

    if not force and qdrant.collection_exists(name):
        stored = stored_fingerprint(qdrant, name)
        count = qdrant.count(name, exact=True).count
        if stored == current and count == len(chunks):
            logger.info("%s already indexed (%d chunks, fingerprint %s)", name, count, current)
            return {"collection": name, "chunks": count, "created": False, "seconds": 0.0}
        logger.warning("%s holds other chunks (%d points, fingerprint %s; expected %d, %s): rebuilding",
                       name, count, stored, len(chunks), current)

    start = time.time()
    vectors = embed([chunk["text"] for chunk in chunks], config["embedder"]["model"])

    if qdrant.collection_exists(name):
        qdrant.delete_collection(name)

    qdrant.create_collection(
        name,
        # The size comes from the embedder's answer, never from a constant: it depends on the model
        vectors_config={"dense": models.VectorParams(size=len(vectors[0]), distance=models.Distance.COSINE)},
        # IDF: Qdrant computes the "inverse document frequency" part of BM25 from the whole collection
        sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )

    for field, schema in PAYLOAD_INDEXES.items():
        qdrant.create_payload_index(name, field, schema)

    for batch_start in range(0, len(chunks), UPSERT_BATCH):
        qdrant.upsert(
            name,
            points=[
                models.PointStruct(
                    id=i,
                    vector={"dense": vectors[i], "sparse": bm25(chunks[i]["text"], sparse_language(chunks[i], config))},
                    payload={**chunks[i], "index_fingerprint": current},
                )
                for i in range(batch_start, min(batch_start + UPSERT_BATCH, len(chunks)))
            ],
            wait=True,
        )
    seconds = time.time() - start
    logger.info("%s: %d chunks indexed in %.1f s", name, len(chunks), seconds)
    return {"collection": name, "chunks": len(chunks), "created": True, "seconds": seconds}
