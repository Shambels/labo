"""Question translation (step 5): the French question in Dutch and English, to search the documents written in them.

BM25 matches words: a French question shares none with a Dutch passage. Searching with a Dutch translation (and
the Dutch stemmer) lets the lexical search find it too; dense search gets three phrasings of the same need.

Step 30: [search] glossary = "prompts/glossary_translation.txt" adds the company's words to the prompt. In step 5 the
LLM translated "chariots élévateurs" as "reachstackers"; the Gent documents say "heftrucks". The glossary is built from
the vocabulary of the corpus's Dutch and English documents, not from the questions.
"""
import json
import logging
from pathlib import Path

from rag_calorvia.rag.generate import get_llm

logger = logging.getLogger(__name__)

TRANSLATION_PROMPT = """Traduis la question en néerlandais et en anglais, sans y répondre.
Garde tels quels les noms propres, les codes, les nombres et les unités.
Réponds uniquement avec un objet JSON de la forme {"nl": "...", "en": "..."}."""


def parse_translations(content, languages):
    """{language: text} for the requested languages found in the LLM's JSON; {} if it isn't valid JSON."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {lang: text.strip() for lang, text in data.items() if lang in languages and isinstance(text, str) and text.strip()}


def translation_prompt(config):
    """The instructions, with the glossary of [search] glossary when there is one."""
    glossary = config["search"].get("glossary")
    if not glossary:
        return TRANSLATION_PROMPT
    return TRANSLATION_PROMPT + "\n\n" + Path(glossary).read_text(encoding="utf-8").strip()


def translate_question(question, config):
    """{'fr': question, 'nl': ..., 'en': ...} for the languages of [search] translate. On a malformed answer, only
    the French question: a failed translation must never cost the search its original question."""
    languages = config["search"].get("translate", [])
    if not languages:
        return {"fr": question}
    response = get_llm().chat.completions.create(
        model=config["generation"]["model"],  # the generator: the only LLM served next to the embedder and reranker
        temperature=0.0,
        max_tokens=256,
        messages=[{"role": "system", "content": translation_prompt(config)}, {"role": "user", "content": question}],
        response_format={"type": "json_object"},
    )
    translations = parse_translations(response.choices[0].message.content, languages)
    if len(translations) < len(languages):
        logger.warning("incomplete translation for %r: %s", question, translations)
    return {"fr": question, **translations}
