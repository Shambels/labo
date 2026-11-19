"""The quiz as a game: every question of QUIZ.md, multiple-choice versions of the long ones, and a code & pipeline
phase with ordering and matching questions. XP, levels, streaks, badges, a score per phase, a redo of what you
missed, and a map of the app coloured by what you know.

    uv run streamlit run app/quiz.py --server.port 8503      # no server needed: it reads QUIZ.md and quiz/*.yaml

Progress is saved after every answer in data/quiz/progress.json (QUIZ_PROGRESS to use another file).
"""
import collections
import datetime as dt
import os

import altair as alt
import pandas as pd
import streamlit as st

from labo_quiz import engine
from labo_quiz.engine import MODES, PHASES, Progress, badges, grade, level, match_details, pick, stats

st.set_page_config(page_title="Calorvia quiz", page_icon="🎓", layout="wide")

# Colours: phases take the categorical slots in fixed order (always with their letter and name beside them);
# mastery uses the status colours, always with its percentage and an icon.
DARK = getattr(st.context.theme, "type", None) == "dark"
PHASE_COLOR = dict(zip(PHASES, ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9"] if DARK
                       else ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]))
STATUS = {"good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b", "none": "#d9d8d3"}
KIND = {"open": "✍️ open", "choice": "🔘 one answer", "multi": "☑️ several answers", "order": "🔢 put in order",
        "match": "🔗 match"}
RESULT = {"right": "✅", "partial": "🟡", "wrong": "❌"}
NODES = {  # the pipeline map: id -> (label, cluster)
    "inventory": ("Inventory\nregistry, duplicates, dates", "Indexing"),
    "conversion": ("Reading\nDocling · openpyxl · VLM", "Indexing"),
    "chunking": ("Chunking\ncontext line · Markdown tables", "Indexing"),
    "index": ("Index\nQdrant dense + BM25 · roles", "Indexing"),
    "search": ("Search\nhybrid RRF · filters", "A RAG question"),
    "rerank": ("Rerank\n+ translation on demand", "A RAG question"),
    "generation": ("Generation\nQwen · workbook SQL", "A RAG question"),
    "endpoint": ("Endpoint /v1\n3 models · streaming", "The agent"),
    "agent_graph": ("Agent graph\nLangGraph · budgets · footer", "The agent"),
    "grounding": ("Grounding check\nevery figure has a source", "The agent"),
    "mcp": ("MCP server\n7 tools · role token", "The databases"),
    "validation": ("Validation & execution\nsqlglot · privacy · log", "The databases"),
    "sources": ("Sources\nERP · compta · paie", "The databases"),
    "access": ("Access\nroles · logins · RLS · links", "Across the app"),
    "evaluation": ("Evaluation\nmetrics · judge · runs", "Across the app"),
}
EDGES = [("inventory", "conversion", ""), ("conversion", "chunking", ""), ("chunking", "index", ""),
         ("index", "search", ""), ("search", "rerank", "30"), ("rerank", "generation", "5"),
         ("endpoint", "search", "calorvia-docs"), ("endpoint", "agent_graph", "sql / both"),
         ("agent_graph", "search", "search_documents"), ("agent_graph", "grounding", ""),
         ("agent_graph", "mcp", "tool calls"), ("mcp", "validation", ""), ("validation", "sources", "read-only"),
         ("access", "mcp", "login per role"), ("access", "search", "allowed_roles"),
         ("evaluation", "generation", "measures"), ("evaluation", "agent_graph", "measures")]


@st.cache_data(ttl=30)
def questions():
    return engine.load_questions()


def load_progress():
    return Progress(os.environ.get("QUIZ_PROGRESS", engine.PROGRESS))


QUESTIONS = questions()
BY_ID = {q.id: q for q in QUESTIONS}
progress = load_progress()
state = st.session_state
for key, default in {"queue": [], "pos": 0, "results": {}, "feedback": None, "revealed": False,
                     "game_xp": 0, "game_name": ""}.items():
    state.setdefault(key, default)


def chip(text, color):
    return (f"<span style='border:1.5px solid {color};border-radius:999px;padding:1px 10px;margin-right:6px;"
            f"font-size:0.85em;white-space:nowrap'><span style='color:{color}'>●</span> {text}</span>")


def mastery_status(s):
    """Green when mastered (every question tried, >= 80 % right); otherwise by the share right among those tried, so
    one miss out of ten untried questions reads "started badly", not "failed"."""
    if not s["seen"]:
        return "none", "○"
    if s.get("mastered"):
        return "good", "✔"
    return ("warning", "◐") if s["right"] / s["seen"] >= 0.5 else ("critical", "✖")


