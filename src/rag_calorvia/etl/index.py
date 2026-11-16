"""Indexing: chunks -> dense (embedder) and sparse (BM25) vectors in Qdrant, one collection per index."""
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
    "language": models.PayloadSchemaType.KEYWORD,
    "source_type": models.PayloadSchemaType.KEYWORD,
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


def bm25(text):
    """Sparse BM25 vector, computed by the Qdrant server. Chunks and questions must use the same options.

    French stemming for every chunk for now: the Dutch and English ones get their own stemmer in step 5.
    """
    return models.Document(text=text, model="qdrant/bm25", options={"language": "french"})


def collection_name(config):
    """One collection per index: only [chunking] and the embedder change the stored vectors.

    Any new [chunking] option that changes the chunks must be added here, or two indexes would share a name.
    """
    chunking = config["chunking"]
    name = f"calorvia__{config['embedder']['model']}__{chunking['max_tokens']}"
    if not chunking["context_line"]:
        name += "__no-context-line"
    return name


def index_corpus(config, force=False):
    """Build the collection of this config if it doesn't exist (or is incomplete). Returns its name and stats."""
    qdrant = get_qdrant()
    name = collection_name(config)
    chunks = chunk_corpus(config)  # a few seconds, and gives the expected number of points

    if not force and qdrant.collection_exists(name):
        count = qdrant.count(name, exact=True).count
        if count == len(chunks):
            logger.info("%s already indexed (%d chunks)", name, count)
            return {"collection": name, "chunks": count, "created": False, "seconds": 0.0}
        logger.warning("%s has %d points instead of %d: rebuilding", name, count, len(chunks))

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
                models.PointStruct(id=i, vector={"dense": vectors[i], "sparse": bm25(chunks[i]["text"])}, payload=chunks[i])
                for i in range(batch_start, min(batch_start + UPSERT_BATCH, len(chunks)))
            ],
            wait=True,
        )
    seconds = time.time() - start
    logger.info("%s: %d chunks indexed in %.1f s", name, len(chunks), seconds)
    return {"collection": name, "chunks": len(chunks), "created": True, "seconds": seconds}
