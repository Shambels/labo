"""Dutch and English chunks translated to French once, for the search (step 30g): [chunking] translate_to = "fr".

The corpus is 93 % French and its questions are French. Instead of translating each question (2 s, step 5b; on
demand, step 30d), the 147 non-French chunks are translated once. A translated chunk gets `search_text`, the French
context line and the French body: the index embeds it and stems it in French, and the reranker scores it against the
French question. `text` stays the original: it is what the generator reads and cites, so figures and names are quoted
as the document writes them.

Translations are cached in data/translations/, keyed by the text, the model and the prompt, and computed by
scripts/translate_chunks.py. Chunking only reads the cache: an index never calls the LLM by accident, and a missing
translation stops the indexing instead of silently mixing languages.
"""
import hashlib
import json
import logging
import time
from pathlib import Path

from rag_calorvia.config import settings

logger = logging.getLogger(__name__)

PROMPT = """Traduis en français ce passage d'un document de l'entreprise Calorvia (pompes à chaleur et ventilation).
Traduis tout, sans résumer, sans ajouter, sans commenter. Garde tels quels les noms propres, les codes, les références,
les nombres, les montants, les dates et les unités. Garde la mise en forme : lignes, listes, tableaux Markdown.
Utilise les termes français de l'entreprise (glossaire ci-dessous). Réponds uniquement par la traduction."""
GLOSSARY = Path("prompts/glossary_translation.txt")
FRENCH = "fr"


class MissingTranslation(RuntimeError):
    pass


def translates_chunks(config):
    return config["chunking"].get("translate_to") == FRENCH


def prompt():
    return PROMPT + "\n\n" + GLOSSARY.read_text(encoding="utf-8").strip()


def cache_path(text, model, instructions):
    key = hashlib.sha256(f"{text}|{model}|{instructions}".encode()).hexdigest()[:16]
    return settings.translations_path / f"{key}.json"


def translation(text, model, compute=True):
    """The cached French translation of a chunk body; computed and stored if missing (compute=False: None)."""
    instructions = prompt()
    path = cache_path(text, model, instructions)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["translation"]
    if not compute:
        return None
    from rag_calorvia.rag.generate import get_llm
    started = time.perf_counter()
    response = get_llm().chat.completions.create(
        model=model, temperature=0.0, max_tokens=2 * len(text) // 3 + 200,   # French runs longer than Dutch
        messages=[{"role": "system", "content": instructions}, {"role": "user", "content": text}])
    choice = response.choices[0]
    if choice.finish_reason == "length":
        logger.warning("translation cut: %r", text[:80])
    record = {"text": text, "model": model, "prompt": instructions, "translation": (choice.message.content or "").strip(),
              "seconds": round(time.perf_counter() - started, 1)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return record["translation"]


def split_context(chunk, has_context_line):
    """(context line or None, body): the context line is already French and is never translated."""
    if not has_context_line:
        return None, chunk["text"]
    line, _, body = chunk["text"].partition("\n")
    return line, body


def needs_translation(chunk):
    return (chunk.get("language") or FRENCH) != FRENCH


def with_french(chunk, config, compute=False):
    """The chunk with its French `search_text` when it is not in French; unchanged otherwise."""
    if not needs_translation(chunk):
        return chunk
    line, body = split_context(chunk, config["chunking"]["context_line"])
    french = translation(body, config["generation"]["model"], compute=compute)
    if french is None:
        raise MissingTranslation(f"no translation of {chunk['document']} #{chunk['chunk_index']}: "
                                 "run scripts/translate_chunks.py with this config first")
    return {**chunk, "search_text": "\n".join(p for p in [line, french] if p)}


def search_text(chunk):
    """What the index and the reranker read: the French version when there is one."""
    return chunk.get("search_text", chunk["text"])
