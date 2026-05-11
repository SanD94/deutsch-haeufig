"""Tests for the learn route and spaced-repetition review flow.

M3: verify that review cards are auto-created, daily caps are enforced,
and the review rating pipeline works end-to-end.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from deutsch_haufig.db import get_session
from deutsch_haufig.main import create_app
from deutsch_haufig.models import Base, Example, ReviewCard, ReviewLog, Sense, User, Word
from deutsch_haufig.routes.learn import _ensure_user


def _seed_sample_words(session: Session, total: int = 3) -> list[Word]:
    words = []
    seed_words = [
        ("Haus", "die", "noun"),
        ("geben", None, "verb"),
        ("schon", None, "adj"),
    ]
    seed_words.extend((f"Wort{i}", None, "noun") for i in range(4, total + 1))
    for lemma, article, pos in seed_words[:total]:
        w = Word(lemma=lemma, article=article, pos=pos, level="A1", frequency=5)
        session.add(w)
        session.flush()
        sense = Sense(word_id=w.id, definition_de="Test definition for " + lemma)
        session.add(sense)
        session.flush()
        session.add(
            Example(
                sense_id=sense.id,
                text_de="Das ist ein Beispiel fur " + lemma + ".",
                source="test",
            )
        )
        words.append(w)
    session.commit()
    return words


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _test_engine(tmp_path: Path) -> Iterator[None]:
    """Patch the db module to use a disposable temp SQLite file."""
    import deutsch_haufig.db as db_mod

    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    test_sessionmaker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    old_engine = db_mod.engine
    old_sm = db_mod.SessionLocal
    db_mod.engine = engine
    db_mod.SessionLocal = test_sessionmaker
    try:
        yield
    finally:
        db_mod.engine = old_engine
        db_mod.SessionLocal = old_sm
        engine.dispose()


@pytest.fixture()
def db_session(_test_engine):
    from deutsch_haufig.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def app(db_session):
    app = create_app()

    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    return app


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def sample_words(db_session: Session):
    return _seed_sample_words(db_session)


# ---------------------------------------------------------------------------
# User auto-creation
# ---------------------------------------------------------------------------


class TestUserAutoCreation:
    def test_first_visit_creates_user(self, client, db_session, sample_words):
        resp = client.get("/learn")
        assert resp.status_code == 200
        count = db_session.execute(select(func.count(User.id))).scalar_one()
        assert count >= 1

    def test_user_persists_across_requests(self, client, db_session, sample_words):
        client.get("/learn")
        first_count = db_session.execute(select(func.count(User.id))).scalar_one()
        client.get("/learn")
        second_count = db_session.execute(select(func.count(User.id))).scalar_one()
        assert first_count == second_count == 1


# ---------------------------------------------------------------------------
# Review card creation
# ---------------------------------------------------------------------------


class TestCardCreation:
    def test_new_sense_creates_review_card(self, client, db_session, sample_words):
        client.get("/learn")
        card_count = db_session.execute(select(func.count(ReviewCard.id))).scalar_one()
        assert card_count >= 1

    def test_revisiting_does_not_duplicate_cards(self, client, db_session, sample_words):
        """Cards are created one-at-a-time; revisiting creates the next sense's card."""
        client.get("/learn")
        first_count = db_session.execute(select(func.count(ReviewCard.id))).scalar_one()
        assert first_count == 1
        client.get("/learn")
        second_count = db_session.execute(select(func.count(ReviewCard.id))).scalar_one()
        # Second visit creates a card for a different sense (not a duplicate)
        assert second_count == 2


# ---------------------------------------------------------------------------
# Review rating flow
# ---------------------------------------------------------------------------


