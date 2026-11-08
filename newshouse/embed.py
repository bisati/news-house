"""Local text embeddings (fastembed, BAAI/bge-small-en-v1.5) for clustering."""

from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from newshouse.db import vec_to_bytes
from newshouse.models import Item

DIM = 384
CACHE_DIR = Path("~/.cache/news-house/fastembed").expanduser()


class Embedder:
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        self.model = model
        self._engine = None

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        if self._engine is None:
            from fastembed import TextEmbedding

            self._engine = TextEmbedding(model_name=self.model, cache_dir=str(CACHE_DIR))
        out = np.stack(list(self._engine.embed(texts, batch_size=64))).astype(np.float32)
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-12)


def text_for_item(item: Item) -> str:
    return f"{item.title}\n{(item.teaser or '')[:500]}"


def embed_new_items(session: Session, embedder: Embedder, *, batch: int = 128) -> int:
    items = session.scalars(
        select(Item)
        .where(Item.embedding.is_(None), Item.stale == False)  # noqa: E712
        .order_by(Item.first_seen_at)
    ).all()
    for i in range(0, len(items), batch):
        chunk = items[i : i + batch]
        vecs = embedder.embed([text_for_item(it) for it in chunk])
        for it, v in zip(chunk, vecs):
            it.embedding = vec_to_bytes(v)
        session.flush()
    return len(items)
