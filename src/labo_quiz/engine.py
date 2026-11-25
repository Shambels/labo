"""The quiz engine: the questions, how an answer is graded, and the player's progress.

Questions come from three files, so the quiz grows with the project without code changes:
- QUIZ.md: every step's open questions and their answers (the source of truth, written step by step);
- quiz/choices.yaml: a multiple-choice version of the questions whose answers are too long to type;
- quiz/code.yaml: phase Z, the code and the flow of the app (ordering, matching, single and multiple choice).

Progress is a JSON file (data/quiz/progress.json, git-ignored): each question's best and latest result, attempts,
the XP, the streak and the history. XP is only won when a question's best result improves, so replaying a known
question earns nothing; a right answer on the first attempt is worth more than after a miss.
"""
import datetime as dt
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
QUIZ_MD = ROOT / "QUIZ.md"
CHOICES = ROOT / "quiz" / "choices.yaml"
CODE = ROOT / "quiz" / "code.yaml"
PROGRESS = ROOT / "data" / "quiz" / "progress.json"

# Phases of ROADMAP.md, plus the code phase. Steps are inclusive ranges; the warm-up belongs to phase A.
PHASES = {
    "A": ("RAG", -1, 9), "B": ("Text-to-SQL agent", 10, 17), "C": ("Improvements", 18, 24),
    "D": ("Role-based access", 25, 29), "E": ("RAG experiments", 30, 30), "F": ("One chat", 31, 31),
    "G": ("Monitoring & conversations", 32, 33), "H": ("Fixing the judged errors", 34, 41),
    "I": ("What the agent knows and writes", 42, 44), "J": ("Speed", 45, 45),
    "Z": ("Code & pipeline", None, None),
}
CODE_PHASE = "Z"            # quiz/code.yaml's questions: about the app as it is, not about one step
# The part of the app each step is mostly about, for the pipeline map (None: about the project as a whole)
NODE_OF_STEP = {
    -1: None, 0: None, 1: "inventory", 2: "inventory", 3: "evaluation", 4: "generation", 5: "search",
    6: "conversion", 7: "conversion", 8: "search", 9: "evaluation", 10: "sources", 11: "mcp", 12: "agent_graph",
    13: "agent_graph", 14: "evaluation", 15: "endpoint", 16: "evaluation", 17: "validation", 18: "access",
    19: "evaluation", 20: "agent_graph", 21: "validation", 22: "grounding", 23: "evaluation", 24: "access",
    25: "access", 26: "access", 27: "access", 28: "index", 29: "access", 30: "rerank", 31: "endpoint",
    32: "monitoring",
    33: "conversations", 34: "chunking", 35: "conversion", 36: "rerank", 37: "conversion",
    38: "evaluation", 39: "generation", 45: "generation",
}
POINTS = {"right": 10, "partial": 3, "wrong": 0}
RETRY_POINTS = 5            # right after an earlier miss
STREAK_BONUS = (5, 10)      # every 5 right answers in a row: +10 XP
RANK = {"wrong": 0, "partial": 1, "right": 2}
LEVELS = [(0, "Stagiaire"), (100, "Analyste"), (300, "Data engineer"), (600, "Ingénieur RAG"),
          (1000, "Architecte d'agents"), (1500, "Gardien des rôles"), (2100, "Expert Calorvia"),
          (2800, "Maître Calorvia")]
MASTERY = 0.8               # a phase or a part of the app is mastered at 80 % right, every question tried


@dataclass
class Question:
    id: str
    phase: str
    section: str                # warmup, step-04, code
    title: str                  # the section's title in QUIZ.md
    kind: str                   # open, choice, multi, order, match
    prompt: str
    explain: str                # the answer of QUIZ.md, or the explanation of a code question
    node: str | None = None
    correct: list[str] = field(default_factory=list)   # choice/multi: right options; order: the steps in order
    wrong: list[str] = field(default_factory=list)
    pairs: list[list[str]] = field(default_factory=list)
    code: str | None = None
    files: list[str] = field(default_factory=list)

    @property
    def can_type(self):
        """A multiple-choice version of a QUIZ.md question can also be answered in one's own words."""
        return self.section != "code" and self.kind == "choice"

    def options(self):
        """choice/multi: every option, shuffled the same way each time for this question."""
        return shuffled(self.correct + self.wrong, self.id)

    def rights(self):
        """match: the right-hand sides, shuffled."""
        return shuffled([right for _, right in self.pairs], self.id)


