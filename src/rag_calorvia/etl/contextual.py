"""Contextual chunks (step 41): one or two sentences, written once by the LLM, that place each chunk in its document.

The context line says which document a chunk comes from ("[PV du CODIR du 2 mars 2026 · ...]"), not what the chunk is
about within it. A row of an action table, an agenda item ("4. Aéris 12 : clôture du rappel", Q008) or a page of a
transcribed chart says little on its own: the search finds it only when the question uses its words. A sentence that
names the subject, the part of the document, the site or the period gives the dense and the lexical search more to
match ("contextual retrieval": the context is written with the whole document in view).

[chunking] contextual = true puts the sentence on the line after the context line, in `text` (and `search_text`): the
index embeds and stems it, the reranker scores it, the generator reads it. Contexts are cached in data/contexts/,
keyed by the document, the chunk, the model and the prompt, and computed by scripts/contextualize_chunks.py. Chunking
only reads the cache: a missing context stops the indexing, as a missing translation does (step 30g).
"""
import hashlib
import json
import logging
import time

from rag_calorvia.config import settings
from rag_calorvia.etl.documents import body_of, by_document, document_text

logger = logging.getLogger(__name__)

PROMPT = """Voici un document de l'entreprise Calorvia (pompes à chaleur et ventilation), puis un extrait de ce document.
Écris une ou deux phrases courtes, en français, qui situent l'extrait dans le document : la partie ou la rubrique où il
se trouve, et ce dont il parle (le produit, le projet, le site, la personne, la période). Ne répète pas le type, le titre
ni la date du document : ils sont déjà connus. Ces phrases servent à retrouver l'extrait par une recherche. N'ajoute rien qui ne soit pas dans le document, ne recopie
pas les chiffres de l'extrait, ne commence pas par « Cet extrait ». Réponds uniquement par ces phrases."""
MAX_DOCUMENT_CHARS = 24000   # about 8k tokens: the start of a long workbook is enough to say what it is
CONTEXT_PREFIX = "Contexte : "


class MissingContext(RuntimeError):
    pass


def contextualizes(config):
    return config["chunking"].get("contextual", False)


def cache_path(document, body, model):
    key = hashlib.sha256(f"{document}|{body}|{model}|{PROMPT}".encode()).hexdigest()[:16]
    return settings.contexts_path / f"{key}.json"


def context(document, document_text_, body, model, compute=True):
    """The cached context of a chunk; computed and stored if missing (compute=False: None).

    The document comes first in the user message and the chunk last: llama-server keeps the prompt's common prefix in
    its cache, so the chunks of one document, done in a row, pay for the document once."""
    path = cache_path(document, body, model)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["context"]
    if not compute:
        return None
    from rag_calorvia.rag.generate import get_llm
    started = time.perf_counter()
    response = get_llm().chat.completions.create(
        model=model, temperature=0.0, max_tokens=120,
        messages=[{"role": "system", "content": PROMPT},
                  {"role": "user", "content": f"<document>\n{document_text_}\n</document>\n\n<extrait>\n{body}\n</extrait>"}])
    text = " ".join((response.choices[0].message.content or "").split())
    record = {"document": document, "body": body, "model": model, "context": text,
              "seconds": round(time.perf_counter() - started, 1)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return text


def with_context_sentence(text, sentence, has_context_line):
    """The sentence on the line after the context line (first line when there is none)."""
    line = f"{CONTEXT_PREFIX}{sentence}"
    if not has_context_line:
        return f"{line}\n{text}"
    head, _, body = text.partition("\n")
    return f"{head}\n{line}\n{body}"


def add_contexts(chunks, config, compute=False):
    """Every chunk with its context sentence in `text` (and in `search_text` when it has a French version)."""
    has_line, model = config["chunking"]["context_line"], config["generation"]["model"]
    out = []
    for document, members in by_document(chunks).items():
        whole = document_text(members, has_line, MAX_DOCUMENT_CHARS)
        for chunk in members:
            sentence = context(document, whole, body_of(chunk, has_line), model, compute=compute)
            if sentence is None:
                raise MissingContext(f"no context for {document} #{chunk['chunk_index']}: "
                                     "run scripts/contextualize_chunks.py with this config first")
            new = {**chunk, "text": with_context_sentence(chunk["text"], sentence, has_line)}
            if "search_text" in chunk:
                new["search_text"] = with_context_sentence(chunk["search_text"], sentence, has_line)
            out.append(new)
    return out
