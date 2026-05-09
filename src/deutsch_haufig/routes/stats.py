"""Stats & insights route (M7).

- ``GET /stats`` — dashboard with heatmap, retention by level/category,
  hardest words, forecast, per-card history
- ``GET /stats/csv`` — CSV export of all review logs
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import Session

from deutsch_haufig.db import get_session
from deutsch_haufig.models import ReviewCard, ReviewLog, Sense, Word
from deutsch_haufig.routes.learn import _ensure_user
from deutsch_haufig.templating import templates

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/stats", response_class=HTMLResponse)
def stats_page(
    request: Request,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
):
    user, _ = _ensure_user(session, request)
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    # --- Heatmap data (reviews per day) ---
    heatmap_rows = (
        session.execute(
            select(
                func.date(ReviewLog.ts).label("day"),
                func.count(ReviewLog.id).label("count"),
            )
            .join(ReviewCard, ReviewCard.id == ReviewLog.card_id)
            .where(ReviewCard.user_id == user.id)
            .where(ReviewLog.ts >= cutoff)
            .group_by(func.date(ReviewLog.ts))
            .order_by(func.date(ReviewLog.ts))
        )
        .all()
    )
    heatmap = {row.day: row.count for row in heatmap_rows}

    # Build full date range
    heatmap_dates = []
    for i in range(days):
        d = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        heatmap_dates.append({"date": d, "count": heatmap.get(d, 0)})

    # --- Retention by level ---
    level_rows = (
        session.execute(
            select(
                Word.level,
                func.count(ReviewLog.id).label("total"),
                func.sum(case((literal(1), ReviewLog.rating >= 3), else_=literal(0))).label("good"),
            )
            .select_from(ReviewLog)
            .join(ReviewCard, ReviewCard.id == ReviewLog.card_id)
            .join(Sense, Sense.id == ReviewCard.sense_id)
            .join(Word, Word.id == Sense.word_id)
            .where(ReviewCard.user_id == user.id)
            .where(ReviewLog.ts >= cutoff)
            .group_by(Word.level)
            .order_by(Word.level)
        )
        .all()
    )
    level_retention = []
    for row in level_rows:
        level = row.level or "none"
        pct = round(row.good / row.total * 100, 1) if row.total > 0 else 0
        level_retention.append({
            "level": level,
            "total": row.total,
            "good": row.good,
            "pct": pct,
        })

    # --- Retention by category (pos) ---
    pos_rows = (
        session.execute(
            select(
                Word.pos,
                func.count(ReviewLog.id).label("total"),
                func.sum(case((literal(1), ReviewLog.rating >= 3), else_=literal(0))).label("good"),
            )
            .select_from(ReviewLog)
            .join(ReviewCard, ReviewCard.id == ReviewLog.card_id)
            .join(Sense, Sense.id == ReviewCard.sense_id)
            .join(Word, Word.id == Sense.word_id)
            .where(ReviewCard.user_id == user.id)
            .where(ReviewLog.ts >= cutoff)
            .group_by(Word.pos)
            .order_by(Word.pos)
        )
        .all()
    )
    pos_retention = []
    for row in pos_rows:
        pct = round(row.good / row.total * 100, 1) if row.total > 0 else 0
        pos_retention.append({
            "pos": row.pos,
            "total": row.total,
            "good": row.good,
            "pct": pct,
        })

    # --- Hardest words (lowest retention) ---
    hardest_rows = (
        session.execute(
            select(
                Word.lemma,
                Word.article,
                Word.pos,
                Word.level,
                func.count(ReviewLog.id).label("total"),
                func.sum(case((literal(1), ReviewLog.rating >= 3), else_=literal(0))).label("good"),
            )
            .select_from(ReviewLog)
            .join(ReviewCard, ReviewCard.id == ReviewLog.card_id)
            .join(Sense, Sense.id == ReviewCard.sense_id)
            .join(Word, Word.id == Sense.word_id)
            .where(ReviewCard.user_id == user.id)
            .where(ReviewLog.ts >= cutoff)
            .group_by(Word.id, Word.lemma, Word.article, Word.pos, Word.level)
            .having(func.count(ReviewLog.id) >= 2)  # at least 2 reviews
            .order_by(
                func.sum(case((literal(1), ReviewLog.rating >= 3), else_=literal(0)))
                / func.count(ReviewLog.id)
            )
            .limit(20)
        )
        .all()
    )
    hardest_words = []
    for row in hardest_rows:
        pct = round(row.good / row.total * 100, 1) if row.total > 0 else 0
        hardest_words.append({
            "lemma": row.lemma,
            "article": row.article,
            "pos": row.pos,
            "level": row.level,
            "total": row.total,
            "good": row.good,
            "pct": pct,
        })

    # --- Forecast (cards due per day for next 14 days) ---
    forecast = []
    for i in range(14):
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=i)
        day_end = day_start + timedelta(days=1)
        count = session.execute(
            select(func.count(ReviewCard.id))
            .where(ReviewCard.user_id == user.id)
            .where(ReviewCard.due >= day_start)
            .where(ReviewCard.due < day_end)
        ).scalar_one()
        forecast.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "count": count,
        })

    # --- Per-card history ---
    cards = (
        session.execute(
            select(ReviewCard)
            .where(ReviewCard.user_id == user.id)
            .order_by(ReviewCard.last_review.desc().nullslast())
            .limit(50)
        )
        .scalars()
        .all()
    )
    card_history = []
    for card in cards:
        sense = session.get(Sense, card.sense_id)
        if sense is None:
            continue
        word = session.get(Word, sense.word_id)
        logs = (
            session.execute(
                select(ReviewLog).where(ReviewLog.card_id == card.id).order_by(ReviewLog.ts.desc())
            )
            .scalars()
            .all()
        )
        card_history.append({
            "card_id": card.id,
            "lemma": word.lemma if word else "?",
            "article": word.article if word else None,
            "sense_definition": sense.definition_de,
            "state": card.state,
            "stability": round(card.stability, 1) if card.stability else None,
            "difficulty": round(card.difficulty, 1) if card.difficulty else None,
            "due": card.due.isoformat() if card.due else None,
            "reps": card.reps,
            "lapses": card.lapses,
            "logs": [
                {
                    "ts": log.ts.isoformat() if log.ts else None,
                    "rating": log.rating,
                    "elapsed_days": log.elapsed_days,
                    "scheduled_days": log.scheduled_days,
                }
                for log in logs
            ],
        })

    # --- Summary stats ---
    total_reviews = session.execute(
        select(func.count(ReviewLog.id))
        .join(ReviewCard, ReviewCard.id == ReviewLog.card_id)
        .where(ReviewCard.user_id == user.id)
    ).scalar_one()

    total_cards = session.execute(
        select(func.count(ReviewCard.id)).where(ReviewCard.user_id == user.id)
    ).scalar_one()

    due_now = session.execute(
        select(func.count(ReviewCard.id))
        .where(ReviewCard.user_id == user.id)
        .where(ReviewCard.due <= now)
        .where(ReviewCard.state != "new")
    ).scalar_one()

    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "title": "Stats",
            "days": days,
            "heatmap": heatmap_dates,
            "level_retention": level_retention,
            "pos_retention": pos_retention,
            "hardest_words": hardest_words,
            "forecast": forecast,
            "card_history": card_history,
            "total_reviews": total_reviews,
            "total_cards": total_cards,
            "due_now": due_now,
        },
    )


@router.get("/stats/csv")
def stats_csv(
    request: Request,
    session: SessionDep,
):
    user, _ = _ensure_user(session, request)

    rows = (
        session.execute(
            select(ReviewLog, ReviewCard, Sense, Word)
            .select_from(ReviewLog)
            .join(ReviewCard, ReviewCard.id == ReviewLog.card_id)
            .join(Sense, Sense.id == ReviewCard.sense_id)
            .join(Word, Word.id == Sense.word_id)
            .where(ReviewCard.user_id == user.id)
            .order_by(ReviewLog.ts)
        )
        .all()
    )

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["lemma", "article", "pos", "level", "definition", "ts", "rating",
                 "elapsed_days", "scheduled_days", "card_state", "reps", "lapses"])

    for log, card, sense, word in rows:
        w.writerow([
            word.lemma,
            word.article or "",
            word.pos,
            word.level or "",
            sense.definition_de or "",
            log.ts.isoformat() if log.ts else "",
            log.rating,
            log.elapsed_days or "",
            log.scheduled_days or "",
            card.state,
            card.reps,
            card.lapses,
        ])

    return PlainTextResponse(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=deutsch-haufig-progress.csv"},
    )