def shuffled(items, seed):
    out = list(items)
    random.Random(seed).shuffle(out)
    return out


# --- loading ------------------------------------------------------------------------------------------------------
SECTION = re.compile(r"^## (.+)$", re.M)
QUESTION = re.compile(r"\*\*(\d+[a-z]?)\.\*\* (.*?)\n\n<details><summary>Answer</summary>\n\n(.*?)\n</details>", re.S)


def step_of(title):
    if title.lower().startswith("warm-up"):
        return -1
    m = re.match(r"Step (\d+)", title)
    return int(m.group(1)) if m else None


def section_id(step):
    return "warmup" if step == -1 else f"step-{step:02d}"


def phase_of(step):
    return next(p for p, (_, lo, hi) in PHASES.items() if lo is not None and lo <= step <= hi)


def load_questions(quiz_md=QUIZ_MD, choices=CHOICES, code=CODE):
    """Every question of the game: QUIZ.md (open, or multiple choice when choices.yaml has a version), then code."""
    overlays = yaml.safe_load(Path(choices).read_text(encoding="utf-8")) or {} if Path(choices).exists() else {}
    text = Path(quiz_md).read_text(encoding="utf-8")
    heads = list(SECTION.finditer(text))
    questions = []
    for i, head in enumerate(heads):
        title, step = head.group(1).strip(), step_of(head.group(1).strip())
        if step is None:
            continue
        body = text[head.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        for number, prompt, answer in QUESTION.findall(body):
            qid = f"{section_id(step)}-q{number}"
            overlay = overlays.get(qid)
            questions.append(Question(
                id=qid, phase=phase_of(step), section=section_id(step), title=title,
                kind="choice" if overlay else "open", prompt=" ".join(prompt.split()), explain=answer.strip(),
                node=NODE_OF_STEP.get(step), correct=[overlay["correct"]] if overlay else [],
                wrong=list(overlay["wrong"]) if overlay else []))
    if Path(code).exists():
        for q in yaml.safe_load(Path(code).read_text(encoding="utf-8"))["questions"]:
            correct = q.get("steps") or q.get("correct") or []
            questions.append(Question(
                id=q["id"], phase=CODE_PHASE, section="code", title="Code & pipeline", kind=q["type"],
                prompt=q["prompt"], explain=q["explain"], node=q["node"],
                correct=[correct] if isinstance(correct, str) else list(correct), wrong=list(q.get("wrong", [])),
                pairs=[list(p) for p in q.get("pairs", [])], code=q.get("code"), files=list(q.get("files", []))))
    return questions


# --- grading ------------------------------------------------------------------------------------------------------
def grade(question, response):
    """'right' or 'wrong' for an automatically graded answer.

    choice: the option chosen; multi: the set chosen; order: the steps in the order clicked;
    match: {left: right chosen}. An open question is graded by the player (right, partial, wrong)."""
    kind = question.kind
    if kind == "choice":
        ok = response == question.correct[0]
    elif kind == "multi":
        ok = set(response or []) == set(question.correct)
    elif kind == "order":
        ok = list(response or []) == question.correct
    elif kind == "match":
        ok = all((response or {}).get(left) == right for left, right in question.pairs)
    else:
        raise ValueError(f"{question.id} is graded by the player")
    return "right" if ok else "wrong"


def match_details(question, response):
    """[(left, chosen, right answer, is it right)] for showing a matching answer."""
    return [(left, (response or {}).get(left), right, (response or {}).get(left) == right)
            for left, right in question.pairs]


# --- progress -----------------------------------------------------------------------------------------------------
class Progress:
    """The player's saved state. Everything is written at each answer: closing the page loses nothing."""

    def __init__(self, path=PROGRESS):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.questions = data.get("questions", {})   # id -> {best, last, attempts, last_at}
        self.xp = data.get("xp", 0)
        self.streak = data.get("streak", 0)
        self.best_streak = data.get("best_streak", 0)
        self.history = data.get("history", [])       # [{at, id, result, xp}]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"questions": self.questions, "xp": self.xp, "streak": self.streak,
                                   "best_streak": self.best_streak, "history": self.history},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def state(self, qid):
        return self.questions.get(qid)

    def record(self, qid, result, now=None):
        """Store an answer and return the XP it earned (0 unless the question's best result improves)."""
        now = now or dt.datetime.now().isoformat(timespec="seconds")
        before = self.questions.get(qid)
        attempts = before["attempts"] if before else 0
        best = before["best"] if before else None
        earned = 0
        if best is None or RANK[result] > RANK[best]:
            points = RETRY_POINTS if result == "right" and attempts > 0 and best != "right" else POINTS[result]
            earned = max(0, points - (POINTS[best] if best and best != "right" else 0))
            best = result
        self.streak = self.streak + 1 if result == "right" else 0
        self.best_streak = max(self.best_streak, self.streak)
        if result == "right" and self.streak % STREAK_BONUS[0] == 0:
            earned += STREAK_BONUS[1]
        self.xp += earned
        self.questions[qid] = {"best": best, "last": result, "attempts": attempts + 1, "last_at": now}
        self.history.append({"at": now, "id": qid, "result": result, "xp": earned})
        self.save()
        return earned

    def reset(self):
        self.questions, self.xp, self.streak, self.best_streak, self.history = {}, 0, 0, 0, []
        self.save()


