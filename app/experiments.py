"""Compare experiment runs: the RAG's (scores per question type or format, judged metrics) and the text-to-SQL agent's
(right answers per category), the questions that changed, and the settings that differ.

    uv run streamlit run app/experiments.py      # needs only the course PostgreSQL (5432)

The numbers are those of scripts/report.py and scripts/t2sql_report.py (same functions, same tables). Stored answers
quote extracts of every document: in local mode the page is open on 127.0.0.1 (.streamlit/config.toml); with
API_KEYS set it asks for a key whose role is `direction` or `it`.
"""
import tomllib

import altair as alt
import pandas as pd
import psycopg
import streamlit as st

from rag_calorvia import db
from rag_calorvia.config import settings as rag_settings
from rag_calorvia.evaluation import compare
from rag_calorvia.evaluation.dataset import align_with_registry, load_questions
from rag_calorvia.rag.permissions import identify

ADMIN_ROLES = {"direction", "it"}
st.set_page_config(page_title="Calorvia experiments", page_icon="📊", layout="wide")


# --- access -----------------------------------------------------------------------------------------------------------
if "identity" not in st.session_state:
    st.session_state.identity = identify("")       # (None, None) in local mode
identity = st.session_state.identity
if identity is None or (identity[1] is not None and identity[1] not in ADMIN_ROLES):
    st.title("Calorvia experiments")
    if identity is not None:
        st.error("This page is for the `direction` and `it` roles: stored answers quote every document.")
    with st.form("login"):
        key = st.text_input("Access key", type="password")
        if st.form_submit_button("Enter"):
            st.session_state.identity = identify(key)
            st.rerun()
    st.stop()


# --- data (cached a minute: new runs appear without restarting) -----------------------------------------------------
@st.cache_data(ttl=60)
def rag_runs():
    with db.connect(read_only=True) as conn:
        return compare.rag_runs(conn)


@st.cache_data(ttl=60)
def rag_scores(run_ids):
    with db.connect(read_only=True) as conn:
        return compare.rag_scores(conn, run_ids)


@st.cache_data(ttl=600)
def rag_configs(run_ids):
    with db.connect(read_only=True) as conn:
        return compare.rag_configs(conn, run_ids)


@st.cache_data(ttl=600)
def rag_answers(run_id):
    with db.connect(read_only=True) as conn:
        return db.load_answers(conn, run_id)


@st.cache_data(ttl=3600)
def rag_questions(split):
    with db.connect(read_only=True) as conn:
        registry = db.load_registry(conn)
    return align_with_registry(load_questions(split, allow_test=split == "test"), registry), registry


@st.cache_data(ttl=60)
def t2sql_data(kind, run_ids=()):
    from text2sql_calorvia.config import settings
    with psycopg.connect(settings.postgres_url) as conn:
        if kind == "runs":
            return compare.t2sql_runs(conn)
        if kind == "categories":
            return compare.t2sql_categories(conn, run_ids)
        if kind == "results":
            return compare.t2sql_results(conn, run_ids)
        return compare.t2sql_configs(conn, run_ids)


@st.cache_data(ttl=3600)
def t2sql_questions():
    from text2sql_calorvia.evaluation import load_final_questions, load_questions as t2sql_load
    questions = t2sql_load(split="all")
    try:
        questions += load_final_questions()
    except (OSError, ValueError):
        pass
    return {q["id"]: q for q in questions}


def in_use_name():
    with open(rag_settings.final_config, "rb") as f:
        return tomllib.load(f)["name"]


def bar_chart(rows, metric):
    """One metric's overall value per run: horizontal bars, one series, a tooltip per bar."""
    dark = getattr(st.context.theme, "type", None) == "dark"
    data = pd.DataFrame(rows)
    return (alt.Chart(data).mark_bar(color="#3987e5" if dark else "#2a78d6", cornerRadiusEnd=4, height=14)
            .encode(x=alt.X("value:Q", title=metric, scale=alt.Scale(zero=True)),
                    y=alt.Y("run:N", sort=None, title=None),
                    tooltip=["run", alt.Tooltip("value:Q", format=".3f"), "n"])
            .properties(height=36 * len(rows) + 20))


