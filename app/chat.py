"""Chat with Calorvia: the documents (the RAG), the databases (the agent), or both (step 31).

    uv run streamlit run app/chat.py          # documents: the embedder, the reranker and the generator
                                              # databases or both: also the MCP server and the agent's endpoint (9000)

"Documents" runs the RAG here, with its extracts, images and workbook SQL shown under each answer. "Bases de données"
and "Les deux" ask the agent's endpoint (models calorvia-sql and calorvia-both) with the same key: its answer carries
the queries that ran and the documents it cites.

Step 33: every conversation is kept (PostgreSQL, the endpoint's tables), whatever the mode: the sidebar lists them,
searches them, reopens one to go on, and shows the archives. Under the title, the current one can be renamed, archived
or restored, compacted (its earlier turns summarized for the agent) and exported as Markdown. The conversation id is
sent to the endpoint (X-Conversation-Id), so a conversation may mix the three modes.

The configuration is the final one (settings.final_config); another can be chosen in the sidebar.
With API_KEYS set, the chat asks for a key and answers only from the documents of the user's role (D77); the settings
of .streamlit/config.toml keep it on this machine otherwise.

Step 47: an admin (ADMIN_USERS, or anyone in local mode) may act as any role from the sidebar: the documents are those
of the role, the agent's endpoint gets X-Calorvia-Act-As (it checks the admin itself), and the conversations and memory
are the simulated role's own (alice#as:finance). Changing the role starts a new conversation.
"""
import tomllib
import uuid
from pathlib import Path

import psycopg
import requests
import streamlit as st
from openai import OpenAI, OpenAIError

from rag_calorvia.config import settings as rag_settings
from rag_calorvia.rag.images import answer_images, image_bytes
from rag_calorvia.rag.permissions import identify
from rag_calorvia.rag.pipeline import answer
from text2sql_calorvia import access, auth, conversations, memory, tracing
from text2sql_calorvia.config import settings as agent_settings

MODES = {"Documents": None, "Bases de données": "calorvia-sql", "Les deux": "calorvia-both"}
CONTEXT_KEYS = ("document", "doc_date", "text", "rerank_score", "image_path", "page")   # what show() reads of a chunk

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
me = user or "default"    # the key's name, or "default" in local mode, as at the endpoint
acting = None
if user is None or user in auth.names(agent_settings.admin_users):   # step 47: only an admin picks a role
    acting = st.sidebar.selectbox(
        "Agir en tant que", [None, *access.roles()], key="acting",
        format_func=lambda r: "— mon accès —" if r is None else r,
        help="Voir le chat comme un utilisateur de ce rôle : ses documents, ses bases, ses conversations.",
        on_change=lambda: st.session_state.update(history=[], conversation_id=f"st-{uuid.uuid4().hex}"))
role = acting or role
owner = auth.acting_user(me, acting)   # whose conversations: the simulated role has its own (step 47)

mode = st.sidebar.radio("Chercher dans", list(MODES), help="Documents : procédures, contrats, PV, tarifs... "
                        "Bases de données : ventes, comptabilité, paie. Les deux : l'agent choisit, et peut comparer.")
configs = sorted(Path("experiments").glob("*.toml"))
default = next((i for i, p in enumerate(configs) if p == rag_settings.final_config), 0)
if role is None and mode == "Documents":
    st.session_state.setdefault("config", configs[default])   # the widget's value, so the ★ button can set it
    pick, reset = st.sidebar.columns([5, 1], vertical_alignment="bottom")
    config_path = pick.selectbox(
        "Configuration", configs, key="config",
        format_func=lambda p: f"★ {p.stem} (par défaut)" if p == configs[default] else p.stem,
        help="★ : la configuration en usage, celle du chat par défaut et de l'endpoint "
             "(settings.final_config, FINAL_CONFIG dans .env).")
    reset.button("★", key="config-default", help="Revenir à la configuration par défaut",
                 disabled=config_path == configs[default],
                 on_click=lambda: st.session_state.update(config=configs[default]))
else:
    config_path = configs[default]
if acting:
    st.sidebar.warning(f"Vous agissez en tant que « {acting} » : réponses, sources et conversations de ce rôle.")
if user is not None:
    st.sidebar.write(f"Connecté : {user} ({st.session_state.identity[1]})")
    if st.sidebar.button("Se déconnecter"):
        st.session_state.clear()
        st.rerun()
with open(config_path, "rb") as f:
    config = tomllib.load(f)
