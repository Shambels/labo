"""Managing conversations (step 33): export, and compaction of the earlier turns.

Storage and the other actions (list, search, rename, archive, restore) are in memory.py; the endpoint's routes and the
Streamlit sidebar both call these functions.

**Compaction.** A long conversation fills the agent's 32k context: every earlier answer is sent again with each
question. Compacting asks the LLM for a summary of the earlier turns (questions, figures, the SQL behind them) and
stores it; the messages themselves stay, shown and exported in full. When the endpoint is asked the next question,
the turns the summary covers are replaced by it in what the agent reads (`with_summary`); the last `KEEP_TURNS` turns
stay word for word, since a follow-up question ("et pour avril ?") is about them.

A summary is model output that will be read as conversation history, and the grounding check accepts the
conversation's numbers as evidence (D54). So it is checked like an answer: every number of the summary (from 1 000
up) must be in the turns it summarizes. The model gets one more try; if a figure is still unfound, nothing is stored.
"""
import re
from pathlib import Path

from text2sql_calorvia import charts, documents, memory
from text2sql_calorvia.config import settings

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "compact.txt"
KEEP_TURNS = 2                      # turns (question + answer) kept word for word after the summary
SUMMARY_QUESTION = "Résume nos échanges précédents."
SUMMARY_HEAD = "Résumé des échanges précédents de cette conversation (compactés) :\n\n"
DETAILS = re.compile(r"<details>.*?</details>\s*", re.S)
MARKER = re.compile(r"\s*<!-- calorvia:conversation=[\w-]+ -->")


class NotFound(LookupError):
    """No such conversation for this user (the same answer whether it exists for someone else or not at all)."""


def owned(conversation_id: str, user: str) -> dict:
    info = memory.conversation_info(conversation_id)
    if info is None or info["user"] != user:
        raise NotFound(conversation_id)
    return info


def clean(text: str) -> str:
    """A stored message without what only a live client uses: step fold-outs, the id marker, expiring image links."""
    return documents.without_images(charts.without_images(MARKER.sub("", DETAILS.sub("", text)))).strip()


# --- export ---------------------------------------------------------------------------------------------------------
def export_markdown(conversation_id: str, user: str) -> str:
    """The whole conversation as Markdown: every message, the queries under each answer; charts and images, whose
    links expire, are named instead of shown."""
    info = owned(conversation_id, user)
    lines = [f"# {info['title']}", "",
             f"Conversation `{conversation_id}` · commencée le {info['created_at'][:16].replace('T', ' ')} · "
             f"dernière activité le {info['updated_at'][:16].replace('T', ' ')}"
             + (" · archivée" if info["archived"] else ""), ""]
    if info["summary"]:
        lines += [(f"> Compactée le {info['compacted_at'][:16].replace('T', ' ')} : les {info['summary_messages']} "
                   "premiers messages sont lus par l'agent sous la forme du résumé en fin de document."), ""]
    for m in memory.conversation(conversation_id):
        drawn = [s.get("args", {}).get("title") for s in m.get("steps") or [] if s.get("tool") == "make_chart" and s.get("ok")]
        who = "Vous" if m["role"] == "user" else "Assistant"
        lines += [f"## {who} · {m['created_at'][:16].replace('T', ' ')}", "", clean(m["content"]), ""]
        lines += [f"*Graphique : {t}*" for t in drawn if t] + ([""] if drawn else [])
    if info["summary"]:
        lines += ["---", "", "## Résumé utilisé par l'agent", "", info["summary"], ""]
    return "\n".join(lines)


# --- compaction -----------------------------------------------------------------------------------------------------
def transcript(messages: list[dict], previous_summary: str | None = None) -> str:
    """The turns to summarize, as the summarizer reads them: an earlier summary first, then each message; answers
    keep their queries as a note (the agent's own view of an earlier answer)."""
    from text2sql_calorvia.agent import previous_answer
    parts = [f"Résumé précédent :\n{previous_summary}"] if previous_summary else []
    for m in messages:
        if m["role"] == "user":
            parts.append(f"Utilisateur : {m['content']}")
        else:
            parts.append(f"Assistant : {previous_answer(clean(m['content']))}")
    return "\n\n".join(parts)


def llm_summary(text: str, note: str | None = None) -> str:
    """The generator's summary of a transcript (8000, the agent's model)."""
    from openai import OpenAI
    client = OpenAI(base_url=settings.llm_url, api_key="local", timeout=300)
    messages = [{"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
                {"role": "user", "content": f"Conversation à résumer :\n\n{text}"}]
    if note:
        messages.append({"role": "user", "content": note})
    reply = client.chat.completions.create(model=settings.llm_model, messages=messages, temperature=0, max_tokens=1500)
    return (reply.choices[0].message.content or "").strip()


def compact(conversation_id: str, user: str, keep_turns: int = KEEP_TURNS, summarize=None) -> dict:
    """Summarize every turn but the last `keep_turns` (and fold in an earlier summary). Returns the summary, how many
    messages it covers, and how many stay word for word. ValueError when there is nothing new to compact or when the
    summary keeps a figure the conversation doesn't have."""
    from text2sql_calorvia.agent import ungrounded
    summarize = summarize or llm_summary
    info = owned(conversation_id, user)
    messages = memory.conversation(conversation_id)
    cut = max(len(messages) - 2 * max(keep_turns, 0), 0)
    cut -= cut % 2                     # turns are saved in pairs: never cut between a question and its answer
    done = info["summary_messages"] if info["summary"] else 0
    if cut <= done:
        raise ValueError(f"Rien à compacter : il faut plus de {keep_turns} échange(s) après "
                         f"{'le dernier résumé' if done else 'le début de la conversation'}.")
    text = transcript(messages[done:cut], info["summary"] if done else None)
    summary = summarize(text)
    missing = ungrounded(summary, text)
    if missing:
        summary = summarize(text, f"Ces chiffres de votre résumé ne figurent pas dans la conversation : "
                                  f"{', '.join(missing)}. Recopiez chaque chiffre exactement, ou retirez-le.")
        missing = ungrounded(summary, text)
    if missing or not summary:
        raise ValueError(("Compaction annulée : le résumé contient des chiffres absents de la conversation ("
                          + ", ".join(missing) + ").") if missing else "Compaction annulée : résumé vide.")
    memory.set_summary(conversation_id, user, summary, cut)
    return {"summary": summary, "summary_messages": cut, "kept_messages": len(messages) - cut}


def with_summary(history: list[dict], info: dict | None, stored: list[dict]) -> list[dict]:
    """The client's history for the agent, its compacted turns replaced by the summary. Only when the history is the
    stored conversation (same questions, in order) and goes past what the summary covers; otherwise unchanged (a
    client that edited or cut its history keeps it as it is)."""
    if not info or not info.get("summary"):
        return history
    n = info["summary_messages"]
    if len(history) <= n or len(stored) < n:
        return history
    asked = [m["content"] for m in history[:n] if m["role"] == "user"]
    if asked != [m["content"] for m in stored[:n] if m["role"] == "user"]:
        return history
    return [{"role": "user", "content": SUMMARY_QUESTION},
            {"role": "assistant", "content": SUMMARY_HEAD + info["summary"]}] + history[n:]


def estimated_tokens(messages: list[dict]) -> int:
    """About how many tokens the history weighs for the agent (3 characters a token, as agent.fit counts)."""
    return sum(len(clean(m["content"])) for m in messages) // 3
