"""Step 36: the newest relevant chunks just below the top 5 are brought in (pure function, no server)."""
from rag_calorvia.rag.rerank import with_recent

OPTIONS = {"recent_slots": 2, "recent_window": 10, "recent_min_score": 0.5}


def chunk(name, score, date=None, precision="day"):
    return {"document": name, "rerank_score": score, "doc_date": date, "date_precision": precision if date else None}


def test_a_newer_relevant_chunk_below_the_top_replaces_the_lowest():
    ranked = [chunk("launch letter", 0.99, "2025-12-11"), chunk("launch minutes", 0.98, "2025-12-08"),
              chunk("faq", 0.98), chunk("dutch letter", 0.97, "2025-12-11"), chunk("board", 0.92, "2025-12-16"),
              chunk("8D report", 0.90, "2025-12-01"), chunk("closure minutes", 0.82, "2026-03-02")]
    out = with_recent(ranked, 5, OPTIONS)
    assert [c["document"] for c in out] == ["launch letter", "launch minutes", "faq", "dutch letter", "closure minutes"]


def test_nothing_changes_when_nothing_below_is_newer():
    ranked = [chunk(f"c{i}", 0.9 - i / 100, f"2026-0{9 - i}-01") for i in range(8)]
    assert with_recent(ranked, 5, OPTIONS) == ranked[:5]


def test_a_newer_chunk_must_still_be_relevant_and_precisely_dated():
    ranked = [chunk(f"c{i}", 0.9, "2025-01-01") for i in range(5)] + [
        chunk("weak", 0.3, "2026-05-01"), chunk("yearly", 0.8, "2026-12-31", precision="year"),
        chunk("undated", 0.8), chunk("outside the window", 0.8, "2026-05-01")]
    assert with_recent(ranked, 5, {**OPTIONS, "recent_window": 8}) == ranked[:5]


def test_at_most_the_slots_are_used_and_the_newest_win():
    ranked = [chunk(f"top{i}", 0.9, "2025-01-01") for i in range(5)] + [
        chunk("feb", 0.8, "2026-02-01"), chunk("may", 0.6, "2026-05-01"), chunk("mar", 0.7, "2026-03-01")]
    out = with_recent(ranked, 5, OPTIONS)
    assert [c["document"] for c in out] == ["top0", "top1", "top2", "mar", "may"]   # newest two, by score
