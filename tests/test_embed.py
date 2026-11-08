from datetime import datetime, timezone

import numpy as np
import pytest

from newshouse.db import bytes_to_vec
from newshouse.embed import Embedder, embed_new_items, text_for_item
from newshouse.models import Item


@pytest.fixture(scope="module")
def embedder():
    return Embedder()


def test_embed_shape_and_norm(embedder):
    out = embedder.embed(["one", "two words", "a third text"])
    assert out.shape == (3, 384)
    assert out.dtype == np.float32
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-4)
    assert embedder.embed([]).shape == (0, 384)


def test_similar_titles_closer_than_different(embedder):
    a, b, c = embedder.embed(
        [
            "Google ships Gemini 3 Flash",
            "Gemini 3 Flash released by Google",
            "Barcelona beat Girona 2-1",
        ]
    )
    assert float(a @ b) > float(a @ c)


def _item(id_, title, teaser="", stale=False, embedding=None, minute=0):
    return Item(
        id=id_,
        title=title,
        teaser=teaser,
        url=f"https://example.com/{id_}",
        canonical_url=f"https://example.com/{id_}",
        published_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
        dated=True,
        topics=[],
        raw={},
        stale=stale,
        embedding=embedding,
        first_seen_at=datetime(2026, 10, 30, 0, minute, tzinfo=timezone.utc),
    )


def test_embed_new_items_skips_stale_and_done(session, embedder):
    sentinel = b"\x00" * 4
    session.add_all(
        [
            _item("fresh1", "Gemini 3 Flash launches", "teaser", minute=1),
            _item("fresh2", "Barcelona win again", minute=2),
            _item("stale", "Old news", stale=True, minute=3),
            _item("done", "Already embedded", embedding=sentinel, minute=4),
        ]
    )
    session.flush()
    assert text_for_item(session.get(Item, "fresh1")) == "Gemini 3 Flash launches\nteaser"
    assert embed_new_items(session, embedder, batch=1) == 2
    assert embed_new_items(session, embedder) == 0
    assert bytes_to_vec(session.get(Item, "fresh1").embedding).shape == (384,)
    assert session.get(Item, "stale").embedding is None
    assert session.get(Item, "done").embedding == sentinel