# --- what to play, and how far along -------------------------------------------------------------------------------
MODES = {"new": "New questions", "failed": "Redo failed", "all": "Everything"}


def pick(questions, progress, mode, phases=None, node=None, sections=None, shuffle_seed=None):
    """The questions of a game: never answered (new), last answered wrong or partly (failed), or all."""
    def keep(q):
        if phases and q.phase not in phases or node and q.node != node or sections and q.section not in sections:
            return False
        state = progress.state(q.id)
        if mode == "new":
            return state is None
        if mode == "failed":
            return state is not None and state["last"] != "right"
        return True
    chosen = [q for q in questions if keep(q)]
    return shuffled(chosen, shuffle_seed) if shuffle_seed is not None else chosen


def stats(questions, progress, key):
    """{group: {total, seen, right, partial, wrong, mastery}} where group = key(question); mastery = right / total."""
    out = {}
    for q in questions:
        group = key(q)
        if group is None:
            continue
        s = out.setdefault(group, {"total": 0, "seen": 0, "right": 0, "partial": 0, "wrong": 0})
        s["total"] += 1
        state = progress.state(q.id)
        if state:
            s["seen"] += 1
            s[state["last"]] += 1
    for s in out.values():
        s["mastery"] = s["right"] / s["total"] if s["total"] else 0.0
        s["mastered"] = s["seen"] == s["total"] and s["mastery"] >= MASTERY
    return out


def level(xp):
    """(number from 1, name, XP into this level, XP this level spans or None at the top)."""
    index = max(i for i, (threshold, _) in enumerate(LEVELS) if xp >= threshold)
    start = LEVELS[index][0]
    span = LEVELS[index + 1][0] - start if index + 1 < len(LEVELS) else None
    return index + 1, LEVELS[index][1], xp - start, span


def badges(questions, progress):
    """[(icon, name, how it was won)] of the badges earned so far."""
    earned = []
    if any(s["best"] == "right" for s in progress.questions.values()):
        earned.append(("🎯", "First right answer", "answer a question right"))
    for phase, s in stats(questions, progress, lambda q: q.phase).items():
        if s["mastered"]:
            earned.append(("🏅", f"Phase {phase} mastered", f"{PHASES[phase][0]}: every question tried, ≥ 80 % right"))
    by_section = stats(questions, progress, lambda q: q.section)
    perfect = [sec for sec, s in by_section.items() if s["right"] == s["total"]]
    if perfect:
        earned.append(("💯", f"Perfect section ×{len(perfect)}", "every question of a step right"))
    for threshold, icon in ((10, "🔥"), (25, "☄️")):
        if progress.best_streak >= threshold:
            earned.append((icon, f"Streak {threshold}", f"{threshold} right answers in a row"))
    redeemed = sum(1 for s in progress.questions.values() if s["best"] == "right" and s["attempts"] > 1)
    if redeemed >= 10:
        earned.append(("🔁", "Comeback ×10", "10 questions right after a miss"))
    code = [q for q in questions if q.phase == CODE_PHASE]
    if code and all(progress.state(q.id) for q in code):
        earned.append(("🗺️", "Pipeline explorer", "every code & pipeline question tried"))
    return earned
