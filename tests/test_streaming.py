"""Step 45: the documents' answer shown as it is written.

generate() streams when given on_text and must return what it returns without it (tool rounds included);
documents.Release decides what may be shown before the answer is complete: nothing uncited, no half citation, no tool
call written as text, nothing more once a round's text turned out not to be the answer.
"""
import json
from types import SimpleNamespace

from rag_calorvia.rag import generate as generate_module
from text2sql_calorvia import documents
from text2sql_calorvia.api import rest_of

CONFIG = {"generation": {"model": "m", "system_prompt": "prompts/tools.txt", "temperature": 0.0, "top_p": 1.0,
                         "top_k": 40, "max_tokens": 64}, "tools": {"tables": True}}
ANSWER = "Herstal comptait 6 ETP [1]."


def piece(content=None, call=None, finish=None):
    calls = [SimpleNamespace(index=0, id=call[0], function=SimpleNamespace(name=call[1], arguments=call[2]))] if call else None
    delta = SimpleNamespace(content=content, tool_calls=calls)
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=delta, finish_reason=finish)])


USAGE = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5), choices=[])
# A tool call arriving in pieces, then the answer in pieces: what llama-server streams for a table question
ROUNDS = [[piece(call=("c1", "run_sql", '{"sql": ')), piece(call=(None, None, '"SELECT 6"}')),
           piece(finish="tool_calls"), USAGE],
          [piece("Herstal comptait "), piece("6 ETP [1"), piece("]."), piece(finish="stop"), USAGE]]


def fake_llm(requests):
    def create(**kwargs):
        requests.append(kwargs)
        stream = ROUNDS[len(requests) - 1]
        if kwargs.get("stream"):
            return iter(stream)
        calls = [{"id": "c1", "type": "function", "function": {"name": "run_sql", "arguments": '{"sql": "SELECT 6"}'}}]
        message = generate_module.ChatCompletionMessage(
            role="assistant", content=None if len(requests) == 1 else ANSWER,
            tool_calls=calls if len(requests) == 1 else None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=stream[-2].choices[0].finish_reason)],
                               usage=USAGE.usage)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_a_streamed_answer_is_the_answer_without_streaming(monkeypatch):
    monkeypatch.setattr("rag_calorvia.rag.tables.get_store", lambda role=None: None)
    monkeypatch.setattr("rag_calorvia.rag.tables.call_tool", lambda store, name, args: json.dumps({"rows": [[6]]}))
    results, sent = {}, []
    for mode in ("plain", "stream"):
        requests = []
        monkeypatch.setattr(generate_module, "get_llm", lambda: fake_llm(requests))
        results[mode] = generate_module.generate("Combien à Herstal ?", [{"text": "Herstal"}], CONFIG,
                                                 on_text=sent.append if mode == "stream" else None)
        results[mode + "_messages"] = requests[1]["messages"]
    assert results["stream"]["answer"] == results["plain"]["answer"] == ANSWER
    assert results["stream"]["tool_calls"] == results["plain"]["tool_calls"]
    assert results["stream"]["completion_tokens"] == results["plain"]["completion_tokens"] == 10
    assert results["stream_messages"] == results["plain_messages"]   # the tool call put together from its pieces
    assert sent == [None, "Herstal comptait ", "6 ETP [1", "]."]       # None: the tool round had no answer


def release():
    shown = []
    return documents.Release(shown.append), shown


def test_nothing_is_shown_before_a_citation_nor_half_a_citation():
    r, shown = release()
    for delta in ["\n", "Le budget ", "est de 2 500 000 € [", "1", "] et ", "il vaut pour 2026 [2]."]:
        r.feed(delta)
    assert shown == ["Le budget est de 2 500 000 € [D1] et ", "il vaut pour 2026 [D2]."]


def test_an_uncited_answer_is_never_shown():
    for text in ["I hate humans", "Je ne sais pas.", "<tool_call>\n<function=run_sql> [1]"]:
        r, shown = release()
        for delta in text.split(" "):
            r.feed(delta + " ")
        assert shown == [], text


def test_a_tool_round_drops_its_text_or_stops_the_stream():
    r, shown = release()
    r.feed("Je vais chercher")       # not shown (no citation), then the round ends in a tool call
    r.feed(None)
    r.feed("6 ETP [1].")
    assert shown == ["6 ETP [D1]."]
    r, shown = release()
    r.feed("Selon [1], ")            # shown, then the round ends in a tool call: nothing more is shown
    r.feed(None)
    r.feed("6 ETP [1].")
    assert shown == ["Selon [D1], "]


def test_the_end_of_the_answer_follows_what_was_shown():
    answer = "6 ETP [D1].\n\n---\n**Documents utilisés**\n\n**D1** · document `a.pdf` · sans date"
    assert rest_of(answer, "6 ETP [D1]") == answer[len("6 ETP [D1]"):]
    assert rest_of(answer, "") == answer
    assert rest_of(answer, "Selon [D1]") == "\n\n---\n\n" + answer   # what was shown is not the answer