def start(ids, name):
    state.update(queue=list(ids), pos=0, results={}, feedback=None, revealed=False, game_xp=0, game_name=name)
    for key in [k for k in state if str(k).startswith("w-")]:   # widgets of a previous game
        del state[key]


# --- sidebar: the player card --------------------------------------------------------------------------------------
with st.sidebar:
    number, name, into, span = level(progress.xp)
    st.markdown(f"## 🎓 Level {number}\n### {name}")
    st.progress(into / span if span else 1.0, text=f"{progress.xp} XP" + (f" · {span - into} to next level" if span else " · top level"))
    c1, c2 = st.columns(2)
    c1.metric("Streak", f"🔥 {progress.streak}", help=f"best: {progress.best_streak}; +10 XP every 5 in a row")
    answered = sum(1 for s in progress.questions.values() if s["best"] == "right")
    c2.metric("Known", f"{answered}/{len(QUESTIONS)}", help="questions answered right at least once")
    earned = badges(QUESTIONS, progress)
    st.markdown("**Badges**")
    st.markdown(" ".join(f"<span title='{b} — {how}' style='font-size:1.6em'>{icon}</span>" for icon, b, how in earned)
                if earned else "_none yet: answer a question right_", unsafe_allow_html=True)
    with st.expander("How scoring works"):
        st.markdown("- ✅ first try **10 XP**, ✅ after a miss **5**, 🟡 partly **3**, ❌ **0**\n"
                    "- XP only when a question's best result improves: replays earn nothing\n"
                    "- **+10 XP** every 5 right answers in a row\n"
                    "- a phase is 🏅 **mastered** when every question was tried and ≥ 80 % are right\n"
                    "- open questions are graded by you, honestly: the redo mode brings back 🟡 and ❌")

play, mapping, stats_tab = st.tabs(["🎮 Play", "🗺️ Pipeline map", "📊 Progress"])


# --- play ---------------------------------------------------------------------------------------------------------
def phase_cards():
    by_phase = stats(QUESTIONS, progress, lambda q: q.phase)
    columns = st.columns(len(PHASES))
    for column, (phase, (title, _, _)) in zip(columns, PHASES.items()):
        s = by_phase[phase]
        status, icon = mastery_status(s)
        failed = s["wrong"] + s["partial"]
        with column.container(border=True):
            st.markdown(chip(f"<b>{phase}</b>", PHASE_COLOR[phase]) + ("🏅" if s["mastered"] else ""),
                        unsafe_allow_html=True)
            st.markdown(f"**{title}**")
            st.progress(s["mastery"], text=f"{icon} {s['right']}/{s['total']} right")
            st.caption(f"{s['seen']} tried · {failed} to redo")
            new = [q.id for q in pick(QUESTIONS, progress, "new", phases=[phase], shuffle_seed=dt.datetime.now().microsecond)]
            if st.button("▶ Play 10", key=f"play-{phase}", disabled=not new, width="stretch"):
                start(new[:10], f"Phase {phase}: new questions")
                st.rerun()
            redo = [q.id for q in pick(QUESTIONS, progress, "failed", phases=[phase])]
            if st.button(f"🔁 Redo {len(redo)}", key=f"redo-{phase}", disabled=not redo, width="stretch"):
                start(redo, f"Phase {phase}: redo")
                st.rerun()


def game_builder():
    with st.container(border=True):
        st.markdown("#### 🎲 Build a game")
        c1, c2, c3 = st.columns([2, 3, 2])
        failed_count = len(pick(QUESTIONS, progress, "failed"))
        mode = c1.radio("Questions", list(MODES), format_func=lambda m: MODES[m] + (f" ({failed_count})" if m == "failed" else ""),
                        key="b-mode")
        phases = c2.multiselect("Phases", list(PHASES), default=list(PHASES), key="b-phases",
                                format_func=lambda p: f"{p} · {PHASES[p][0]}")
        kinds = c3.multiselect("Kinds", ["open", "choice", "interactive"], default=["open", "choice", "interactive"],
                               key="b-kinds", help="interactive: put in order, match, several answers")
        count = st.slider("How many", 5, 40, 10, key="b-count")
        pool = [q for q in pick(QUESTIONS, progress, mode, phases=phases, shuffle_seed=dt.datetime.now().microsecond)
                if ("interactive" if q.kind in ("order", "match", "multi") else q.kind) in kinds]
        if st.button(f"Start ({min(count, len(pool))} of {len(pool)})", key="start", type="primary", disabled=not pool):
            start([q.id for q in pool[:count]], MODES[mode])
            st.rerun()


