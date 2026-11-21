"""The semantic layer at question time (step 41): the entities a question names, their documents and what they are.

knowledge/entities.json (etl/entities.py, scripts/build_entities.py) lists who and what the documents talk about. A
question that names one of them gets two things:

- [search] entities = "knowledge/entities.json": one more dense search, restricted to the documents that mention the
  entities named (when they are specific: at most [search] entity_max_documents documents), fused with the others by
  RRF. "Gand" finds the Dutch reports that write "Gent"; a named supplier's documents come in even when the question's
  other words match another document better. The number of candidates stays [search] candidates.
- [generation] entity_cards = true: one more extract after the others, "[Référentiel des entités de Calorvia]", that
  says what each named entity is, from the newest document that describes it, so the generator knows Pieter De Smet
  is the director of the Gand site when the extract that answers only names him. It is numbered like an extract and
  may be cited; it never counts in the retrieval metrics (it is added to the context, not to the chunks).

Both respect the role (D77): a document the role can't read neither widens its search (the question's filter applies
to every prefetch) nor describes an entity on its card.
"""
import json
import re
from functools import cache
from pathlib import Path

from rag_calorvia.etl.entities import MIN_KEY, normalize
from rag_calorvia.rag.permissions import can_read

CARD_DOCUMENT = "knowledge/entities.json"
CARD_HEADER = "[Référentiel des entités de Calorvia, établi à partir des documents]"
MAX_CARDS = 5


@cache
def load_entities(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@cache
def keys_of(path):
    """[(normalized key, entity index)], longest first; a key shared by two entities belongs to neither."""
    owners = {}
    for i, entity in enumerate(load_entities(path)):
        for name in [entity["name"], *entity["aliases"]]:
            key = normalize(name)
            if len(key) >= MIN_KEY:
                owners.setdefault(key, set()).add(i)
    return sorted(((key, next(iter(ids))) for key, ids in owners.items() if len(ids) == 1),
                  key=lambda pair: -len(pair[0]))


def find_entities(question, path):
    """The entities a question names, in the order of their first mention. Longest names first, and a span already
    matched is not matched again: "Aéris 12" is the product, not also the "Aéris" range."""
    text, taken, found = f" {normalize(question)} ", [], {}
    for key, index in keys_of(path):
        for match in re.finditer(rf"(?<= ){re.escape(key)}(?= )", text):
            span = range(match.start(), match.end())
            if any(set(span) & set(other) for other in taken):
                continue
            taken.append(span)
            found.setdefault(index, match.start())
    entities = load_entities(path)
    return [entities[i] for i in sorted(found, key=found.get)]


def entities_of(question, config):
    path = config["search"].get("entities")
    return find_entities(question, path) if path else []


def entity_documents(entities, config, role=None):
    """The documents of the specific entities named: those mentioned in at most entity_max_documents documents.
    "Seneffe" is in 200 documents and narrows nothing; "Valtek" is in 12."""
    limit = config["search"].get("entity_max_documents", 15)
    documents = []
    for entity in entities:
        readable = [d for d in entity["documents"] if can_read(role, d)]
        if len(readable) <= limit:
            documents += readable
    return list(dict.fromkeys(documents))


def card(entities, role=None):
    """The extract that says what the named entities are, or None when none has a readable description."""
    lines = []
    for entity in entities:
        description = next((d for d in entity["descriptions"]   # a reviewed description has no document
                            if d["document"] is None or can_read(role, d["document"])), None)
        if description is None:
            continue
        aliases = [a for a in entity["aliases"] if len(normalize(a)) >= MIN_KEY][:3]
        also = f" ; aussi : {', '.join(aliases)}" if aliases else ""
        source = ""
        if description["document"]:
            source = f" (source : {Path(description['document']).stem}"
            source += f", {description['date']})" if description.get("date") else ")"
        lines.append(f"- {entity['name']} ({entity['kind']}{also}) : {description['text']}{source}")
        if len(lines) == MAX_CARDS:
            break
    if not lines:
        return None
    return {"document": CARD_DOCUMENT, "chunk_index": -1, "entity_card": True,
            "text": "\n".join([CARD_HEADER, *lines])}
