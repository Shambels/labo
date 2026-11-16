"""Generation: question + reranked chunks -> answer, with the system prompt and the [generation] settings."""
import logging
from functools import cache
from pathlib import Path

from openai import OpenAI

from rag_calorvia.config import settings

logger = logging.getLogger(__name__)


@cache
def get_llm():
    return OpenAI(base_url=settings.llm_url, api_key="EMPTY")  # llama-server started without --api-key


def load_system_prompt(config):
    """The text of the system prompt file. The runner stores it with the experiment: files change, results must not."""
    return Path(config["generation"]["system_prompt"]).read_text(encoding="utf-8").strip()


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


def uses_tools(config):
    """[tools] tables = true (step 6b): the LLM may query the workbooks' tables in SQL before answering."""
    return config.get("tools", {}).get("tables", False)


def generate(question, chunks, config):
    """The LLM's answer, with token counts and the tool calls it made (none without [tools]).

    With tools, the conversation loops: the LLM asks for tool calls, gets their results, and so on, up to
    MAX_TOOL_ROUNDS; then it must answer. No seed: at temperature > 0, repeated runs must be able to differ.
    """
    params = config["generation"]
    messages = build_messages(question, chunks, config)
    tools, store = None, None
    if uses_tools(config):
        from rag_calorvia.rag.tables import TOOLS, call_tool, get_store  # the store is built only when needed
        tools, store = TOOLS, get_store()

    calls, prompt_tokens, completion_tokens = [], 0, 0
    for round_ in range(MAX_TOOL_ROUNDS + 1):
        last = round_ == MAX_TOOL_ROUNDS
        response = get_llm().chat.completions.create(
            model=params["model"],
            messages=messages,
            temperature=params["temperature"],
            top_p=params["top_p"],
            max_tokens=params["max_tokens"],
            extra_body={"top_k": params["top_k"]},  # llama-server parameter, not part of the OpenAI API
            **({"tools": tools, "tool_choice": "none" if last else "auto"} if tools else {}),
        )
        prompt_tokens += response.usage.prompt_tokens
        completion_tokens += response.usage.completion_tokens
        choice = response.choices[0]
        if not choice.message.tool_calls or last:
            break
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