def header(q):
    st.markdown(chip(f"<b>{q.phase}</b> · {PHASES[q.phase][0]}", PHASE_COLOR[q.phase])
                + chip(q.title if q.phase != "G" else NODES.get(q.node, (q.node,))[0].split("\n")[0], "#8a8a85")
                + chip(KIND[q.kind] if not typing(q) else KIND["open"], "#8a8a85"), unsafe_allow_html=True)
    st.markdown(f"### {q.prompt}")
    if q.code:
        st.code(q.code, language="python")


def typing(q):
    return q.kind == "open" or (q.can_type and state.get(f"w-type-{q.id}", False))


def submit(q, result, response=None):
    before = {b[1] for b in badges(QUESTIONS, progress)}
    earned = progress.record(q.id, result)
    after = badges(QUESTIONS, progress)
    state.results[q.id] = result
    state.game_xp += earned
    state.feedback = {"result": result, "earned": earned, "response": response,
                      "new_badges": [b for b in after if b[1] not in before]}
    st.rerun()


def ask(q):
    """The answer widgets of one question; submitting records the result."""
    key = f"w-{q.id}"
    if q.can_type:
        st.toggle("✍️ Answer in my own words instead", key=f"w-type-{q.id}")
    if typing(q):
        st.text_area("Your answer (for you: you'll compare it with the model answer)", key=f"{key}-text", height=120)
        if not state.revealed:
            if st.button("👀 Reveal the answer", type="primary", key=f"{key}-reveal"):
                state.revealed = True
                st.rerun()
            return
        with st.container(border=True):
            st.markdown("**Model answer**")
            st.markdown(q.explain if q.kind == "open" else q.correct[0])
            if q.kind != "open":
                with st.expander("The full answer of QUIZ.md"):
                    st.markdown(q.explain)
        st.markdown("**How did you do?**")
        c1, c2, c3 = st.columns(3)
        if c1.button("✅ Got it", key=f"{key}-right", width="stretch"):
            submit(q, "right")
        if c2.button("🟡 Partly", key=f"{key}-partial", width="stretch"):
            submit(q, "partial")
        if c3.button("❌ Missed it", key=f"{key}-wrong", width="stretch"):
            submit(q, "wrong")
        return
    if q.kind == "choice":
        choice = st.radio("Choose one", q.options(), index=None, key=f"{key}-choice", label_visibility="collapsed")
        if st.button("Check", type="primary", disabled=choice is None, key=f"{key}-check"):
            submit(q, grade(q, choice), choice)
    elif q.kind == "multi":
        st.caption("Tick every right answer, and only those.")
        chosen = [option for option in q.options() if st.checkbox(option, key=f"{key}-{option}")]
        if st.button("Check", type="primary", disabled=not chosen, key=f"{key}-check"):
            submit(q, grade(q, chosen), chosen)
    elif q.kind == "order":
        st.caption("Click the steps in the order they happen; remove one with its ✕ to change your mind.")
        order = st.multiselect("Your order", engine.shuffled(q.correct, q.id), key=f"{key}-order",
                               placeholder="1st step…")
        for i, step in enumerate(order, 1):
            st.markdown(f"**{i}.** {step}")
        if st.button("Check", type="primary", disabled=len(order) != len(q.correct), key=f"{key}-check"):
            submit(q, grade(q, order), order)
    elif q.kind == "match":
        rights = q.rights()
        answer = {}
        for left, _ in q.pairs:
            c1, c2 = st.columns([2, 3])
            c1.markdown(f"**{left}**")
            answer[left] = c2.selectbox(left, rights, index=None, key=f"{key}-{left}", label_visibility="collapsed",
                                        placeholder="matches…")
        if st.button("Check", type="primary", disabled=None in answer.values(), key=f"{key}-check"):
            submit(q, grade(q, answer), answer)


