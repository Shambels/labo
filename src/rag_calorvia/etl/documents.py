"""A document's text rebuilt from its chunks, for the LLM passes that read whole documents (step 41)."""


def by_document(chunks):
    """{document: [its chunks]}, in the chunks' order."""
    documents = {}
    for chunk in chunks:
        documents.setdefault(chunk["document"], []).append(chunk)
    return documents


def body_of(chunk, has_context_line):
    """The chunk without its context line, which is the same for every chunk of a document."""
    return chunk["text"].partition("\n")[2] if has_context_line else chunk["text"]


def document_text(chunks, has_context_line, max_chars):
    """A document as the LLM reads it: its context line once, then its chunks' bodies, cut at max_chars."""
    head = [chunks[0]["text"].partition("\n")[0]] if has_context_line and chunks else []
    return "\n\n".join(head + [body_of(chunk, has_context_line) for chunk in chunks])[:max_chars]