# --- RAG --------------------------------------------------------------------------------------------------------------
def rag_page():
    runs = rag_runs()
    using = in_use_name()
    c1, c2, c3 = st.columns([1, 1, 2])
    split = c1.radio("Question set", ["dev", "test"], horizontal=True,
                     help="test: the held-out questions, run once at the end (step 9)")
    kinds = c2.multiselect("Runs", ["retrieval only", "with answers"], default=["retrieval only", "with answers"])
    dirty = c3.checkbox("Include runs on uncommitted code", help="Left out of every report: not reproducible")
    pool = [r for r in runs if r["split"] == split and (dirty or not r["git_dirty"])
            and (("with answers" in kinds and r["generation"]) or ("retrieval only" in kinds and not r["generation"]))]
    label = {r["id"]: f"{r['id']} · {r['name']}" + (" ★ in use" if r["name"].removesuffix("__retrieval") == using else "")
             for r in pool}
    latest = {}
    for r in pool:
        latest[r["name"]] = r["id"]
    defaults = [latest[n] for n in ("status_filter__retrieval", f"{using}__retrieval") if n in latest]
    chosen = st.multiselect("Compare", list(reversed(list(label))), default=defaults, format_func=label.get,
                            help="Newest first. ★ marks the configuration in use (settings.final_config).")
    with st.expander(f"All {len(pool)} runs"):
        st.dataframe(pd.DataFrame(pool), hide_index=True, width="stretch")
    if not chosen:
        st.info("Choose at least one run.")
        return

    chosen = tuple(chosen)
    scores = {label[r]: s for r, s in rag_scores(chosen).items()}
    questions, registry = rag_questions(split)
    available = sorted({m for s in scores.values() for per_q in s.values() for m in per_q})
    preferred = [m for m in compare.RETRIEVAL_METRICS[:2] + ["correctness"] if m in available]
    c1, c2, c3 = st.columns([3, 1, 2])
    metrics = c1.multiselect("Metrics", available, default=preferred)
    by = c2.radio("By", ["type", "format", "all"], horizontal=False)
    same = c3.checkbox("Only questions scored in every run", value=True,
                       help="Judged metrics were computed on different question sets: compare the same questions")

    tab_metrics, tab_questions, tab_config = st.tabs(["Metrics", "Questions that changed", "Settings that differ"])
    with tab_metrics:
        for metric in metrics:
            qs = questions
            if same:
                common = set.intersection(*({q for q, m in s.items() if m.get(metric) is not None}
                                            for s in scores.values()))
                qs = [q for q in questions if q["id"] in common]
            rows = compare.metric_table(scores, qs, registry, metric, by)
            runs_ = list(scores)
            arrow = "lower is better" if metric in compare.LOWER_IS_BETTER else "higher is better"
            st.subheader(f"{metric}")
            st.caption(f"{arrow} · mean over the questions that have the metric, their number in brackets · "
                       "▲ best of the row")
            table = []
            for row in rows:
                best = compare.best_run(row, runs_, metric)
                table.append({"group": row["group"], **{
                    run: "–" if row[run] is None else f"{row[run]:.3f} ({row[f'{run} n']})" + (" ▲" if run == best else "")
                    for run in runs_}})
            st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
            total = rows[-1]
            bars = [{"run": run, "value": total[run], "n": total[f"{run} n"]} for run in runs_ if total[run] is not None]
            if len(bars) > 1:
                st.altair_chart(bar_chart(bars, f"{metric}, all questions"), width="stretch")

    with tab_questions:
        if len(scores) < 2:
            st.info("Choose two runs or more.")
        else:
            metric = st.selectbox("Metric", metrics or available, key="diff_metric")
            diffs = compare.question_diffs(scores, metric, questions)
            st.caption(f"{len(diffs)} questions where {metric} differs between the runs")
            st.dataframe(pd.DataFrame(diffs), hide_index=True, width="stretch")
            if diffs:
                show_rag_question(st.selectbox("Read a question", [d["question"] for d in diffs]), questions, chosen,
                                  label)

    with tab_config:
        diff = compare.config_diff({label[r]: c for r, c in rag_configs(chosen).items()})
        if diff:
            st.dataframe(pd.DataFrame(diff), hide_index=True, width="stretch")
        else:
            st.info("Same settings." if len(chosen) > 1 else "Choose two runs or more.")