def feedback(q):
    f = state.feedback
    result = f["result"]
    if result == "right":
        st.success(f"### ✅ Right!  +{f['earned']} XP" + (f"  ·  🔥 {progress.streak} in a row" if progress.streak > 1 else ""))
    elif result == "partial":
        st.warning(f"### 🟡 Partly  +{f['earned']} XP — it comes back in **Redo failed**")
    else:
        st.error("### ❌ Not this time — it comes back in **Redo failed**")
    response = f["response"]
    if q.kind == "choice" and response is not None:
        for option in q.options():
            mark = "✅" if option == q.correct[0] else ("❌" if option == response else "▫️")
            st.markdown(f"{mark} {option}")
    elif q.kind == "multi":
        for option in q.options():
            right, picked = option in q.correct, option in response
            st.markdown(f"{'✅' if right == picked else '❌'} {'☑' if picked else '☐'} {option}"
                        + ("" if right == picked else ("  ← should be ticked" if right else "  ← shouldn't be")))
    elif q.kind == "order":
        rows = [{"#": i, "your order": mine, "": "✅" if mine == right else "❌", "right order": right}
                for i, (mine, right) in enumerate(zip(response, q.correct), 1)]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    elif q.kind == "match":
        rows = [{"": "✅" if ok else "❌", "item": left, "you chose": chosen, "right answer": right}
                for left, chosen, right, ok in match_details(q, response)]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if q.kind != "open" and not typing(q):
        with st.container(border=True):
            st.markdown("**Why**")
            st.markdown(q.explain)
    if q.files:
        st.caption("Read more: " + " · ".join(f"`{path}`" for path in q.files))
    for icon, name, how in f["new_badges"]:
        st.toast(f"{icon} New badge: {name}", icon="🏆")
        st.balloons()
    if f["earned"]:
        st.toast(f"+{f['earned']} XP", icon="⭐")
    last = state.pos + 1 >= len(state.queue)
    if st.button("🏁 See the results" if last else "Next question ➜", type="primary", key="next"):
        state.update(pos=state.pos + 1, feedback=None, revealed=False)
        st.rerun()


