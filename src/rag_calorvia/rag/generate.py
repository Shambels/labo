"""Generation: question + reranked chunks -> answer, with the system prompt and the [generation] settings."""
import logging
from functools import cache
from pathlib import Path
from types import SimpleNamespace

from openai import OpenAI
from openai.types.chat import ChatCompletionMessage

from rag_calorvia.config import settings

logger = logging.getLogger(__name__)


@cache
def get_llm():
    return OpenAI(base_url=settings.llm_url, api_key="EMPTY")  # llama-server started without --api-key


def load_system_prompt(config):
    """The text of the system prompt file. The runner stores it with the experiment: files change, results must not.

    [generation] corpus (step 41): a description of the corpus (sites, the label line, versions, series, and which
    details go with an answer from each kind of document) added after the rules. Step 41's analysis of the misses:
    45 of 50 lost answers on dev and 19 of 19 on the fresh set had the evidence in the context and stopped at the core
    fact; rule 4 says which details to add in general, the description says it per kind of document."""
    text = Path(config["generation"]["system_prompt"]).read_text(encoding="utf-8").strip()
    corpus = config["generation"].get("corpus")
    return f"{text}\n\n{Path(corpus).read_text(encoding='utf-8').strip()}" if corpus else text


def format_passages(chunks):
    """Numbered extracts, best first: [1] ... [2] ... The numbers are what the prompt asks the LLM to cite."""
    return "\n\n".join(f"[{i}] {chunk['text']}" for i, chunk in enumerate(chunks, 1))


def build_messages(question, chunks, config):
    """System prompt = how to answer; user message = the extracts, then the question last, closest to the answer."""
    return [
        {"role": "system", "content": load_system_prompt(config)},
        {"role": "user", "content": f"Extraits :\n\n{format_passages(chunks)}\n\nQuestion : {question}"},
    ]


MAX_TOOL_ROUNDS = 5  # rounds of tool calls before the LLM must answer with what it has
# Said before the last round (step 39): with tool_choice "none" alone, Qwen3.8 can still write a call as text (Q017).
LAST_ROUND = ("Tu ne peux plus appeler d'outil. Réponds maintenant à la question à partir des extraits "
              "et des résultats déjà obtenus.")
RAW_CALL = ("<tool_call>", "<function=")  # a tool call written in the answer's text instead of as a call


def raw_tool_call(text):
    """True when the answer is a tool call written as text, which the user must never see as an answer."""
    return any(marker in (text or "") for marker in RAW_CALL)


def uses_tools(config):
    """[tools] tables = true (step 6b): the LLM may query the workbooks' tables in SQL before answering."""
    return config.get("tools", {}).get("tables", False)


def streamed(stream, on_text):
    """One streamed completion read to the end (step 45): its text goes to on_text as it arrives; returned as the
    same (choice, usage) a plain call gives, so the tool loop does not know the difference."""
    text, calls, finish, usage = [], {}, None, None
    for chunk in stream:
        usage = chunk.usage or usage
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        finish = choice.finish_reason or finish
        if choice.delta.content:
            text.append(choice.delta.content)
            on_text(choice.delta.content)
        for call in choice.delta.tool_calls or []:   # a tool call arrives in pieces, by index
            slot = calls.setdefault(call.index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            slot["id"] = call.id or slot["id"]
            if call.function:
                slot["function"]["name"] += call.function.name or ""
                slot["function"]["arguments"] += call.function.arguments or ""
    message = ChatCompletionMessage(role="assistant", content="".join(text) or None,
                                    tool_calls=[calls[i] for i in sorted(calls)] or None)
    return SimpleNamespace(message=message, finish_reason=finish), usage


def generate(question, chunks, config, role=None, on_text=None):
    """The LLM's answer, with token counts and the tool calls it made (none without [tools]).

    With tools, the conversation loops: the LLM asks for tool calls, gets their results, and so on, up to
    MAX_TOOL_ROUNDS; then it must answer. No seed: at temperature > 0, repeated runs must be able to differ.

    on_text (step 45): every call is streamed and its text given to on_text as it is written; on_text(None) says the
    text given so far was not the answer (the round ended in tool calls, or in a tool call written as text). Without
    it, nothing changes: the evaluation calls generate() as before.
    """
    params = config["generation"]
    messages = build_messages(question, chunks, config)
    tools, store = None, None
    if uses_tools(config):
        from rag_calorvia.rag.tables import TOOLS, call_tool, get_store  # the store is built only when needed
        tools, store = TOOLS, get_store(role)

    calls, prompt_tokens, completion_tokens = [], 0, 0
    def complete(with_tools, tool_choice):
        nonlocal prompt_tokens, completion_tokens
        response = get_llm().chat.completions.create(
            model=params["model"],
            messages=messages,
            temperature=params["temperature"],
            top_p=params["top_p"],
            max_tokens=params["max_tokens"],
            extra_body={"top_k": params["top_k"]},  # llama-server parameter, not part of the OpenAI API
            **({"tools": tools, "tool_choice": tool_choice} if with_tools else {}),
            **({"stream": True, "stream_options": {"include_usage": True}} if on_text else {}),
        )
        choice, usage = streamed(response, on_text) if on_text else (response.choices[0], response.usage)
        if usage:
            prompt_tokens += usage.prompt_tokens
            completion_tokens += usage.completion_tokens
        return choice

    for round_ in range(MAX_TOOL_ROUNDS + 1):
        last = round_ == MAX_TOOL_ROUNDS
        if last and tools:
            messages.append({"role": "user", "content": LAST_ROUND})
        choice = complete(bool(tools), "none" if last else "auto")
        if tools and raw_tool_call(choice.message.content) and not choice.message.tool_calls:
            # Asked once more, without the tools: the call written as text is never shown as the answer.
            logger.warning("tool call written as text, asked again without tools: %s", question)
            if on_text:
                on_text(None)
            messages.append({"role": "assistant", "content": choice.message.content})
            messages.append({"role": "user", "content": LAST_ROUND})
            choice = complete(False, None)
            break
        if not choice.message.tool_calls or last:
            break
        if on_text:
            on_text(None)
        messages.append(choice.message.model_dump(exclude_none=True))
        for call in choice.message.tool_calls:
            result = call_tool(store, call.function.name, call.function.arguments)
            calls.append({"tool": call.function.name, "arguments": call.function.arguments, "result": result[:500]})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    if choice.finish_reason == "length":
        logger.warning("answer cut at max_tokens=%d: %s", params["max_tokens"], question)
    return {
        "answer": (choice.message.content or "").strip(),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "finish_reason": choice.finish_reason,
        "tool_calls": calls,
    }
