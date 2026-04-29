"""Learn / SRS route — spaced-repetition review session.

M3: serves the /learn page with gap-cloze flashcards, FSRS review buttons,
daily caps, and header counters.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from deutsch_haufig.db import get_session
from deutsch_haufig.models import ReviewCard, ReviewLog, Sense, User, Word
from deutsch_haufig.scheduler import FSRSScheduler, Rating
from deutsch_haufig.templating import templates

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]

COOKIE_USER_ID = "dh_user_id"
COOKIE_MAX_AGE = 365 * 24 * 3600  # 1 year


# ---------------------------------------------------------------------------
# User management (simple cookie-based, no auth for M3)
# ---------------------------------------------------------------------------


def _get_user_id(request: Request) -> int | None:
    uid = request.cookies.get(COOKIE_USER_ID)
    if uid:
        try:
            return int(uid)
        except ValueError:
            return None
    return None


def _ensure_user(session: Session) -> tuple[User, bool]:
    """Return the current user, creating a default one if needed.

    Returns ``(user, is_new)``.
    """
    user = session.execute(select(User).order_by(User.id).limit(1)).scalar_one_or_none()
    if user is None:
        user = User(settings_json=json.dumps({
            "new_per_day": FSRSScheduler.DEFAULT_NEW_PER_DAY,
            "reviews_per_day": FSRSScheduler.DEFAULT_REVIEWS_PER_DAY,
            "desired_retention": 0.9,
        }))
        session.add(user)
        session.commit()
        return user, True
    return user, False


def _user_response(response, user_id: int):
    """Set the user-id cookie on the response."""
    response.set_cookie(
        COOKIE_USER_ID,
        str(user_id),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


def _get_user_settings(user: User) -> dict:
    defaults = {
        "new_per_day": FSRSScheduler.DEFAULT_NEW_PER_DAY,
        "reviews_per_day": FSRSScheduler.DEFAULT_REVIEWS_PER_DAY,
        "desired_retention": 0.9,
    }
    if user.settings_json:
        try:
            cfg = json.loads(user.settings_json)
            defaults.update(cfg)
        except (json.JSONDecodeError, TypeError):
            pass
    return defaults


# ---------------------------------------------------------------------------
# Daily cap helpers
# ---------------------------------------------------------------------------


def _today_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _count_reviews_today(session: Session, user_id: int, now: datetime) -> int:
    start = _today_start(now)
    stmt = (
        select(func.count(ReviewLog.id))
        .join(ReviewCard, ReviewCard.id == ReviewLog.card_id)
        .where(ReviewCard.user_id == user_id)
        .where(ReviewLog.ts >= start)
    )
    return session.execute(stmt).scalar_one()


def _count_new_today(session: Session, user_id: int, now: datetime) -> int:
    start = _today_start(now)
    stmt = (
        select(func.count(ReviewCard.id))
        .where(ReviewCard.user_id == user_id)
        .where(ReviewCard.state == "new")
        .where(ReviewCard.due >= start)  # created today
    )
    return session.execute(stmt).scalar_one()


def _compute_retention_30d(session: Session, user_id: int, now: datetime) -> float | None:
    """Fraction of reviews in the last 30 days that were Good/Easy (≥3)."""
    cutoff = now - timedelta(days=30)
    stmt = (
        select(func.count(ReviewLog.id))
        .join(ReviewCard, ReviewCard.id == ReviewLog.card_id)
        .where(ReviewCard.user_id == user_id)
        .where(ReviewLog.ts >= cutoff)
    )
    total = session.execute(stmt).scalar_one()
    if total == 0:
        return None

    good_stmt = (
        select(func.count(ReviewLog.id))
        .join(ReviewCard, ReviewCard.id == ReviewLog.card_id)
        .where(ReviewCard.user_id == user_id)
        .where(ReviewLog.ts >= cutoff)
        .where(ReviewLog.rating >= 3)
    )
    good = session.execute(good_stmt).scalar_one()
    return good / total


# ---------------------------------------------------------------------------
# Queue building
# ---------------------------------------------------------------------------


def _build_scheduler(user: User) -> FSRSScheduler:
    settings = _get_user_settings(user)
    return FSRSScheduler(
        desired_retention=settings.get("desired_retention", 0.9),
    )


def _get_due_cards(
    session: Session,
    user_id: int,
    now: datetime,
    limit: int,
) -> list[ReviewCard]:
    """Return review cards that are due (due <= now), ordered by due date."""
    stmt = (
        select(ReviewCard)
        .where(ReviewCard.user_id == user_id)
        .where(ReviewCard.state != "new")
        .where(ReviewCard.due <= now)
        .order_by(ReviewCard.due.asc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def _get_new_senses(
    session: Session,
    user_id: int,
    now: datetime,
    limit: int,
) -> list[Sense]:
    """Return senses that the user has NOT yet turned into a review card."""
    # Subquery: senses the user already has cards for
    have_cards = (
        select(ReviewCard.sense_id)
        .where(ReviewCard.user_id == user_id)
    )
    stmt = (
        select(Sense)
        .join(Word, Word.id == Sense.word_id)
        .where(Sense.id.notin_(have_cards))
        .order_by(Word.frequency.desc(), Word.lemma.asc(), Sense.order.asc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def _create_review_cards_for_senses(
    session: Session,
    user_id: int,
    senses: list[Sense],
    scheduler: FSRSScheduler,
    now: datetime,
) -> list[tuple[Sense, ReviewCard]]:
    """Create ReviewCards for new senses.  Returns list of (sense, card)."""
    results: list[tuple[Sense, ReviewCard]] = []
    for sense in senses:
        card = ReviewCard(
            user_id=user_id,
            sense_id=sense.id,
            state="new",
            due=now,  # due immediately so it shows up
        )
        session.add(card)
        results.append((sense, card))
    session.commit()
    # Refresh to get IDs
    for _, card in results:
        session.refresh(card)
    return results


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/learn", response_class=HTMLResponse)
def learn(
    request: Request,
    session: SessionDep,
):
    """Main learn page — shows the next card to review."""
    user, _ = _ensure_user(session)
    settings = _get_user_settings(user)
    now = datetime.now(UTC)

    # Compute today's counts
    reviews_today = _count_reviews_today(session, user.id, now)
    new_today = _count_new_today(session, user.id, now)
    remaining_reviews = max(0, settings["reviews_per_day"] - reviews_today)
    remaining_new = max(0, settings["new_per_day"] - new_today)
    retention = _compute_retention_30d(session, user.id, now)

    # Build scheduler and fetch queue
    scheduler = _build_scheduler(user)
    due_cards = _get_due_cards(session, user.id, now, remaining_reviews)
    new_senses = _get_new_senses(session, user.id, now, remaining_new)

    # If no cards at all and corpus is empty, show a message
    if not due_cards and not new_senses:
        total_words = session.execute(select(func.count(Word.id))).scalar_one()
        if total_words == 0:
            return templates.TemplateResponse(
                request,
                "learn.html",
                {
                    "title": "Learn",
                    "user_id": user.id,
                    "due_count": 0,
                    "new_count": 0,
                    "retention": retention,
                    "empty_corpus": True,
                },
            )

    # If we have new senses, create cards and pick the first one
    current_sense = None
    current_card = None
    card_dict = None

    if new_senses:
        sense_card_pairs = _create_review_cards_for_senses(
            session, user.id, new_senses, scheduler, now
        )
        current_sense, current_card = sense_card_pairs[0]
        # Use the card dict from scheduler for consistency
        card_dict = scheduler.new_card()
        current_card.stability = card_dict.get("stability")
        current_card.difficulty = card_dict.get("difficulty")
        session.commit()

    # Otherwise pick the first due card
    if due_cards and current_card is None:
        current_card = due_cards[0]
        current_sense = session.execute(
            select(Sense).where(Sense.id == current_card.sense_id)
        ).scalar_one()

    # Build sense detail
    sense_data = None
    if current_sense:
        sense_data = {
            "id": current_sense.id,
            "lemma": current_sense.word.lemma,
            "article": current_sense.word.article,
            "pos": current_sense.word.pos,
            "definition_de": current_sense.definition_de,
            "examples": [
                {"text_de": ex.text_de, "translation_en": ex.translation_en}
                for ex in current_sense.examples
            ],
        }

    # Serialize card data for the HTMX form
    card_data = None
    if current_card:
        card_data = {
            "id": current_card.id,
            "sense_id": current_card.sense_id,
            "state": current_card.state,
            "card_dict": card_dict if card_dict else {
                "state": 1,
                "step": 0,
                "stability": current_card.stability,
                "difficulty": current_card.difficulty,
                "due": (
                    current_card.due.isoformat()
                    if current_card.due
                    else None
                ),
                "last_review": (
                    current_card.last_review.isoformat()
                    if current_card.last_review
                    else None
                ),
            },
        }

    # Count remaining after this card
    remaining_due = max(0, len(due_cards) - 1) if due_cards else 0
    remaining_new_q = max(0, len(new_senses) - 1) if new_senses else 0
    total_remaining = remaining_due + remaining_new_q

    return templates.TemplateResponse(
        request,
        "learn.html",
        {
            "title": "Learn",
            "user_id": user.id,
            "due_count": len(due_cards),
            "new_count": len(new_senses),
            "retention": retention,
            "sense": sense_data,
            "card": card_data,
            "remaining": total_remaining,
            "settings": settings,
            "empty_corpus": False,
        },
    )


@router.post("/learn/rate")
def learn_rate(
    request: Request,
    session: SessionDep,
    card_id: Annotated[int, Query()],
    sense_id: Annotated[int, Query()],
    rating: Annotated[int, Query()],
):
    """Process a rating for the current card and redirect to next card."""
    user, _ = _ensure_user(session)
    now = datetime.now(UTC)
    scheduler = _build_scheduler(user)

    # Load the review card
    card = session.execute(
        select(ReviewCard).where(ReviewCard.id == card_id)
    ).scalar_one_or_none()
    if card is None:
        return RedirectResponse(url="/learn", status_code=303)

    # Build fsrs card dict from stored data (fsrs from_dict needs all keys)
    card_dict = {
        "card_id": card.id,
        "state": {"learning": 1, "review": 2, "relearning": 3}.get(card.state, 1),
        "step": 0,
        "stability": card.stability or 0.0,
        "difficulty": card.difficulty or 0.0,
        "due": card.due.isoformat() if card.due else datetime.now(UTC).isoformat(),
        "last_review": card.last_review.isoformat() if card.last_review else None,
    }

    # Review with fsrs
    fs_rating = Rating(rating)
    result = scheduler.review(card_dict, fs_rating, now=now)

    # Update card in DB
    updated = result.card
    card.state = {1: "learning", 2: "review", 3: "relearning"}.get(
        updated.get("state", 1), "learning"
    )
    card.stability = updated.get("stability")
    card.difficulty = updated.get("difficulty")

    due_str = updated.get("due")
    if due_str:
        card.due = datetime.fromisoformat(due_str)

    card.last_review = now
    card.reps += 1
    if fs_rating == Rating.AGAIN:
        card.lapses += 1

    # Log the review
    log = ReviewLog(
        card_id=card.id,
        ts=now,
        rating=int(fs_rating),
        elapsed_days=result.elapsed_days,
        scheduled_days=result.scheduled_days,
    )
    session.add(log)
    session.commit()

    return RedirectResponse(url="/learn", status_code=303)


@router.post("/learn/finish")
def learn_finish(request: Request):
    """Finish the session — redirect to /learn which will reset the queue."""
    return RedirectResponse(url="/learn", status_code=303)
