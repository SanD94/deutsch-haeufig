"""M1 — `/browse` exposes the vocabeo-style filters over seeded words.

Filters covered: level, pos, frequency, full-text on lemma.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from deutsch_haufig.db import get_session
from deutsch_haufig.ingest.pipeline import upsert_word
from deutsch_haufig.ingest.vocabeo import parse_row_html
from deutsch_haufig.main import app
from deutsch_haufig.models import Base

FIXTURES = Path(__file__).parent / "fixtures" / "vocabeo"

# Each tuple: (fixture file, pos tag) — mirrors the live scraper's
# per-POS-filter loop. Five rows, five POS variants.
SEED_ROWS = (
    ("adj_a1.html", "adj"),
    ("noun_der.html", "noun"),
    ("noun_die.html", "noun"),
    ("verb_sein.html", "verb"),
    ("pron_no_level.html", "pron"),
)


@pytest.fixture()
def seeded_client(tmp_path: Path) -> Iterator[TestClient]:
    """Spin up a per-test SQLite DB seeded from the M1 row fixtures."""
    db_path = tmp_path / "browse.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(  # noqa: N806 — sessionmaker returns a class
        bind=engine, autoflush=False, expire_on_commit=False
    )

    with TestSession() as session:
        for fname, pos in SEED_ROWS:
            html = (FIXTURES / fname).read_text(encoding="utf-8")
            entry = parse_row_html(
                html,
                pos=pos,
                source_slug=f"vocabeo:browse#{pos}:{fname}",
            )
            upsert_word(session, entry)
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
    # 5 fixture rows seeded.
    assert "5 Wörter" in resp.text


def test_browse_filter_by_pos_keeps_only_nouns(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?pos=noun")
    assert resp.status_code == 200
    assert "Mensch" in resp.text
    assert "Uhr" in resp.text
    # adj/verb/pron must be filtered out.
    assert "gut" not in resp.text


def test_browse_filter_by_pos_verb(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?pos=verb")
    assert resp.status_code == 200
    # Only the verb row should remain; the pronoun "sein" is filtered out.
    assert "1 Wörter" in resp.text
    assert "<td>verb</td>" in resp.text
    assert "<td>pron</td>" not in resp.text


def test_browse_filter_by_level_a1(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?level=A1")
    assert resp.status_code == 200
    # Four of the five fixtures carry level=A1; pron_no_level has no level.
    assert "4 Wörter" in resp.text
    assert "<td>pron</td>" not in resp.text


def test_browse_filter_by_frequency_top_bucket(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?frequency=5")
    assert resp.status_code == 200
    # Four of the five fixtures are frequency=5; the pronoun row is freq=3.
    assert "4 Wörter" in resp.text
    assert "<td>pron</td>" not in resp.text


def test_browse_full_text_search_on_lemma(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?q=uhr")
    assert resp.status_code == 200
    assert "Uhr" in resp.text
    # Other lemmas must not appear in the table body.
    assert "Mensch" not in resp.text
    assert "gut" not in resp.text


def test_browse_invalid_frequency_returns_422(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?frequency=99")
    assert resp.status_code == 422


def test_browse_empty_frequency_is_optional(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?frequency=")
    assert resp.status_code == 200
    assert "5 Wörter" in resp.text


def test_browse_no_category_filter_anymore(seeded_client: TestClient) -> None:
    """M1 dropped the category filter; the form must not advertise it."""
    resp = seeded_client.get("/browse")
    assert resp.status_code == 200
    assert "Kategorie" not in resp.text
    assert 'name="category"' not in resp.text
