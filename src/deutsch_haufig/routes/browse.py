"""Browse route — list seeded words with the M1 vocabeo-style filters.

Filters (all optional, all combined with AND):

  ?level=A1       CEFR level (A1 / A2 / B1)
  ?pos=verb       part of speech (noun, verb, adj, adv, prep, conj, pron, interj, num)
  ?frequency=5    frequency bucket 1..5 (5 = most frequent)
  ?q=geb          case-insensitive substring on lemma
  ?limit=200      page size (default 200, max 1000)
  ?offset=0       offset for pagination
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from deutsch_haufig.db import get_session
from deutsch_haufig.ingest.vocabeo import KNOWN_POS_TAGS
from deutsch_haufig.models import Word
from deutsch_haufig.templating import templates

router = APIRouter()

KNOWN_LEVELS = ("A1", "A2", "B1")
KNOWN_POS = KNOWN_POS_TAGS
KNOWN_FREQUENCIES = (5, 4, 3, 2, 1)


SessionDep = Annotated[Session, Depends(get_session)]


def _parse_frequency(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


@router.get("/browse", response_class=HTMLResponse)
def browse(
    request: Request,
    session: SessionDep,
    level: Annotated[str | None, Query()] = None,
    pos: Annotated[str | None, Query()] = None,
    frequency: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HTMLResponse:
    freq = _parse_frequency(frequency)
    if freq is not None and not (1 <= freq <= 5):
        raise HTTPException(422, "frequency must be 1-5")
    stmt = select(Word)
    count_stmt = select(func.count(Word.id))
    if level:
        stmt = stmt.where(Word.level == level)
        count_stmt = count_stmt.where(Word.level == level)
    if pos:
        stmt = stmt.where(Word.pos == pos)
        count_stmt = count_stmt.where(Word.pos == pos)
    if freq is not None and not (1 <= freq <= 5):
        raise HTTPException(422, "frequency must be 1-5")
    if freq is not None:
        stmt = stmt.where(Word.frequency == freq)
        count_stmt = count_stmt.where(Word.frequency == freq)
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
                "frequency": freq,
                "q": q,
            },
            "limit": limit,
            "offset": offset,
            "known_levels": KNOWN_LEVELS,
            "known_pos": KNOWN_POS,
            "known_frequencies": KNOWN_FREQUENCIES,
        },
    )