def show_rag_question(qid, questions, chosen, label):
    question = next(q for q in questions if q["id"] == qid)
    st.markdown(f"**{qid}** ({question['type']}) · {question['question']}")
    st.markdown(f"*Expected:* {question['answer']}")
    st.caption("Evidence: " + ", ".join(f"`{e['document']}`" for e in question.get("evidence", [])))
    for run_id, column in zip(chosen, st.columns(len(chosen))):
        chunks, answer = rag_answers(run_id).get(qid, ([], None))
        with column:
            st.markdown(f"**{label[run_id]}**")
            if answer:
                st.write(answer)
            for n, chunk in enumerate(chunks or [], 1):
                st.caption(f"[{n}] {chunk['document']} · {chunk.get('rerank_score', 0):.3f}")


# --- text-to-SQL --------------------------------------------------------------------------------------------------
def t2sql_page():
    runs = t2sql_data("runs")
    c1, c2 = st.columns(2)
    split = c1.radio("Question set", sorted({r["split"] for r in runs}), horizontal=True)
    dirty = c2.checkbox("Include runs on uncommitted code", key="t2sql_dirty")
    pool = [r for r in runs if r["split"] == split and (dirty or not r["git_dirty"])]
    label = {r["id"]: f"{r['id']} · {r['name']}" + (f" ({r['role']})" if r["role"] else "") for r in pool}
    clean = [r["id"] for r in pool if not r["role"]]
    chosen = st.multiselect("Compare", list(reversed(list(label))), default=clean[-2:], format_func=label.get,
                            key="t2sql_runs")
    with st.expander(f"All {len(pool)} runs"):
        st.dataframe(pd.DataFrame(pool), hide_index=True, width="stretch")
    if not chosen:
        st.info("Choose at least one run.")
        return
    chosen = tuple(chosen)
    tab_categories, tab_questions, tab_config = st.tabs(["Per category", "Questions that changed", "Settings that differ"])
    with tab_categories:
        rows = t2sql_data("categories", chosen)
        st.caption("right answers / questions, and how many were confidently wrong (a wrong figure presented as right)")
        st.dataframe(pd.DataFrame([{"category": r["category"], **{
            label[run]: f"{r.get(run, '–')} · {r.get(f'{run} wrong', 0)} wrong" for run in chosen}} for r in rows]),
            hide_index=True, width="stretch")
        bars = [{"run": label[r["id"]], "value": r["ok"] / r["questions"], "n": r["questions"]}
                for r in pool if r["id"] in chosen]
        if len(bars) > 1:
            st.altair_chart(bar_chart(bars, "share of right answers"), width="stretch")
    with tab_questions:
        results = t2sql_data("results", chosen)
        diffs = compare.t2sql_diffs(results)
        st.caption(f"{len(diffs)} questions right in some runs and wrong in others")
        st.dataframe(pd.DataFrame([{"question": d["question"], "category": d["category"],
                                    **{label[run]: d.get(run, "") for run in chosen}} for d in diffs]),
                     hide_index=True, width="stretch")
        if diffs:
            qid = st.selectbox("Read a question", [d["question"] for d in diffs], key="t2sql_question")
            question = t2sql_questions().get(qid, {})
            st.markdown(f"**{qid}** · {question.get('question', '')}")
            st.markdown(f"*Expected:* {question.get('expected', question.get('behavior', ''))}")
            for run, column in zip(chosen, st.columns(len(chosen))):
                r = results[run].get(qid)
                with column:
                    st.markdown(f"**{label[run]}**")
                    if r:
                        st.caption(f"{'right' if r['ok'] else 'wrong'} · judged {r['label']} · {r['queries']} queries · "
                                   f"{r['seconds']:.0f} s" + (f" · missing {r['missing']}" if r["missing"] else ""))
                        st.markdown(r["answer"])
    with tab_config:
        diff = compare.config_diff({label[r]: c for r, c in t2sql_data("configs", chosen).items()})
        if diff:
            st.dataframe(pd.DataFrame(diff), hide_index=True, width="stretch")
        else:
            st.info("Same settings." if len(chosen) > 1 else "Choose two runs or more.")


st.title("Calorvia experiments")
st.caption(f"RAG configuration in use: `{rag_settings.final_config}` (settings.final_config, FINAL_CONFIG in .env)")
rag_tab, t2sql_tab = st.tabs(["RAG", "Text-to-SQL agent"])
with rag_tab:
    rag_page()
with t2sql_tab:
    t2sql_page()
