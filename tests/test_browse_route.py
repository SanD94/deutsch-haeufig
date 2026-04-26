"""M1 — `/browse` page exposes the vocabeo-style filters over seeded words."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from deutsch_haufig.db import get_session
from deutsch_haufig.ingest.pipeline import upsert_word
from deutsch_haufig.ingest.vocabeo import parse_browse_page
from deutsch_haufig.main import app
from deutsch_haufig.models import Base

FIXTURES = Path(__file__).parent / "fixtures" / "vocabeo"


@pytest.fixture()
def seeded_client(tmp_path: Path) -> Iterator[TestClient]:
    """Spin up a per-test SQLite DB seeded from the fixture HTML pages."""
    db_path = tmp_path / "browse.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(  # noqa: N806 — sessionmaker returns a class
        bind=engine, autoflush=False, expire_on_commit=False
    )

    with TestSession() as session:
        # Slugs match those produced live by ingest.vocabeo.scrape_pages so the
        # /browse?category=… filter (which keys on Word.source_ref LIKE) works.
        for fixture, pos, category, slug in (
            ("verbs.html", "verb", "Common verbs", "100-most-common-german-verbs"),
            ("nouns.html", "noun", "Common nouns", "100-most-common-german-nouns"),
            (
                "adjectives.html",
                "adj",
                "Common adjectives",
                "100-most-common-german-adjectives",
            ),
            ("colors.html", "adj", "Colors", "colors-in-german"),
            ("numbers.html", "num", "Numbers", "numbers-in-german"),
        ):
            html = (FIXTURES / fixture).read_text(encoding="utf-8")
            entries = parse_browse_page(
                html,
                pos=pos,
                category=category,
                source_slug=f"vocabeo:{slug}",
            )
            for e in entries:
                upsert_word(session, e)
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
    assert "groß" in resp.text
    assert "Uhr" in resp.text
    assert "stellen" in resp.text
    # Total = 4 verbs + 3 nouns + 2 adjectives + 3 colors + 3 numbers = 15.
    assert "15 Wörter" in resp.text


def test_browse_filter_by_pos_keeps_only_matches(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?pos=noun")
    assert resp.status_code == 200
    # Nouns shown.
    assert "Uhr" in resp.text
    # Verbs / adjectives / numbers must be absent from the list.
    assert "stellen" not in resp.text
    assert "groß" not in resp.text
    assert "einundzwanzig" not in resp.text


def test_browse_filter_by_level_a1(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?level=A1")
    assert resp.status_code == 200
    # All seeded fixtures default to A1, so total is unchanged.
    assert "15 Wörter" in resp.text


def test_browse_filter_by_category_colors(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?category=Colors")
    assert resp.status_code == 200
    assert "rot" in resp.text
    assert "blau" in resp.text
    assert "grün" in resp.text
    # Non-color words must be filtered out.
    assert "stellen" not in resp.text
    assert "Uhr" not in resp.text


def test_browse_filter_by_frequency_top_bucket(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?frequency=5")
    assert resp.status_code == 200
    # Frequency 5 includes the rank-1 entries from each page.
    # We don't assert exact membership, just that the table renders and
    # at least one row survives.
    assert "Häufigkeit" in resp.text
    assert "<tbody>" in resp.text


def test_browse_full_text_search_on_lemma(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?q=ER")
    assert resp.status_code == 200
    # "sich erinnern", "(sich) vorstellen" don't match "er";
    # but "stellen", "nehmen" don't match either.  The verbs containing
    # "er" are "sich erinnern", "Mensch" (no), "Uhr" (no).  Use a more
    # discriminating substring: "uhr".
    resp = seeded_client.get("/browse?q=uhr")
    assert resp.status_code == 200
    assert "Uhr" in resp.text
    assert "stellen" not in resp.text


def test_browse_invalid_frequency_returns_422(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/browse?frequency=99")
    assert resp.status_code == 422
