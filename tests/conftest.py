import httpx
import pytest

from newshouse.db import get_engine, init_db, session_scope


@pytest.fixture(autouse=True)
def lessons_path(tmp_path, monkeypatch):
    """Every test gets its own ledger: no test reads or writes ledger/lessons.json
    through settings (explicit ``Settings(...)`` objects read LESSONS_PATH too)."""
    from newshouse.config import get_settings
    path = tmp_path / "lessons.json"
    monkeypatch.setenv("LESSONS_PATH", str(path))
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
def session(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    try:
        with session_scope(engine) as s:
            yield s
    finally:
        engine.dispose()


@pytest.fixture
def httpx_client():
    with httpx.Client() as c:
        yield c