st.sidebar.caption("Les extraits, les images et les requêtes SQL sont affichés sous chaque réponse : "
                   "vérifiez une valeur lue dans une image avant de la réutiliser.")


# --- conversations (step 33) ----------------------------------------------------------------------------------------
def new_conversation():
    st.session_state.history = []
    st.session_state.conversation_id = f"st-{uuid.uuid4().hex}"   # stored at its first turn


def turn_of(question: dict, reply: dict) -> dict:
    """A stored question and answer as a turn of this page: Documents turns kept their extracts in their step."""
    steps = reply.get("steps") or []
    docs = next((s for s in steps if s.get("mode") == "Documents"), None)
    if docs:
        return {"question": question["content"], "mode": "Documents",
                "result": {"answer": reply["content"], "context": docs.get("context", []),
                           "latency_ms": docs.get("latency_ms", 0), "tool_calls": docs.get("tool_calls", [])}}
    from text2sql_calorvia.api import with_fresh_links  # chart and image links renewed, as the endpoint's read route
    both = any(s.get("tool") == "search_documents" for s in steps)
    return {"question": question["content"], "mode": "Les deux" if both else "Bases de données",
            "result": {"answer": with_fresh_links(reply)["content"]}}


def open_conversation(conversation_id: str):
    stored = memory.conversation(conversation_id)
    pairs = zip(stored[0::2], stored[1::2])
    st.session_state.history = [turn_of(q, a) for q, a in pairs if q["role"] == "user" and a["role"] == "assistant"]
    st.session_state.conversation_id = conversation_id


if "history" not in st.session_state:
    new_conversation()

st.sidebar.divider()
st.sidebar.subheader("Conversations")
if st.sidebar.button("➕ Nouvelle conversation", width="stretch"):
    new_conversation()
    st.rerun()
search = st.sidebar.text_input("Rechercher", placeholder="un mot du titre ou des messages")
show_archives = st.sidebar.toggle("Archives", help="Les conversations archivées : rouvrez-en une pour la restaurer.")
try:
    listed = memory.conversations(owner, 30, show_archives, search)
except psycopg.Error:
    listed = None
    st.sidebar.caption("Historique indisponible : PostgreSQL (5432) ne répond pas.")
if listed == [] and (search or show_archives):
    st.sidebar.caption("Aucune conversation.")
for c in listed or []:
    current = c["id"] == st.session_state.conversation_id
    label = ("▶ " if current else "") + c["title"][:60]
    if st.sidebar.button(label, key=f"open-{c['id']}", width="stretch", disabled=current,
                         help=f"{c['updated_at'][:16].replace('T', ' ')} · {c['messages']} messages"
                              + (" · compactée" if c["compacted"] else "")):
        open_conversation(c["id"])
        st.rerun()

st.title("Assistant Calorvia")


def manage(conversation_id: str):
    """Rename, archive or restore, compact, export: the current conversation, once it is stored."""
    try:
        info = memory.conversation_info(conversation_id)
    except psycopg.Error:
        return
    if not info or info["user"] != owner:
        return
    stored = memory.conversation(conversation_id)
    with st.expander(f"⚙️ {info['title']}" + (" · archivée" if info["archived"] else ""), expanded=False):
        c1, c2 = st.columns([3, 1])
        title = c1.text_input("Titre", value=info["title"], key=f"title-{conversation_id}")
        if c2.button("Renommer", width="stretch", disabled=title.strip() in ("", info["title"])):
            memory.rename(conversation_id, owner, title)
            st.rerun()
        c1, c2, c3 = st.columns(3)
        if info["archived"]:
            if c1.button("Restaurer", width="stretch"):
                memory.archive(conversation_id, owner, False)
                st.rerun()
        elif c1.button("Archiver", width="stretch", help="Cachée de la liste, rien n'est effacé ; voir « Archives »."):
            memory.archive(conversation_id, owner, True)
            new_conversation()
            st.rerun()
        tokens = conversations.estimated_tokens(stored)
        if c2.button("Compacter", width="stretch",
                     help=f"Résume les échanges sauf les {conversations.KEEP_TURNS} derniers : l'agent lira le résumé à "
                          f"leur place. Historique : ~{tokens:,} jetons sur {agent_settings.context_tokens:,}.".replace(",", " ")):
            with st.spinner("Résumé des échanges précédents…"):
                try:
                    done = conversations.compact(conversation_id, owner)
                    st.success(f"{done['summary_messages']} messages résumés ; {done['kept_messages']} gardés tels quels.")
                except (ValueError, OpenAIError) as error:
                    st.warning(str(error) if isinstance(error, ValueError) else
                               f"Le modèle ne répond pas ({type(error).__name__}) : lancez le générateur sur 8000.")
            info = memory.conversation_info(conversation_id)
        c3.download_button("Exporter (.md)", conversations.export_markdown(conversation_id, owner),
                           file_name=f"{conversation_id}.md", mime="text/markdown", width="stretch")
        st.caption(f"Historique relu par l'agent : ~{tokens:,} jetons (contexte : {agent_settings.context_tokens:,})."
                   .replace(",", " "))
        if info["summary"]:
            st.markdown(f"**Résumé lu par l'agent à la place des {info['summary_messages']} premiers messages** "
                        f"(compactée le {info['compacted_at'][:16].replace('T', ' ')}) :")
            st.markdown(info["summary"])


