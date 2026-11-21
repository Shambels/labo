"""Step 41: the miss analysis, the corpus description, the semantic layer, the series, the contextual chunks."""
import importlib.util
import sys
from pathlib import Path

from rag_calorvia.rag.generate import load_system_prompt


def load_script(name, argv):
    """A script's functions, without running its command line (its argparse sees `argv`)."""
    spec = importlib.util.spec_from_file_location(name, Path("scripts") / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    old, sys.argv = sys.argv, [name, *argv]
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    finally:
        sys.argv = old
    return module


def test_the_corpus_description_comes_after_the_rules():
    rules = {"generation": {"system_prompt": "prompts/tools_complete.txt"}}
    with_corpus = {"generation": {**rules["generation"], "corpus": "prompts/corpus.txt"}}
    plain, described = load_system_prompt(rules), load_system_prompt(with_corpus)
    assert described.startswith(plain) and len(described) > len(plain)
    assert "Gand" in described and "Gent" in described and "plus récent" in described
    assert "fiche de non-conformité" in described   # the details of rule 4 per kind of document