class TestReviewRating:
    def _get_card(self, client, db_session):
        client.get("/learn")
        card = db_session.execute(select(ReviewCard).limit(1)).scalar_one_or_none()
        assert card is not None
        return card

    def test_rate_good_redirects(self, client, db_session, sample_words):
        card = self._get_card(client, db_session)
        resp = client.post(
            "/learn/rate",
            data={"card_id": card.id, "sense_id": card.sense_id, "rating": 3},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_rate_creates_review_log(self, client, db_session, sample_words):
        card = self._get_card(client, db_session)
        client.post(
            "/learn/rate",
            data={"card_id": card.id, "sense_id": card.sense_id, "rating": 3},
            follow_redirects=False,
        )
        log_count = db_session.execute(select(func.count(ReviewLog.id))).scalar_one()
        assert log_count >= 1

    def test_rate_updates_card_state(self, client, db_session, sample_words):
        card = self._get_card(client, db_session)
        client.post(
            "/learn/rate",
            data={"card_id": card.id, "sense_id": card.sense_id, "rating": 3},
            follow_redirects=False,
        )
        db_session.refresh(card)
        assert card.state in ("learning", "review")
        assert card.reps == 1

    def test_rate_again_increases_lapses(self, client, db_session, sample_words):
        card = self._get_card(client, db_session)
        client.post(
            "/learn/rate",
            data={"card_id": card.id, "sense_id": card.sense_id, "rating": 1},
            follow_redirects=False,
        )
        db_session.refresh(card)
        assert card.lapses == 1

    def test_rate_missing_card_redirects(self, client, sample_words):
        resp = client.post(
            "/learn/rate",
            data={"card_id": 99999, "sense_id": 1, "rating": 3},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_rate_via_form_body_succeeds(self, client, db_session, sample_words):
        """Browser-style form-encoded POST must not 422."""
        card = self._get_card(client, db_session)
        resp = client.post(
            "/learn/rate",
            data={"card_id": card.id, "sense_id": card.sense_id, "rating": 3},
            follow_redirects=False,
        )
        assert resp.status_code == 303


# ---------------------------------------------------------------------------
# Daily cap enforcement
# ---------------------------------------------------------------------------


class TestDailyCaps:
    def test_new_per_day_cap_respected(self, client, db_session, sample_words):
        user, _ = _ensure_user(db_session)
        user.settings_json = json.dumps(
            {
                "new_per_day": 2,
                "reviews_per_day": 120,
                "desired_retention": 0.9,
            }
        )
        db_session.commit()

        client.get("/learn")
        new_cards = db_session.execute(
            select(func.count(ReviewCard.id)).where(ReviewCard.user_id == user.id)
        ).scalar_one()
        assert new_cards <= 2


# ---------------------------------------------------------------------------
# Retention calculation
# ---------------------------------------------------------------------------


class TestRetention:
    def test_retention_calculation(self, client, db_session, sample_words):
        client.get("/learn")
        user = db_session.execute(select(User).limit(1)).scalar_one_or_none()
        card = db_session.execute(
            select(ReviewCard).where(ReviewCard.user_id == user.id).limit(1)
        ).scalar_one_or_none()

        now = datetime.now(UTC)
        for i, rating in enumerate([3, 4, 3, 1]):
            log = ReviewLog(
                card_id=card.id,
                ts=now - timedelta(days=i),
                rating=rating,
            )
            db_session.add(log)
        db_session.commit()

        # 3 out of 4 reviews are >= 3 (Good/Easy)
        from deutsch_haufig.routes.learn import _compute_retention_30d

        retention = _compute_retention_30d(db_session, user.id, now)
        assert retention is not None
        assert abs(retention - 0.75) < 0.01


# ---------------------------------------------------------------------------
# Header counters
# ---------------------------------------------------------------------------


class TestHeaderCounters:
    def _neu_count(self, text: str) -> int:
        """Extract the Neu counter value from rendered HTML."""
        import re
        m = re.search(r'Neu.*?<strong[^>]*>(\d+)</strong>', text)
        assert m is not None, f"Could not find Neu counter in:\n{text}"
        return int(m.group(1))

    def _fallig_count(self, text: str) -> int:
        """Extract the Fällig counter value from rendered HTML."""
        import re
        m = re.search(r'Fällig.*?<strong[^>]*>(\d+)</strong>', text)
        assert m is not None, f"Could not find Fällig counter in:\n{text}"
        return int(m.group(1))

    def _rate_card(self, client, card_id: int, rating: int = 3):
        resp = client.post(
            "/learn/rate",
            data={"card_id": card_id, "rating": rating},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        return resp

    def test_counters_displayed(self, client, sample_words):
        resp = client.get("/learn")
        assert resp.status_code == 200
        assert "Fällig" in resp.text
        assert "Neu" in resp.text

    def test_rating_form_uses_htmx(self, client, sample_words):
        """The visible rating form must send HTMX requests so HX-Redirect is used."""
        resp = client.get("/learn")
        assert resp.status_code == 200
        assert 'action="/learn/rate"' in resp.text
        assert 'hx-post="/learn/rate"' in resp.text

    def test_counters_start_correct(self, client, db_session, sample_words):
        """Three new words → Neu: 3, Fällig: 0."""
        resp = client.get("/learn")
        assert self._neu_count(resp.text) == 3
        assert self._fallig_count(resp.text) == 0

    def test_counters_decrease_after_rating(self, client, db_session, sample_words):
        """After rating a new card, new_count decreases by 1."""
        client.get("/learn")
        card = db_session.execute(select(ReviewCard).limit(1)).scalar_one_or_none()
        assert card is not None

        self._rate_card(client, card.id, rating=3)

        resp2 = client.get("/learn")
        assert self._neu_count(resp2.text) == 2
        assert self._fallig_count(resp2.text) == 0

    def test_new_counter_decreases_when_corpus_exceeds_daily_cap(self, client, db_session):
        """After rating one of many new cards, Neu should go 15→14, not refill to 15."""
        _seed_sample_words(db_session, total=20)

        resp = client.get("/learn")
        assert self._neu_count(resp.text) == 15

        card = db_session.execute(select(ReviewCard).limit(1)).scalar_one_or_none()
        assert card is not None
        self._rate_card(client, card.id, rating=3)

        resp2 = client.get("/learn")
        assert self._neu_count(resp2.text) == 14
        assert self._fallig_count(resp2.text) == 0

    def test_htmx_rating_redirects_to_fresh_counter_page(self, client, db_session, sample_words):
        """HTMX rating submissions must trigger a full reload so counters refresh."""
        client.get("/learn")
        card = db_session.execute(select(ReviewCard).limit(1)).scalar_one_or_none()
        assert card is not None

        resp = client.post(
            "/learn/rate",
            data={"card_id": card.id, "rating": 3},
            headers={"HX-Request": "true"},
            follow_redirects=False,
        )

        assert resp.status_code == 204
        assert resp.headers["HX-Redirect"] == "/learn"

        resp2 = client.get(resp.headers["HX-Redirect"])
        assert self._neu_count(resp2.text) == 2
        assert self._fallig_count(resp2.text) == 0

    def test_due_count_shows_due_cards(self, client, db_session, sample_words):
        """Cards due in the past appear in Fällig.

        Exhaust new senses first, then move one card due to the past.
        """
        client.get("/learn")
        for _ in range(3):
            card = db_session.execute(
                select(ReviewCard).order_by(ReviewCard.id.desc()).limit(1)
            ).scalar_one()
            self._rate_card(client, card.id, rating=3)
            client.get("/learn")

        assert db_session.execute(select(func.count(ReviewCard.id))).scalar_one() == 3

        # Move card1 due to the past
        card1 = db_session.execute(
            select(ReviewCard).order_by(ReviewCard.id).limit(1)
        ).scalar_one()
        card1.due = datetime.now(UTC) - timedelta(hours=1)
        db_session.commit()

        resp = client.get("/learn")
        assert self._fallig_count(resp.text) == 1
        assert self._neu_count(resp.text) == 0

    def test_counters_update_after_rating_due_card(self, client, db_session, sample_words):
        """After rating a due card, due_count decreases by 1.

        Exhaust all new senses first so only a past-due card remains.
        """
        # Create and rate all 3 cards so no new senses remain
        client.get("/learn")
        for _ in range(3):
            card = db_session.execute(
                select(ReviewCard).order_by(ReviewCard.id.desc()).limit(1)
            ).scalar_one()
            self._rate_card(client, card.id, rating=3)
            client.get("/learn")

        assert db_session.execute(select(func.count(ReviewCard.id))).scalar_one() == 3

        # Move card2 due to the past
        card2 = db_session.execute(
            select(ReviewCard).order_by(ReviewCard.id).limit(1).offset(1)
        ).scalar_one()
        card2.due = datetime.now(UTC) - timedelta(hours=1)
        db_session.commit()

        resp = client.get("/learn")
        assert self._fallig_count(resp.text) == 1
        assert self._neu_count(resp.text) == 0

        # Rate the due card
        self._rate_card(client, card2.id, rating=3)

        resp2 = client.get("/learn")
        assert self._fallig_count(resp2.text) == 0
        assert self._neu_count(resp2.text) == 0

    def test_counters_persist_across_ratings(self, client, db_session, sample_words):
        """Rate all 3 new cards — Neu goes 3→2→1→0, Fällig stays 0."""
        client.get("/learn")  # init

        for expected_neu in (2, 1, 0):
            card = db_session.execute(
                select(ReviewCard).order_by(ReviewCard.id.desc()).limit(1)
            ).scalar_one_or_none()
            assert card is not None
            self._rate_card(client, card.id, rating=3)
            resp = client.get("/learn")
            assert self._neu_count(resp.text) == expected_neu, (
                f"Expected Neu: {expected_neu}, "
                f"got Neu: {self._neu_count(resp.text)} "
                f"after rating card #{card.id}"
            )
            assert self._fallig_count(resp.text) == 0

    def test_remaining_text_updates(self, client, db_session, sample_words):
        """The 'N übrig' text should also decrease after ratings."""
        resp = client.get("/learn")
        assert "2 übrig" in resp.text  # 3 new - 1 current = 2 remaining

        card = db_session.execute(select(ReviewCard).limit(1)).scalar_one()
        self._rate_card(client, card.id, rating=3)

        resp = client.get("/learn")
        assert "1 übrig" in resp.text  # 2 new - 1 current = 1 remaining


# ---------------------------------------------------------------------------
# Browser regression
# ---------------------------------------------------------------------------


def test_browser_rating_click_updates_visible_counters(tmp_path: Path) -> None:
    """A real browser click should update the rendered Fällig/Neu DOM counters."""
    try:
        import uvicorn
        from playwright.sync_api import Error, expect, sync_playwright
    except ImportError as exc:
        pytest.skip(f"browser dependencies are not installed: {exc}")

    db_path = tmp_path / "browser.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    test_sessionmaker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with test_sessionmaker() as session:
        _seed_sample_words(session, total=20)

    app = create_app()

    def _override():
        session = test_sessionmaker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Error as exc:
                pytest.skip(f"playwright chromium is not installed: {exc}")
            try:
                page = browser.new_page()
                page.goto(f"http://{host}:{port}/learn", wait_until="domcontentloaded")

                expect(page.locator('[data-testid="due-count"]')).to_have_text("0")
                expect(page.locator('[data-testid="new-count"]')).to_have_text("15")

                page.keyboard.press("Space")
                page.get_by_role("button", name="Good 3").click()

                expect(page.locator('[data-testid="due-count"]')).to_have_text("0")
                expect(page.locator('[data-testid="new-count"]')).to_have_text("14")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        engine.dispose()