manage(st.session_state.conversation_id)


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
    """The RAG, run here: traced like the endpoint's calorvia-docs (step 32), the conversation id as Langfuse session;
    the turn saved like the endpoint's, its extracts in its step so it can be shown again (step 33)."""
    with tracing.trace("calorvia-docs", question=question, user=owner, session_id=st.session_state.conversation_id,
                       tags=["streamlit", config_path.stem]) as trace:
        result = answer(question, config, role)
        trace.update(output=result["answer"], metadata={"extracts": [c["document"] for c in result["context"]],
                                                        "latency_ms": result["latency_ms"]})
    step = {"tool": "search_documents", "args": {"query": question}, "ok": True, "mode": "Documents",
            "context": [{k: c[k] for k in CONTEXT_KEYS if k in c} for c in result["context"]],
            "latency_ms": result["latency_ms"], "tool_calls": result.get("tool_calls", [])}
    try:
        memory.save_turn(st.session_state.conversation_id, owner, question, result["answer"], [step])
    except psycopg.Error as error:   # keeping the history must never cost the user the answer
        st.warning(f"Conversation non enregistrée ({type(error).__name__}).")
    return result


def ask_agent(question, model):
    """The agent's endpoint, with the conversation so far, under this conversation's id (it saves the turn)."""
    client = OpenAI(base_url=f"http://{agent_settings.agent_host}:{agent_settings.agent_port}/v1",
                    api_key=st.session_state.get("key") or "local", timeout=600)
    messages = [m for t in st.session_state.history
                for m in ({"role": "user", "content": t["question"]}, {"role": "assistant", "content": t["result"]["answer"]})]
    headers = {"X-Conversation-Id": st.session_state.conversation_id, **({"X-Calorvia-Act-As": acting} if acting else {})}
    reply = client.chat.completions.create(model=model, messages=messages + [{"role": "user", "content": question}],
                                           user=me, extra_headers=headers)   # the endpoint adds the role to the owner
    return {"answer": conversations.MARKER.sub("", reply.choices[0].message.content)}   # the header names it


MODEL_SERVERS = {rag_settings.llm_url: "le générateur", rag_settings.embeddings_url: "l'embedder",
                 rag_settings.rerank_url: "le reranker"}


def documents_error(error: Exception) -> str:
    """What to start when the RAG, run here, fails: the model server the failed request went to, from its URL."""
    request = getattr(error, "request", None)
    url = str(request.url) if request is not None else ""
    server = next((f"{name} ({base})" for base, name in MODEL_SERVERS.items() if url.startswith(base)), None)
    if server:
        return f"Le serveur de modèle ne répond pas ({type(error).__name__}) : lancez {server}."
    return (f"Un serveur de modèle ne répond pas ({type(error).__name__}{f', {url}' if url else ''}) : vérifiez le "
            "générateur (8000), l'embedder (8001) et le reranker (8002).")


if question := st.chat_input("Votre question sur Calorvia"):
    with st.spinner("Recherche et rédaction de la réponse…"):
        try:
            result = ask_documents(question) if MODES[mode] is None else ask_agent(question, MODES[mode])
        except (OpenAIError, requests.RequestException) as error:
            if MODES[mode] is None:   # the RAG runs here: only the model servers, never the MCP server or 9000
                st.error(documents_error(error))
            else:
                st.error(f"L'agent ne répond pas ({type(error).__name__}) : lancez le serveur MCP (9001), "
                         "`uv run python -m text2sql_calorvia.api` (9000) et le générateur (8000).")
            st.stop()
    turn = {"question": question, "result": result, "mode": mode}
    st.session_state.history.append(turn)
    st.rerun()   # the sidebar lists the conversation once its first turn is stored
