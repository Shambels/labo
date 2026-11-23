"""The semantic layer of the documents (step 41): who and what the corpus talks about, found by the LLM, merged, reviewed.

Phase B's ontology (step 12) describes the ERP's tables; the documents had nothing like it. A question names things
("l'Aéris 12", "le site de Gand", "le projet Atlas", "Pieter De Smet") that the search only finds through the words of
each chunk: Gand is "Gent" in the Dutch reports, Atlas is "le nouvel ERP" in the minutes, a person's role is in another
document than the one that answers. The layer is a list of entities, each with its kind, its other names, what the
documents say it is and the documents that mention it, built in three passes:

1. extract (scripts/build_entities.py, needs the generator): the entities of each document, cached in data/entities/;
2. merge (merge_entities): the same entity found in many documents becomes one, its names and aliases joined;
3. review (knowledge/entities_review.yaml): entities dropped, merged or renamed by hand, as phase B's terms were
   certified (step 12); the result, knowledge/entities.json, is committed and is what the RAG reads (rag/entities.py).
"""
import hashlib
import json
import logging
import re
import time
import unicodedata

from rag_calorvia.config import settings

logger = logging.getLogger(__name__)

KINDS = ["personne", "site", "produit", "client", "fournisseur", "projet", "instance", "équipement", "autre"]
PROMPT = """Tu construis le référentiel des entités de l'entreprise Calorvia (pompes à chaleur et ventilation) à partir
de ses documents. Liste les entités nommées du document : personnes, sites et bâtiments, produits et gammes, clients,
fournisseurs et partenaires, projets, instances (comités, conseils), équipements et lignes de production.
Une ligne par entité, quatre champs séparés par « | » :
nom | type | alias | description
- nom : son nom le plus complet dans le document ;
- type : un de personne, site, produit, client, fournisseur, projet, instance, équipement, autre ;
- alias : les autres noms que le document lui donne (sigle, nom court, nom dans une autre langue), séparés par « ; »,
  vide s'il n'y en a pas ;
- description : ce que le document dit qu'elle est, en 10 mots au plus (la fonction d'une personne, le rôle d'un site,
  la nature d'un produit ou d'un projet), sans montants.
Exemple : Pieter De Smet | personne | | directeur du site de Gand
Ne liste ni Calorvia elle-même, ni les départements, ni les dates, ni les montants, ni les documents. N'invente rien :
seulement ce que le document écrit. Réponds uniquement par les lignes."""
MAX_DOCUMENT_CHARS = 12000   # the entities of a long workbook are in its first rows; the list's length is the cost
MIN_KEY = 3   # names and aliases shorter than this (normalized) are dropped: "L4" stays, "A" doesn't


