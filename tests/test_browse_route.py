"""M1-DWDS — `/browse` exposes level/POS/frequency filters over Goethe-seeded words.

Filters covered: level, pos, frequency, full-text on lemma.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from deutsch_haufig.db import get_session
from deutsch_haufig.ingest.goethe import GoetheEntry
from deutsch_haufig.ingest.pipeline import upsert_goethe_word
from deutsch_haufig.main import app
from deutsch_haufig.models import Base


@dataclass
class _SeedWord:
    lemma: str
    pos: str
    level: str | None
    article: str | None = None


SEED_WORDS: tuple[_SeedWord, ...] = (
    _SeedWord("gut", "adj", "A1"),
    _SeedWord("Mensch", "noun", "A1", "der"),
    _SeedWord("Uhr", "noun", "A1", "die"),
    _SeedWord("sein", "verb", "A1"),
    _SeedWord("man", "pron", None),
)


@pytest.fixture()
def seeded_client(tmp_path: Path) -> Iterator[TestClient]:
    """Spin up a per-test SQLite DB seeded with Goethe-style words."""
    db_path = tmp_path / "browse.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    with TestSession() as session:
        for w in SEED_WORDS:
            level = w.level
            entry = GoetheEntry(
                lemma=w.lemma,
                url=f"https://www.dwds.de/wb/{w.lemma}",
                pos=w.pos,
                level=level,
                article=w.article,
                genus=None,
                only_plural=False,
            )
            upsert_goethe_word(session, entry)
        session.commit()

    def _override() -> Iterator[Session]:
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def test_browse_lists_all_seeded_words(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse")
    assert resp.status_code == 200
    assert "gut" in resp.text
    assert "Mensch" in resp.text
    assert "Uhr" in resp.text
    assert "sein" in resp.text
    assert "man" in resp.text


def test_browse_filter_by_pos_keeps_only_nouns(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?pos=noun")
    assert resp.status_code == 200
    assert "Mensch" in resp.text
    assert "Uhr" in resp.text
    assert "gut" not in resp.text


def test_browse_filter_by_pos_verb(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?pos=verb")
    assert resp.status_code == 200
    assert "sein" in resp.text
    assert "man" not in resp.text


def test_browse_filter_by_level_a1(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?level=A1")
    assert resp.status_code == 200
    assert "gut" in resp.text
    assert "Mensch" in resp.text
    assert "Uhr" in resp.text
    assert "sein" in resp.text
    # man has no level, filtered out
    assert "man" not in resp.text


def test_browse_full_text_search_on_lemma(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?q=uhr")
    assert resp.status_code == 200
    assert "Uhr" in resp.text
    assert "Mensch" not in resp.text


def test_browse_empty_frequency_is_optional(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?frequency=")
    assert resp.status_code == 200


def test_browse_returns_all_words_when_no_limit(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse")
    assert resp.status_code == 200
    assert "gut" in resp.text
    assert "Mensch" in resp.text
    assert "Uhr" in resp.text
    assert "sein" in resp.text
    assert "man" in resp.text
    assert "5 Wörter" in resp.text
    assert "Nächste" not in resp.text


def test_browse_pagination_shows_when_limit_exceeds_total(
    seeded_client: TestClient,
) -> None:
    resp = seeded_client.get("/browse?limit=2")
    assert resp.status_code == 200
    assert "Nächste" in resp.text
    assert "1–2 von 5" in resp.text
