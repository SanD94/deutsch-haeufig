"""Tests for the learn route and spaced-repetition review flow.

M3: verify that review cards are auto-created, daily caps are enforced,
and the review rating pipeline works end-to-end.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from deutsch_haufig.db import SessionLocal, get_session
from deutsch_haufig.main import create_app
from deutsch_haufig.models import Example, ReviewCard, ReviewLog, Sense, User, Word
from deutsch_haufig.routes.learn import _ensure_user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_db():
    from deutsch_haufig.models import Base
    from deutsch_haufig.db import engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def db_session():
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
    words = []
    for lemma, article, pos in [
        ("Haus", "die", "noun"),
        ("geben", None, "verb"),
        ("schon", None, "adj"),
    ]:
        w = Word(lemma=lemma, article=article, pos=pos, level="A1", frequency=5)
        db_session.add(w)
        db_session.flush()
        sense = Sense(word_id=w.id, definition_de="Test definition for " + lemma)
        db_session.add(sense)
        db_session.flush()
        db_session.add(
            Example(
                sense_id=sense.id,
                text_de="Das ist ein Beispiel fur " + lemma + ".",
                source="test",
            )
        )
        words.append(w)
    db_session.commit()
    return words


# ---------------------------------------------------------------------------
# User auto-creation
# ---------------------------------------------------------------------------


class TestUserAutoCreation:
    def test_first_visit_creates_user(self, client, sample_words):
        resp = client.get("/learn")
        assert resp.status_code == 200
        session = SessionLocal()
        count = session.execute(select(func.count(User.id))).scalar_one()
        session.close()
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
        client.get("/learn")
        first_count = db_session.execute(select(func.count(ReviewCard.id))).scalar_one()
        client.get("/learn")
        second_count = db_session.execute(select(func.count(ReviewCard.id))).scalar_one()
        assert second_count == first_count


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
            params={"card_id": card.id, "sense_id": card.sense_id, "rating": 3},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_rate_creates_review_log(self, client, db_session, sample_words):
        card = self._get_card(client, db_session)
        client.post(
            "/learn/rate",
            params={"card_id": card.id, "sense_id": card.sense_id, "rating": 3},
            follow_redirects=False,
        )
        log_count = db_session.execute(select(func.count(ReviewLog.id))).scalar_one()
        assert log_count >= 1

    def test_rate_updates_card_state(self, client, db_session, sample_words):
        card = self._get_card(client, db_session)
        client.post(
            "/learn/rate",
            params={"card_id": card.id, "sense_id": card.sense_id, "rating": 3},
            follow_redirects=False,
        )
        db_session.refresh(card)
        assert card.state in ("learning", "review")
        assert card.reps == 1

    def test_rate_again_increases_lapses(self, client, db_session, sample_words):
        card = self._get_card(client, db_session)
        client.post(
            "/learn/rate",
            params={"card_id": card.id, "sense_id": card.sense_id, "rating": 1},
            follow_redirects=False,
        )
        db_session.refresh(card)
        assert card.lapses == 1

    def test_rate_missing_card_redirects(self, client, sample_words):
        resp = client.post(
            "/learn/rate",
            params={"card_id": 99999, "sense_id": 1, "rating": 3},
            follow_redirects=False,
        )
        assert resp.status_code == 303


# ---------------------------------------------------------------------------
# Daily cap enforcement
# ---------------------------------------------------------------------------


class TestDailyCaps:
    def test_new_per_day_cap_respected(self, client, db_session, sample_words):
        user, _ = _ensure_user(db_session)
        user.settings_json = json.dumps({
            "new_per_day": 2,
            "reviews_per_day": 120,
            "desired_retention": 0.9,
        })
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
    def test_counters_displayed(self, client, sample_words):
        resp = client.get("/learn")
        assert resp.status_code == 200
        assert "Due today" in resp.text
        assert "New today" in resp.text
        assert "Retention 30d" in resp.text
