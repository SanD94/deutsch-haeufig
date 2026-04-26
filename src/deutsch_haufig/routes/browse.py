"""Browse route — list seeded words with vocabeo-style filters.

Filters (all optional, all combined with AND):

  ?level=A1            CEFR level
  ?pos=verb            part of speech
  ?category=…          (no-op for now: vocabeo categories live on the
                       JSONL; the seeded Word rows don't carry the field
                       yet, so this filter is reserved for M2.)
  ?frequency=5         frequency bucket 1..5
  ?q=geb               case-insensitive substring on lemma
  ?limit=200           page size (default 200, max 1000)
  ?offset=0            offset for pagination
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from deutsch_haufig.db import get_session
from deutsch_haufig.models import Word
from deutsch_haufig.templating import templates

router = APIRouter()


# Categories surfaced on the page; sourced from vocabeo's filter set.
KNOWN_CATEGORIES = (
    "Common verbs",
    "Common nouns",
    "Common adjectives",
    "Colors",
    "Numbers",
)
KNOWN_LEVELS = ("A1", "A2", "B1")
KNOWN_POS = ("noun", "verb", "adj", "adv", "prep", "conj", "pron", "interj", "num")
KNOWN_FREQUENCIES = (5, 4, 3, 2, 1)


SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/browse", response_class=HTMLResponse)
def browse(
    request: Request,
    session: SessionDep,
    level: Annotated[str | None, Query()] = None,
    pos: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    frequency: Annotated[int | None, Query(ge=1, le=5)] = None,
    q: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HTMLResponse:
    stmt = select(Word)
    count_stmt = select(func.count(Word.id))
    if level:
        stmt = stmt.where(Word.level == level)
        count_stmt = count_stmt.where(Word.level == level)
    if pos:
        stmt = stmt.where(Word.pos == pos)
        count_stmt = count_stmt.where(Word.pos == pos)
    if category:
        # Source-ref carries the slug, e.g. "vocabeo:100-most-common-german-nouns#3".
        cat_to_slug = {
            "Common verbs": "100-most-common-german-verbs",
            "Common nouns": "100-most-common-german-nouns",
            "Common adjectives": "100-most-common-german-adjectives",
            "Colors": "colors-in-german",
            "Numbers": "numbers-in-german",
        }
        slug = cat_to_slug.get(category)
        if slug is not None:
            like = f"vocabeo:{slug}#%"
            stmt = stmt.where(Word.source_ref.like(like))
            count_stmt = count_stmt.where(Word.source_ref.like(like))
    if frequency is not None:
        stmt = stmt.where(Word.frequency == frequency)
        count_stmt = count_stmt.where(Word.frequency == frequency)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Word.lemma).like(like))
        count_stmt = count_stmt.where(func.lower(Word.lemma).like(like))

    total = session.execute(count_stmt).scalar_one()
    stmt = (
        stmt.order_by(
            Word.frequency.desc().nullslast(),
            Word.lemma.asc(),
        )
        .offset(offset)
        .limit(limit)
    )
    words = session.execute(stmt).scalars().all()

    return templates.TemplateResponse(
        request,
        "browse.html",
        {
            "title": "Browse",
            "words": words,
            "total": total,
            "filters": {
                "level": level,
                "pos": pos,
                "category": category,
                "frequency": frequency,
                "q": q,
            },
            "limit": limit,
            "offset": offset,
            "known_levels": KNOWN_LEVELS,
            "known_pos": KNOWN_POS,
            "known_categories": KNOWN_CATEGORIES,
            "known_frequencies": KNOWN_FREQUENCIES,
        },
    )
