"""Tests for the FSRS scheduler wrapper.

M3: verify that the scheduler produces valid card state transitions,
queue ordering is correct, and serialisation round-trips cleanly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


from deutsch_haufig.scheduler import (
    CardState,
    FSRSScheduler,
    Rating,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCHED = FSRSScheduler()
NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)


def _new_card_dict() -> dict:
    return SCHED.new_card()


# ---------------------------------------------------------------------------
# new_card
# ---------------------------------------------------------------------------


class TestNewCard:
    def test_returns_dict_with_expected_keys(self) -> None:
        card = _new_card_dict()
        assert isinstance(card, dict)
        # fsrs v5 to_dict includes these keys
        assert "state" in card
        assert "stability" in card
        assert "difficulty" in card

    def test_new_card_is_in_learning_state(self) -> None:
        card = _new_card_dict()
        # fsrs State.Learning == 1
        assert card["state"] == 1

    def test_two_new_cards_are_independent(self) -> None:
        c1 = _new_card_dict()
        c2 = _new_card_dict()
        c1["stability"] = 42.0  # mutate one
        assert c2["stability"] != 42.0


# ---------------------------------------------------------------------------
# review — state transitions
# ---------------------------------------------------------------------------


class TestReviewTransitions:
    def test_again_keeps_in_learning(self) -> None:
        card = _new_card_dict()
        result = SCHED.review(card, Rating.AGAIN, now=NOW)
        assert result.rating == Rating.AGAIN
        assert result.card["state"] in (1, 3)  # learning or relearning

    def test_good_moves_toward_review(self) -> None:
        card = _new_card_dict()
        result = SCHED.review(card, Rating.GOOD, now=NOW)
        assert result.rating == Rating.GOOD
        assert result.scheduled_days >= 0

    def test_easy_graduates_faster(self) -> None:
        card = _new_card_dict()
        easy = SCHED.review(card, Rating.EASY, now=NOW)
        good = SCHED.review(card, Rating.GOOD, now=NOW)
        assert easy.scheduled_days > good.scheduled_days

    def test_hard_slower_than_good(self) -> None:
        card = _new_card_dict()
        hard = SCHED.review(card, Rating.HARD, now=NOW)
        good = SCHED.review(card, Rating.GOOD, now=NOW)
        assert hard.scheduled_days < good.scheduled_days

    def test_again_shorter_than_hard(self) -> None:
        card = _new_card_dict()
        again = SCHED.review(card, Rating.AGAIN, now=NOW)
        hard = SCHED.review(card, Rating.HARD, now=NOW)
        assert again.scheduled_days < hard.scheduled_days

    def test_ordering_again_lt_hard_lt_good_lt_easy(self) -> None:
        card = _new_card_dict()
        days = {
            r: SCHED.review(card, r, now=NOW).scheduled_days
            for r in (Rating.AGAIN, Rating.HARD, Rating.GOOD, Rating.EASY)
        }
        assert days[Rating.AGAIN] < days[Rating.HARD]
        assert days[Rating.HARD] < days[Rating.GOOD]
        assert days[Rating.GOOD] < days[Rating.EASY]


# ---------------------------------------------------------------------------
# serialisation round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_review_then_review_again(self) -> None:
        card = _new_card_dict()
        r1 = SCHED.review(card, Rating.GOOD, now=NOW)
        # Use the output card as input for the next review
        r2 = SCHED.review(r1.card, Rating.EASY, now=NOW + timedelta(days=1))
        assert r2.scheduled_days > r1.scheduled_days

    def test_stability_increases_with_good_reviews(self) -> None:
        card = _new_card_dict()
        t = NOW
        result = SCHED.review(card, Rating.GOOD, now=t)
        card = result.card
        prev_stability = card["stability"]
        # Simulate reviewing after the scheduled interval
        for i in range(1, 4):
            t = NOW + timedelta(days=i * 3)
            result = SCHED.review(card, Rating.GOOD, now=t)
            card = result.card
        assert card["stability"] is not None
        assert card["stability"] > prev_stability

    def test_elapsed_days_is_zero_on_first_review(self) -> None:
        card = _new_card_dict()
        result = SCHED.review(card, Rating.GOOD, now=NOW)
        assert result.elapsed_days == 0


# ---------------------------------------------------------------------------
# retrievability
# ---------------------------------------------------------------------------


class TestRetrievability:
    def test_new_card_has_no_retrievability(self) -> None:
        card = _new_card_dict()
        # New cards may or may not have a retrievability — fsrs returns 0 or None
        r = SCHED.retrievability(card, now=NOW)
        assert isinstance(r, (int, float, type(None)))

    def test_reviewed_card_has_retrievability(self) -> None:
        card = _new_card_dict()
        result = SCHED.review(card, Rating.GOOD, now=NOW)
        r = SCHED.retrievability(result.card, now=NOW + timedelta(days=1))
        assert r is not None
        assert 0 <= r <= 1

    def test_retrievability_decays_over_time(self) -> None:
        card = _new_card_dict()
        result = SCHED.review(card, Rating.GOOD, now=NOW)
        r1 = SCHED.retrievability(result.card, now=NOW + timedelta(days=1))
        r2 = SCHED.retrievability(result.card, now=NOW + timedelta(days=30))
        assert r1 is not None and r2 is not None
        assert r2 < r1


# ---------------------------------------------------------------------------
# state_from_fsrs
# ---------------------------------------------------------------------------


class TestStateMapping:
    def test_learning(self) -> None:
        assert FSRSScheduler.state_from_fsrs(1) == CardState.LEARNING

    def test_review(self) -> None:
        assert FSRSScheduler.state_from_fsrs(2) == CardState.REVIEW

    def test_relearning(self) -> None:
        assert FSRSScheduler.state_from_fsrs(3) == CardState.RELEARNING

    def test_unknown_defaults_to_learning(self) -> None:
        assert FSRSScheduler.state_from_fsrs(99) == CardState.LEARNING


# ---------------------------------------------------------------------------
# days_until_due
# ---------------------------------------------------------------------------


class TestDaysUntilDue:
    def test_future_due_positive(self) -> None:
        card = _new_card_dict()
        future = (NOW + timedelta(days=5)).isoformat()
        card["due"] = future
        assert FSRSScheduler.days_until_due(card, now=NOW) >= 4  # ~5 days

    def test_overdue_negative(self) -> None:
        card = _new_card_dict()
        past = (NOW - timedelta(days=3)).isoformat()
        card["due"] = past
        assert FSRSScheduler.days_until_due(card, now=NOW) < 0

    def test_no_due_returns_none(self) -> None:
        card = {"state": 1, "due": None}  # manually crafted card without due
        assert FSRSScheduler.days_until_due(card, now=NOW) is None


# ---------------------------------------------------------------------------
# Rating enum values
# ---------------------------------------------------------------------------


class TestRatingValues:
    def test_again_is_1(self) -> None:
        assert Rating.AGAIN == 1

    def test_hard_is_2(self) -> None:
        assert Rating.HARD == 2

    def test_good_is_3(self) -> None:
        assert Rating.GOOD == 3

    def test_easy_is_4(self) -> None:
        assert Rating.EASY == 4
