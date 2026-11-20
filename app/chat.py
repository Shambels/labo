"""Chat with Calorvia: the documents (the RAG), the databases (the agent), or both (step 31).

    uv run streamlit run app/chat.py          # documents: the embedder, the reranker and the generator
                                              # databases or both: also the MCP server and the agent's endpoint (9000)

"Documents" runs the RAG here, with its extracts, images and workbook SQL shown under each answer. "Bases de données"
and "Les deux" ask the agent's endpoint (models calorvia-sql and calorvia-both) with the same key: its answer carries
the queries that ran and the documents it cites.

The configuration is the final one (settings.final_config); another can be chosen in the sidebar.
With API_KEYS set, the chat asks for a key and answers only from the documents of the user's role (D77); the settings
of .streamlit/config.toml keep it on this machine otherwise.
"""
import tomllib
import uuid
from pathlib import Path

import streamlit as st
from openai import OpenAI, OpenAIError

from rag_calorvia.config import settings as rag_settings
from rag_calorvia.rag.images import answer_images, image_bytes
from rag_calorvia.rag.permissions import identify
from rag_calorvia.rag.pipeline import answer
from text2sql_calorvia import tracing
from text2sql_calorvia.config import settings as agent_settings

MODES = {"Documents": None, "Bases de données": "calorvia-sql", "Les deux": "calorvia-both"}

st.set_page_config(page_title="Assistant Calorvia", page_icon="💬", layout="wide")

if "identity" not in st.session_state:
    st.session_state.identity = identify("")     # (None, None) in local mode; None until a key is accepted
if st.session_state.identity is None:
    st.title("Assistant documentaire Calorvia")
    with st.form("login"):
        key = st.text_input("Clé d'accès", type="password")
        if st.form_submit_button("Entrer"):
            st.session_state.identity, st.session_state.key = identify(key), key
            if st.session_state.identity is None:
                st.error("Clé invalide.")
            else:
                st.rerun()
    st.stop()
user, role = st.session_state.identity

mode = st.sidebar.radio("Chercher dans", list(MODES), help="Documents : procédures, contrats, PV, tarifs... "
                        "Bases de données : ventes, comptabilité, paie. Les deux : l'agent choisit, et peut comparer.")
configs = sorted(Path("experiments").glob("*.toml"))
default = next((i for i, p in enumerate(configs) if p == rag_settings.final_config), 0)
if role is None and mode == "Documents":
    config_path = st.sidebar.selectbox("Configuration", configs, index=default, format_func=lambda p: p.stem)
else:
    config_path = configs[default]
if role is not None:
    st.sidebar.write(f"Connecté : {user} ({role})")
    if st.sidebar.button("Se déconnecter"):
        st.session_state.clear()
        st.rerun()
with open(config_path, "rb") as f:
    config = tomllib.load(f)
st.sidebar.caption("Les extraits, les images et les requêtes SQL sont affichés sous chaque réponse : "
                   "vérifiez une valeur lue dans une image avant de la réutiliser.")

st.title("Assistant Calorvia")

if "history" not in st.session_state:
    st.session_state.history = []
    st.session_state.session_id = f"streamlit-{uuid.uuid4().hex}"   # groups this chat's traces in Langfuse (step 32)


def show(turn):
    """One question and its answer, with the sources, the cited images and the SQL queries."""
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        result = turn["result"]
        if turn.get("mode", "Documents") != "Documents":
            st.caption(turn["mode"])
            st.markdown(result["answer"])    # the endpoint's Markdown: queries, cited documents, charts and images
            return
        st.write(result["answer"])
        for path, page in answer_images(result["answer"], result["context"]):
            caption = path + (f", page {page + 1}" if page is not None else "")
            st.image(image_bytes(path, page, role=role), caption=caption)
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

def ask_documents(question):
    """The RAG, run here; traced like the endpoint's calorvia-docs (the other modes are traced by the endpoint)."""
    with tracing.trace("calorvia-docs", question=question, user=user or "default",
                       session_id=st.session_state.session_id, tags=["streamlit", config_path.stem]) as trace:
        result = answer(question, config, role)
        trace.update(output=result["answer"], metadata={"extracts": [c["document"] for c in result["context"]],
                                                        "latency_ms": result["latency_ms"]})
    return result


def ask_agent(question, model):
    """The agent's endpoint, with the conversation so far (an earlier answer carries the conversation's id)."""
    client = OpenAI(base_url=f"http://{agent_settings.agent_host}:{agent_settings.agent_port}/v1",
                    api_key=st.session_state.get("key") or "local", timeout=600)
    messages = [m for t in st.session_state.history
                for m in ({"role": "user", "content": t["question"]}, {"role": "assistant", "content": t["result"]["answer"]})]
    reply = client.chat.completions.create(model=model, messages=messages + [{"role": "user", "content": question}])
    return {"answer": reply.choices[0].message.content}


if question := st.chat_input("Votre question sur Calorvia"):
    with st.spinner("Recherche et rédaction de la réponse…"):
        try:
            result = ask_documents(question) if MODES[mode] is None else ask_agent(question, MODES[mode])
        except OpenAIError as error:
            st.error(f"L'agent ne répond pas ({type(error).__name__}) : lancez le serveur MCP et "
                     "`uv run python -m text2sql_calorvia.api`.")
            st.stop()
    turn = {"question": question, "result": result, "mode": mode}
    st.session_state.history.append(turn)
    show(turn)
