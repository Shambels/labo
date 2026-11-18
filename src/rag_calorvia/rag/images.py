"""Bonus of step 7: the images an answer relies on, to show them next to it so the reader can check a value
the VLM read. Only the images of the extracts the answer cites ([2]); all of them when it cites none."""
import io

from PIL import Image

from rag_calorvia.config import settings
from rag_calorvia.etl.vision import page_image
from rag_calorvia.evaluation.metrics import cited_passages
from rag_calorvia.rag.permissions import can_read


def answer_images(answer, chunks, max_images=3):
    """[(image_path, page)] of the image or scan chunks the answer cites, in citation order, without duplicates."""
    cited = sorted(cited_passages(answer))
    pool = [chunks[n - 1] for n in cited if 1 <= n <= len(chunks)] if cited else chunks
    seen, images = set(), []
    for chunk in pool:
        key = (chunk.get("image_path"), chunk.get("page"))
        if key[0] and key not in seen:
            seen.add(key)
            images.append(key)
    return images[:max_images]


def image_bytes(path, page=None, max_side=900, role=None):
    """A JPEG of the image (or of the scanned page), small enough to display, if the role may read it."""
    if not can_read(role, path):
        raise PermissionError(path)
    image = page_image(settings.corpus_path / path, page, dpi=100) if page is not None else Image.open(settings.corpus_path / path)
    image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()
