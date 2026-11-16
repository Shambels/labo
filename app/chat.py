"""Chat with the Calorvia RAG: the answer, its sources, the images it relies on, and the SQL it ran.

    uv run streamlit run app/chat.py          # needs the embedder, the reranker and the generator

The configuration is the final one (experiments/time_rules.toml); another can be chosen in the sidebar.
"""
import tomllib
from pathlib import Path

import streamlit as st

from rag_calorvia.rag.images import answer_images, image_bytes
from rag_calorvia.rag.pipeline import answer

st.set_page_config(page_title="Assistant Calorvia", page_icon="💬", layout="wide")

configs = sorted(Path("experiments").glob("*.toml"))
default = next((i for i, p in enumerate(configs) if p.stem == "time_rules"), 0)
config_path = st.sidebar.selectbox("Configuration", configs, index=default, format_func=lambda p: p.stem)
with open(config_path, "rb") as f:
    config = tomllib.load(f)
st.sidebar.caption("Les extraits, les images et les requêtes SQL sont affichés sous chaque réponse : "
                   "vérifiez une valeur lue dans une image avant de la réutiliser.")

st.title("Assistant documentaire Calorvia")

if "history" not in st.session_state:
    st.session_state.history = []


def show(turn):
    """One question and its answer, with the sources, the cited images and the SQL queries."""
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        result = turn["result"]
        st.write(result["answer"])
        for path, page in answer_images(result["answer"], result["context"]):
            caption = path + (f", page {page + 1}" if page is not None else "")
            st.image(image_bytes(path, page), caption=caption)
        with st.expander(f"Extraits ({len(result['context'])}) · {result['latency_ms'] / 1000:.1f} s"):
            for n, chunk in enumerate(result["context"], 1):
                score = f" · pertinence {chunk['rerank_score']:.2f}" if "rerank_score" in chunk else ""
                st.markdown(f"**[{n}]** `{chunk['document']}` · {chunk.get('doc_date') or 'sans date'}{score}")
                st.text(chunk["text"][:1200])
        if result.get("tool_calls"):
            with st.expander(f"Calculs ({len(result['tool_calls'])} appels d'outils)"):
                for call in result["tool_calls"]:
                    st.code(f"{call['tool']}({call['arguments']})\n→ {call['result']}", language="text")


for turn in st.session_state.history:
    show(turn)

if question := st.chat_input("Votre question sur les documents de Calorvia"):
    with st.spinner("Recherche et rédaction de la réponse…"):
        turn = {"question": question, "result": answer(question, config)}
    st.session_state.history.append(turn)
    show(turn)
