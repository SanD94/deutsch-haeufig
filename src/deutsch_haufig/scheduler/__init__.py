"""Spaced-repetition scheduler interface + FSRS implementation.

M3: wraps the ``fsrs`` library behind a Protocol so the rest of the app
never imports fsrs directly.  ``ReviewCard`` rows store serialised FSRS
``Card`` dicts (``to_dict``/``from_dict``).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------


class Rating(int, enum.Enum):
    """User feedback on a review — mirrors fsrs.Rating values."""

    AGAIN = 1  # forgot the card
    HARD = 2   # remembered with serious difficulty
    GOOD = 3   # remembered after hesitation
    EASY = 4   # remembered easily


class CardState(enum.StrEnum):
    """Lifecycle of a card in our system."""

    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


@dataclass(frozen=True)
class ReviewResult:
    """Outcome of rating a card."""

    card: CardDict          # serialised FSRS card (for DB persistence)
    rating: Rating
    scheduled_days: float
    elapsed_days: float


# ---------------------------------------------------------------------------
# Opaque dict type — what we store in DB ``ReviewCard.stability`` (JSON blob)
# ---------------------------------------------------------------------------
CardDict = dict  # fsrs.Card.to_dict() output; typed as dict for simplicity


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class Scheduler(Protocol):
    """Minimal interface every scheduler must implement."""

    def new_card(self) -> CardDict:
        """Return a serialised brand-new FSRS card."""

    def review(
        self,
        card: CardDict,
        rating: Rating,
        now: datetime | None = None,
    ) -> ReviewResult:
        """Apply *rating* to *card* and return the updated card + metadata."""

    def retrievability(self, card: CardDict, now: datetime | None = None) -> float | None:
        """Return retrievability ∈ [0, 1] or None for a new card."""

    @staticmethod
    def state_from_fsrs(fsrs_state: int) -> CardState:
        """Map fsrs integer state → our CardState enum."""


# ---------------------------------------------------------------------------
# FSRS implementation
# ---------------------------------------------------------------------------

# Lazy import — fsrs is heavy and may not be installed in test-only envs.
_fsrs = None


def _get_fsrs():
    global _fsrs
    if _fsrs is None:
        from fsrs import Card as _FSCard
        from fsrs import Rating as _FSRating
        from fsrs import ReviewLog as _FSReviewLog
        from fsrs import Scheduler as _FSScheduler
        from fsrs import State as _FSState

        _fsrs = (
            _FSCard,
            _FSRating,
            _FSReviewLog,
            _FSScheduler,
            _FSState,
        )
    return _fsrs


class FSRSScheduler:
    """Concrete scheduler backed by the ``fsrs`` library (py-fsrs ≥ 5)."""

    # Defaults from ROADMAP M3
    DEFAULT_NEW_PER_DAY = 15
    DEFAULT_REVIEWS_PER_DAY = 120

    def __init__(
        self,
        desired_retention: float = 0.9,
        maximum_interval: int = 36500,
        learning_steps: tuple[float, ...] | None = None,
    ) -> None:
        _FSCard, _FSRating, _FSReviewLog, _FSScheduler, _FSState = _get_fsrs()  # noqa: N806

        kwargs: dict = {
            "desired_retention": desired_retention,
            "maximum_interval": maximum_interval,
        }
        if learning_steps is not None:
            kwargs["learning_steps"] = learning_steps

        self._scheduler = _FSScheduler(**kwargs)
        self._fs_card = _FSCard
        self._fs_rating = _FSRating
        self._fs_state = _FSState

        # Rating mapping: our Rating enum → fsrs Rating enum
        self._rating_map: dict[Rating, _FSRating] = {
            Rating.AGAIN: _FSRating.Again,
            Rating.HARD: _FSRating.Hard,
            Rating.GOOD: _FSRating.Good,
            Rating.EASY: _FSRating.Easy,
        }

    # ---- Protocol methods ----

    def new_card(self) -> CardDict:
        card = self._fs_card()
        return card.to_dict()

    def review(
        self,
        card: CardDict,
        rating: Rating,
        now: datetime | None = None,
    ) -> ReviewResult:
        fs_card = self._fs_card.from_dict(card)
        if now is not None:
            if now.tzinfo is None:
                now = now.replace(tzinfo=UTC)

        updated, _fs_log = self._scheduler.review_card(
            fs_card,
            self._rating_map[rating],
            review_datetime=now,
        )

        updated_dict = updated.to_dict()

        # Compute scheduled_days from the card's own due / last_review
        due_dt = datetime.fromisoformat(updated_dict["due"])
        last_review_str = updated_dict.get("last_review")
        if last_review_str:
            last_review_dt = datetime.fromisoformat(last_review_str)
            scheduled_days = (due_dt - last_review_dt).total_seconds() / 86400
            prev_last = card.get("last_review")
            if prev_last:
                elapsed_days = (
                    last_review_dt - datetime.fromisoformat(prev_last)
                ).total_seconds() / 86400
            else:
                elapsed_days = 0.0
        else:
            scheduled_days = 0.0
            elapsed_days = 0.0

        return ReviewResult(
            card=updated_dict,
            rating=rating,
            scheduled_days=scheduled_days,
            elapsed_days=elapsed_days,
        )

    def retrievability(self, card: CardDict, now: datetime | None = None) -> float | None:
        fs_card = self._fs_card.from_dict(card)
        if now is not None and now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return self._scheduler.get_card_retrievability(fs_card, current_datetime=now)

    @staticmethod
    def state_from_fsrs(fsrs_state: int) -> CardState:
        mapping = {
            1: CardState.LEARNING,
            2: CardState.REVIEW,
            3: CardState.RELEARNING,
        }
        return mapping.get(fsrs_state, CardState.LEARNING)

    # ---- Helpers for DB layer ----

    @staticmethod
    def days_until_due(card: CardDict, now: datetime | None = None) -> int | None:
        """Days from *now* until the card's ``due`` date.  Negative = overdue."""
        if now is None:
            now = datetime.now(UTC)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        due_str = card.get("due")
        if due_str is None:
            return None
        # fsrs stores ISO-8601 with tz
        due_dt = datetime.fromisoformat(due_str)
        delta = due_dt - now
        return delta.days

    def sync_user_settings(self, settings_json: str | None) -> None:
        """Apply user-settable caps from JSON.  Does NOT persist back."""
        import json

        if not settings_json:
            return
        try:
            cfg = json.loads(settings_json)
        except (json.JSONDecodeError, TypeError):
            return

        desired_retention = cfg.get("desired_retention")
        if isinstance(desired_retention, (int, float)) and 0.5 <= desired_retention <= 0.99:
            # Re-initialise scheduler with new retention target
            self.__init__(desired_retention=desired_retention)  # type: ignore[misc]