def normalize(text):
    """Lower case, no accents, punctuation as spaces: 'Aéris 12' and 'AERIS-12' both give 'aeris 12'."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def parse_lines(text):
    """The LLM's lines 'nom | type | alias ; alias | description' -> [{nom, type, alias, description}].
    One line per entity costs half the tokens of JSON: the output, not the document, is what takes the time."""
    entities = []
    for line in (text or "").splitlines():
        fields = [f.strip() for f in line.strip().strip("-* ").split("|")]
        if len(fields) != 4 or not fields[0] or fields[0].lower() == "nom":
            continue
        entities.append({"nom": fields[0], "type": fields[1].lower(),
                         "alias": [a.strip() for a in fields[2].split(";") if a.strip()], "description": fields[3]})
    return entities


def cache_path(document, text, model):
    key = hashlib.sha256(f"{document}|{text}|{model}|{PROMPT}".encode()).hexdigest()[:16]
    return settings.entities_path / f"{key}.json"


def document_entities(document, text, model, compute=True):
    """The entities the LLM finds in one document: [{nom, type, alias, description}], cached."""
    path = cache_path(document, text, model)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["entities"]
    if not compute:
        return None
    from rag_calorvia.rag.generate import get_llm
    started = time.perf_counter()
    response = get_llm().chat.completions.create(
        model=model, temperature=0.0, max_tokens=2000,
        messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": text}])
    entities = parse_lines(response.choices[0].message.content)
    record = {"document": document, "model": model, "entities": entities,
              "seconds": round(time.perf_counter() - started, 1)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return entities


class Groups:
    """Union-find over normalized names: two names in one group are one entity."""

    def __init__(self):
        self.parent = {}

    def find(self, key):
        self.parent.setdefault(key, key)
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def merge_entities(found, dates=None):
    """{document: [entity]} -> [{name, kind, aliases, descriptions, documents}], most documents first.

    Two mentions are one entity when they share a name, or when one's alias is the other's name. An alias claimed by
    several entities that share no name ("Marc" for two people) links nothing and is kept out of the aliases: it
    would make the question matcher pick one at random. descriptions: the distinct ones, newest document first.
    """
    dates = dates or {}
    mentions = []
    for document, entities in found.items():
        for entity in entities:
            name = " ".join((entity.get("nom") or "").split())
            if len(normalize(name)) < MIN_KEY or entity.get("type") not in KINDS:
                continue
            aliases = [a for a in (" ".join(x.split()) for x in entity.get("alias") or [])
                       if len(normalize(a)) >= MIN_KEY and normalize(a) != normalize(name)]
            mentions.append({"name": name, "kind": entity["type"], "aliases": aliases,
                             "description": " ".join((entity.get("description") or "").split()), "document": document})
    names = {normalize(m["name"]) for m in mentions}
    claimants = {}
    for m in mentions:
        for alias in m["aliases"]:
            claimants.setdefault(normalize(alias), set()).add(normalize(m["name"]))
    groups = Groups()
    for key in names:
        groups.find(key)
    for m in mentions:
        for alias in m["aliases"]:
            key = normalize(alias)
            if key in names or len(claimants[key]) == 1:
                groups.union(normalize(m["name"]), key)
    # a shared alias that still names two groups after the merges is ambiguous
    ambiguous = {key for key, owners in claimants.items() if len({groups.find(o) for o in owners}) > 1}
    merged = {}
    for m in mentions:
        root = groups.find(normalize(m["name"]))
        entry = merged.setdefault(root, {"names": {}, "kinds": {}, "aliases": {}, "descriptions": [], "documents": []})
        entry["names"][m["name"]] = entry["names"].get(m["name"], 0) + 1
        entry["kinds"][m["kind"]] = entry["kinds"].get(m["kind"], 0) + 1
        for alias in m["aliases"]:
            if normalize(alias) not in ambiguous:
                entry["aliases"][alias] = entry["aliases"].get(alias, 0) + 1
        if m["description"]:
            entry["descriptions"].append((dates.get(m["document"]) or "", m["description"], m["document"]))
        if m["document"] not in entry["documents"]:
            entry["documents"].append(m["document"])
    out = []
    for entry in merged.values():
        name = max(entry["names"], key=lambda n: (entry["names"][n], len(n)))   # the most frequent, then the longest
        others = [n for n in [*entry["names"], *entry["aliases"]] if normalize(n) != normalize(name)]
        aliases = list(dict.fromkeys(others, None))
        seen, descriptions = set(), []
        for date, text, document in sorted(entry["descriptions"], key=lambda d: d[0], reverse=True):
            if normalize(text) not in seen:
                seen.add(normalize(text))
                descriptions.append({"text": text, "document": document, "date": date or None})
        out.append({"name": name, "kind": max(entry["kinds"], key=entry["kinds"].get),
                    "aliases": dedupe_normalized(aliases, name), "descriptions": descriptions[:3],
                    "documents": sorted(entry["documents"])})
    return sorted(out, key=lambda e: (-len(e["documents"]), e["name"]))


def dedupe_normalized(aliases, name):
    """Aliases that differ from the name and from each other once normalized ('Aéris 12', 'AERIS 12': one)."""
    seen, kept = {normalize(name)}, []
    for alias in aliases:
        if normalize(alias) not in seen:
            seen.add(normalize(alias))
            kept.append(alias)
    return kept


def apply_review(entities, review):
    """The hand review (knowledge/entities_review.yaml): drop, merge {kept name: [other names]}, rename, aliases,
    drop_aliases {name: [aliases]}, describe {name: text} (a checked description, shown before the extracted ones,
    with no source document), kind.

    Names are matched normalized. A merged entity brings its aliases, descriptions and documents to the kept one."""
    review = review or {}
    by_name = {normalize(e["name"]): e for e in entities}
    for kept, others in (review.get("merge") or {}).items():
        target = by_name.get(normalize(kept))
        if target is None:
            raise KeyError(f"review: no entity named {kept!r} to merge into")
        for other in others:
            source = by_name.pop(normalize(other), None)
            if source is None:
                raise KeyError(f"review: no entity named {other!r} to merge into {kept!r}")
            target["aliases"] = dedupe_normalized([*target["aliases"], source["name"], *source["aliases"]],
                                                  target["name"])
            target["descriptions"] = (target["descriptions"] + source["descriptions"])[:3]
            target["documents"] = sorted(set(target["documents"]) | set(source["documents"]))
    for name in review.get("drop") or []:
        if by_name.pop(normalize(name), None) is None:
            raise KeyError(f"review: no entity named {name!r} to drop")
    for old, new in (review.get("rename") or {}).items():
        entity = by_name.pop(normalize(old))
        entity["aliases"] = dedupe_normalized([old, *entity["aliases"]], new)
        entity["name"] = new
        by_name[normalize(new)] = entity
    for name, extra in (review.get("aliases") or {}).items():
        entity = by_name[normalize(name)]
        entity["aliases"] = dedupe_normalized([*entity["aliases"], *extra], entity["name"])
    for name, wrong in (review.get("drop_aliases") or {}).items():
        entity = by_name[normalize(name)]
        bad = {normalize(a) for a in wrong}
        entity["aliases"] = [a for a in entity["aliases"] if normalize(a) not in bad]
    for name, text in (review.get("describe") or {}).items():
        entity = by_name[normalize(name)]
        entity["descriptions"] = [{"text": text, "document": None, "date": None}, *entity["descriptions"]][:3]
    for name, kind in (review.get("kind") or {}).items():
        by_name[normalize(name)]["kind"] = kind
    return sorted(by_name.values(), key=lambda e: (-len(e["documents"]), e["name"]))
