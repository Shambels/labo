"""What search() asks Qdrant for, per method (no server: the embedder and the client are replaced)."""
from types import SimpleNamespace

import pytest
from qdrant_client import models

from rag_calorvia.rag import search as module

CONFIG = {"embedder": {"model": "m", "query_instruction": ""},
          "search": {"method": "hybrid", "fusion": "rrf", "rrf_k": 60, "candidates": 30},
          "chunking": {"max_tokens": 256, "context_line": True}}
FILTER = models.Filter(must_not=[models.FieldCondition(key="status", match=models.MatchAny(any=["draft"]))])


class FakeQdrant:
    def query_points(self, collection, **request):
        self.collection, self.request = collection, request
        return SimpleNamespace(points=[SimpleNamespace(payload={"text": "t"}, score=0.5)])


@pytest.fixture
def qdrant(monkeypatch):
    client = FakeQdrant()
    embedded = []
    monkeypatch.setattr(module, "get_qdrant", lambda: client)
    monkeypatch.setattr(module, "embed", lambda texts, model: embedded.extend(texts) or [[float(i)] for i, _ in enumerate(texts)])
    client.embedded = embedded
    return client


def config(**search):
    return {**CONFIG, "search": {**CONFIG["search"], **search}}


def test_the_result_is_the_payload_with_the_score(qdrant):
    assert module.search("q", CONFIG) == [{"text": "t", "search_score": 0.5}]
    assert qdrant.request["limit"] == 30 and qdrant.request["with_payload"] is True


def test_dense_search_uses_the_instruction(qdrant):
    module.search("q", {**config(method="dense"), "embedder": {"model": "m", "query_instruction": "Find"}}, FILTER)
    assert qdrant.embedded == ["Instruct: Find\nQuery: q"]
    assert qdrant.request["using"] == "dense" and qdrant.request["query_filter"] is FILTER
    assert "prefetch" not in qdrant.request


def test_sparse_search_needs_no_embedding(qdrant):
    module.search("q", config(method="sparse"))
    assert qdrant.embedded == [] and qdrant.request["using"] == "sparse"
    assert qdrant.request["query"].text == "q" and qdrant.request["query"].options["language"] == "french"


def test_hybrid_search_filters_each_prefetch(qdrant):
    module.search("q", CONFIG, FILTER)
    assert [p.using for p in qdrant.request["prefetch"]] == ["dense", "sparse"]
    assert all(p.filter is FILTER and p.limit == 30 for p in qdrant.request["prefetch"])
    assert isinstance(qdrant.request["query"], models.RrfQuery) and qdrant.request["query_filter"] is FILTER


def test_one_version_is_the_plain_question(qdrant):
    module.search("q", CONFIG, versions={"fr": "other"})
    assert qdrant.embedded == ["q"]


def test_each_translation_gets_its_searches_and_its_stemmer(qdrant):
    module.search("q", config(fusion="dbsf"), versions={"fr": "q", "nl": "v"})
    assert qdrant.embedded == ["q", "v"] and len(qdrant.request["prefetch"]) == 4
    assert qdrant.request["prefetch"][3].query.options["language"] == "dutch"
    assert isinstance(qdrant.request["query"], models.FusionQuery)


@pytest.mark.parametrize("settings, versions, message", [
    ({"method": "other"}, None, "unknown search method"),
    ({"fusion": "other"}, None, "unknown fusion"),
    ({"method": "dense"}, {"fr": "q", "nl": "v"}, "needs \\[search\\] method"),
])
def test_bad_settings_are_refused(qdrant, settings, versions, message):
    with pytest.raises(ValueError, match=message):
        module.search("q", config(**settings), versions=versions)
