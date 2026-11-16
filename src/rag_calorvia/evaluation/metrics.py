"""Deterministic metrics against the eval set: no LLM, and the same ground truth for every chunking.

A question's evidence lists, document by document, the snippets that contain the answer:
grade 2 = contains the answer or a necessary part of it (with a fact number), grade 1 = useful, not necessary.
Same fact number = interchangeable sources; different numbers = complementary facts, all needed.
Traps list the passages that hold a wrong or outdated answer (draft, old version, minute corrected later).
"""
import math
import re
import unicodedata

K_VALUES = (3, 5, 10)  # computed for every k <= [search] top_k, so experiments with different top_k stay comparable


def normalize_numbers(text):
    """'4 568' -> '4568', '41,5' -> '41.5': the same rendering in chunks and evidence snippets.

    The workbook snippets of the eval set follow Docling's rendering (4568, 41.5); our own Excel reader (step 6)
    will display numbers as Excel does (4 568, 41,5). Applied to both sides, the comparison ignores the difference.
    """
    text = re.sub(r"(?<=\d)[   ](?=\d{3}\b)", "", text)  # space, no-break space, narrow no-break space
    return re.sub(r"(?<=\d),(?=\d)", ".", text)


def normalize(text):
    """Unicode NFC, single spaces, numbers without thousands separators and with a decimal point."""
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()
    return normalize_numbers(text)


def contains_all(chunk, document, snippets):
    """The chunk comes from `document` and its text contains every snippet."""
    if chunk["document"] != document:
        return False
    text = normalize(chunk["text"])
    return all(normalize(s) in text for s in snippets)


def judge_chunk(chunk, question):
    """Indices of the question's evidence items this chunk proves: the right document and every snippet in its text.

    The document must match: the same sentence in another document (an older minute recalling a decision) proves nothing.
    """
    return [i for i, e in enumerate(question["evidence"]) if contains_all(chunk, e["document"], e["snippets"])]


def is_trap(chunk, question):
    """The chunk holds one of the question's traps: a wrong or outdated answer."""
    return any(contains_all(chunk, trap["document"], trap["snippets"]) for trap in question.get("traps") or [])


def hit(matches, evidence, k):
    """1 if a chunk of the top k contains the answer or a necessary part of it (grade 2), else 0."""
    return float(any(evidence[i]["grade"] == 2 for ranked in matches[:k] for i in ranked))


def mrr(matches, evidence, k):
    """1 / rank of the first grade-2 chunk in the top k, 0 if none: is the best chunk at the top?"""
    for rank, ranked in enumerate(matches[:k], 1):
        if any(evidence[i]["grade"] == 2 for i in ranked):
            return 1 / rank
    return 0.0


def recall(matches, evidence, k):
    """Share of the needed facts found in the top k. A fact counts once, whichever of its sources was found."""
    needed = {e["fact"] for e in evidence if e["grade"] == 2}
    found = {evidence[i]["fact"] for ranked in matches[:k] for i in ranked if evidence[i]["grade"] == 2}
    return len(found) / len(needed)


def ndcg(matches, evidence, k):
    """Ranking quality with graded relevance: gain = grade / log2(rank + 1), divided by the best possible ranking.

    Each evidence item is credited once and each chunk brings at most one: two overlapping chunks proving the same
    item don't count twice, so the score stays between 0 and 1.
    """
    credited, dcg = set(), 0.0
    for rank, ranked in enumerate(matches[:k], 1):
        new = [i for i in ranked if i not in credited]
        if new:
            best = max(new, key=lambda i: evidence[i]["grade"])
            credited.add(best)
            dcg += evidence[best]["grade"] / math.log2(rank + 1)
    ideal = sorted((e["grade"] for e in evidence), reverse=True)[:k]
    idcg = sum(grade / math.log2(rank + 1) for rank, grade in enumerate(ideal, 1))
    return dcg / idcg


METRICS = {"hit": hit, "mrr": mrr, "recall": recall, "ndcg": ndcg}