def summary():
    results = state.results
    right = sum(1 for r in results.values() if r == "right")
    st.markdown(f"## 🏁 {state.game_name}: {right}/{len(results)} right")
    c1, c2, c3 = st.columns(3)
    c1.metric("Score", f"{right / len(results):.0%}" if results else "–")
    c2.metric("XP won", f"+{state.game_xp}")
    c3.metric("Streak", f"🔥 {progress.streak}")
    if results and right == len(results):
        st.balloons()
    rows = [{"": RESULT[r], "question": BY_ID[qid].prompt, "phase": BY_ID[qid].phase, "step": BY_ID[qid].title}
            for qid, r in results.items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    missed = [qid for qid, r in results.items() if r != "right"]
    c1, c2 = st.columns(2)
    if c1.button(f"🔁 Redo the {len(missed)} I missed", disabled=not missed, type="primary", key="redo-game"):
        start(missed, "Redo of the last game")
        st.rerun()
    if c2.button("🎲 New game", key="new-game"):
        start([], "")
        st.rerun()


with play:
    if not state.queue:
        phase_cards()
        game_builder()
    elif state.pos >= len(state.queue):
        summary()
    else:
        q = BY_ID[state.queue[state.pos]]
        done = len(state.results)
        right = sum(1 for r in state.results.values() if r == "right")
        top1, top2 = st.columns([4, 1])
        top1.progress(state.pos / len(state.queue),
                      text=f"{state.game_name} · question {state.pos + 1}/{len(state.queue)} · {right}/{done} right · +{state.game_xp} XP")
        if top2.button("✖ Quit game", key="quit"):
            start([], "")
            st.rerun()
        with st.container(border=True):
            header(q)
            if state.feedback is None:
                ask(q)
            else:
                feedback(q)


# --- the pipeline map -------------------------------------------------------------------------------------------
with mapping:
    by_node = stats(QUESTIONS, progress, lambda q: q.node)
    st.markdown("How well you know each part of the app: every question belongs to a part. "
                "**✔ mastered** (all tried, ≥ 80 % right) · **◐** going well: half or more of the tried ones right · "
                "**✖** most tried ones missed · **○** not tried yet. The numbers are right / questions.")
    lines = ["digraph app {", 'rankdir=LR; bgcolor="transparent"; nodesep=0.35; ranksep=0.5;',
             'node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=11 margin="0.15,0.08"];',
             f'edge [color="#8a8a85" fontname="Helvetica" fontsize=9 fontcolor="{"#c3c2b7" if DARK else "#52514e"}"];']
    for cluster in dict.fromkeys(c for _, c in NODES.values()):
        lines.append(f'subgraph "cluster_{cluster}" {{ label="{cluster}"; fontname="Helvetica"; fontsize=12; '
                     f'fontcolor="{"#c3c2b7" if DARK else "#52514e"}"; style="rounded,dashed"; color="#8a8a85";')
        for node, (label, c) in NODES.items():
            if c != cluster:
                continue
            s = by_node.get(node, {"seen": 0, "total": 0, "right": 0, "mastery": 0})
            status, icon = mastery_status(s)
            font = "#ffffff" if status == "critical" else "#0b0b0b"
            text = label.replace("\n", "\\n") + f"\\n{icon} {s['right']}/{s['total']} right · {s['seen']} tried"
            lines.append(f'"{node}" [label="{text}" fillcolor="{STATUS[status]}" fontcolor="{font}" color="{STATUS[status]}"];')
        lines.append("}")
    for a, b, label in EDGES:
        dashed = ' style="dashed"' if a in ("access", "evaluation") else ""
        lines.append(f'"{a}" -> "{b}" [label="{label}"{dashed}];')
    lines.append("}")
    st.graphviz_chart("\n".join(lines), width="stretch")
    c1, c2 = st.columns([3, 2])
    node = c1.selectbox("Practice a part", list(NODES), format_func=lambda n: NODES[n][0].replace("\n", " — "),
                        key="map-node")
    s = by_node.get(node, {"total": 0, "seen": 0, "right": 0})
    todo = [q.id for q in QUESTIONS if q.node == node and (progress.state(q.id) or {}).get("last") != "right"]
    c2.metric("Still to get right", f"{len(todo)}/{s['total']}")
    if st.button(f"▶ Practice this part ({len(todo)} questions)", disabled=not todo, key="practice", type="primary"):
        start(engine.shuffled(todo, dt.datetime.now().microsecond), f"Practice: {NODES[node][0].splitlines()[0]}")
        st.rerun()
    st.caption("Switch to 🎮 Play to answer them.")


# --- progress -------------------------------------------------------------------------------------------------
with stats_tab:
    by_phase = stats(QUESTIONS, progress, lambda q: q.phase)
    table = pd.DataFrame([{"phase": f"{p} · {PHASES[p][0]}", "mastery": s["mastery"], "right": s["right"],
                           "partly": s["partial"], "missed": s["wrong"], "not tried": s["total"] - s["seen"],
                           "questions": s["total"], "badge": "🏅" if s["mastered"] else ""}
                          for p, s in ((p, by_phase[p]) for p in PHASES)])
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "mastery": st.column_config.ProgressColumn("mastery", format="percent", min_value=0, max_value=1)})
    color = "#3987e5" if DARK else "#2a78d6"
    st.altair_chart(
        alt.Chart(table).mark_bar(color=color, cornerRadiusEnd=4)
        .encode(x=alt.X("mastery:Q", title="share of questions answered right", scale=alt.Scale(domain=[0, 1]),
                        axis=alt.Axis(format="%")),
                y=alt.Y("phase:N", sort=None, title=None, axis=alt.Axis(labelLimit=260)),
                tooltip=["phase", alt.Tooltip("mastery:Q", format=".0%"), "right", "questions"])
        .properties(height=alt.Step(30), autosize=alt.AutoSizeParams(type="fit-x", contains="padding")),
        width="stretch")
    if progress.history:
        st.markdown("#### Activity")
        days = collections.Counter((h["at"][:10], h["result"]) for h in progress.history)
        activity = pd.DataFrame([{"day": d, "result": {"right": "right", "partial": "partly", "wrong": "missed"}[r], "answers": n}
                                 for (d, r), n in sorted(days.items())])
        st.altair_chart(
            alt.Chart(activity).mark_bar()
            .encode(x=alt.X("day:O", title=None), y=alt.Y("answers:Q", title="answers"),
                    color=alt.Color("result:N", title=None, sort=["right", "partly", "missed"],
                                    scale=alt.Scale(domain=["right", "partly", "missed"],
                                                    range=[STATUS["good"], STATUS["warning"], STATUS["critical"]])),
                    order=alt.Order("result:N", sort="descending"),
                    tooltip=["day", "result", "answers"])
            .properties(height=220, autosize=alt.AutoSizeParams(type="fit-x", contains="padding")),
            width="stretch")
        recent = [{"when": h["at"].replace("T", " "), "": RESULT[h["result"]], "question": BY_ID[h["id"]].prompt[:110],
                   "XP": h["xp"]} for h in reversed(progress.history[-15:]) if h["id"] in BY_ID]
        st.dataframe(pd.DataFrame(recent), hide_index=True, width="stretch")
    with st.expander("Reset my progress"):
        sure = st.checkbox("Yes, erase my XP, results and badges", key="reset-sure")
        if st.button("Reset", disabled=not sure, key="reset"):
            progress.reset()
            start([], "")
            st.rerun()