def retrieval_scores(chunks, question, top_k):
    """The retrieval scores of one question, as {metric: value} (e.g. "recall@5").

    hit/mrr/recall/ndcg: questions with evidence (not out_of_corpus).
    trap_hit@k: questions with traps; 1 if a trap is in the top k. Lower is better.
    """
    scores = {}
    ks = [k for k in K_VALUES if k <= top_k]
    if question["evidence"]:
        matches = [judge_chunk(chunk, question) for chunk in chunks]
        scores |= {f"{name}@{k}": metric(matches, question["evidence"], k) for k in ks for name, metric in METRICS.items()}
    if question.get("traps"):
        traps = [is_trap(chunk, question) for chunk in chunks]
        scores |= {f"trap_hit@{k}": float(any(traps[:k])) for k in ks}
    return scores


# ---------------------------------------------------------------------------------------------------
# Redundancy: how much the top k chunks repeat each other (duplicates, three-language press releases,
# newsletters recalling the CODIR). Same measure as exercise 3, without the per-patient scope.
# ---------------------------------------------------------------------------------------------------
REDUNDANCY_K = (5, 10)
NEAR_DUPLICATE = 0.8    # Jaccard above which a chunk counts as a near-duplicate of an earlier one
SHINGLE_SIZE = 3        # words per shingle


def chunk_body(text):
    """The chunk's own text, without its context line ('[PV du CODIR du 13 octobre 2025 · …]').

    Without this, every chunk of one document would look alike through their shared first line.
    """
    lines = text.splitlines()
    if lines and lines[0].startswith("[") and lines[0].rstrip().endswith("]"):
        lines = lines[1:]
    return "\n".join(lines)


def shingles(text):
    """The set of SHINGLE_SIZE-word groups of a text (lowercase, normalised); the words themselves if it's shorter."""
    words = normalize(text).casefold().split()
    if len(words) < SHINGLE_SIZE:
        return set(words)
    return {" ".join(words[i:i + SHINGLE_SIZE]) for i in range(len(words) - SHINGLE_SIZE + 1)}


def jaccard(a, b):
    """|a ∩ b| / |a ∪ b| of two shingle sets; 0 for two empty sets."""
    return len(a & b) / len(a | b) if a or b else 0.0


def redundancy_scores(chunks, top_k):
    """For every k of REDUNDANCY_K <= top_k:

    redundancy@k = mean Jaccard of the chunk bodies over all pairs of the top k;
    near_duplicates@k = number of chunks with Jaccard >= NEAR_DUPLICATE to an earlier chunk;
    documents@k = number of distinct documents.
    """
    bodies = [shingles(chunk_body(chunk["text"])) for chunk in chunks]
    scores = {}
    for k in REDUNDANCY_K:
        if k > top_k:
            continue
        n = min(k, len(chunks))
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
        scores[f"redundancy@{k}"] = sum(jaccard(bodies[i], bodies[j]) for i, j in pairs) / len(pairs) if pairs else 0.0
        scores[f"near_duplicates@{k}"] = float(sum(
            any(jaccard(bodies[i], bodies[j]) >= NEAR_DUPLICATE for i in range(j)) for j in range(n)))
        scores[f"documents@{k}"] = float(len({chunk["document"] for chunk in chunks[:n]}))
    return scores


# ---------------------------------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------------------------------
def is_refusal(answer):
    """The system prompt asks for this exact sentence when the passages do not answer the question."""
    return "je ne sais pas" in answer.lower()


def cited_passages(answer):
    """Numbers of the passages cited in the answer, written like [2]."""
    return {int(number) for number in re.findall(r"\[(\d+)\]", answer)}


def answer_scores(answer, chunks, question):
    """Deterministic answer checks.

    refusal (every question) = 1 if the answer is a refusal: its mean is the right-refusal rate on out_of_corpus
    questions and the wrong-refusal rate on the others. Only reliable with prompts that impose the sentence.
    When the answer cites passages ([2]): citation_valid = share of cited numbers that exist (1..number of chunks),
    citation_relevant = share of the existing cited chunks that prove part of the answer (judge_chunk, any grade).
    """
    scores = {"refusal": float(is_refusal(answer))}
    cited = cited_passages(answer)
    if cited:
        existing = [n for n in cited if 1 <= n <= len(chunks)]
        scores["citation_valid"] = len(existing) / len(cited)
        if existing and question["evidence"]:
            scores["citation_relevant"] = sum(bool(judge_chunk(chunks[n - 1], question)) for n in existing) / len(existing)
    return scores
