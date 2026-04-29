"""Word detail route — show definition, examples, and corpus samples.

M2: Monolingual definition from DWDS, with fallback for missing definitions.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from deutsch_haufig.db import get_session
from deutsch_haufig.models import Example, Sense, Word
from deutsch_haufig.schemas import WordDetail
from deutsch_haufig.templating import templates

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/word/{word_id}", response_class=HTMLResponse)
def word_detail(
    request: Request,
    session: SessionDep,
    word_id: int,
) -> HTMLResponse:
    word = session.get(Word, word_id)
    if word is None:
        raise HTTPException(404, "Word not found")

    senses = (
        session.execute(
            select(Sense)
            .where(Sense.word_id == word_id)
            .order_by(Sense.order)
            .options(joinedload(Sense.examples))
        )
        .scalars()
        .unique()
        .all()
    )

    has_any_def = any(s.definition_de for s in senses)

    word_data = {
        "id": word.id,
        "lemma": word.lemma,
        "article": word.article,
        "pos": word.pos,
        "level": word.level,
        "frequency": word.frequency,
    }

    sense_list = []
    for s in senses:
        examples = session.execute(select(Example).where(Example.sense_id == s.id)).scalars().all()
        sense_list.append(
            {
                "id": s.id,
                "order": s.order,
                "definition_de": s.definition_de,
                "register": s.register,
                "domain": s.domain,
                "has_definition": bool(s.definition_de),
                "examples": [
                    {"id": e.id, "text_de": e.text_de, "source": e.source} for e in examples
                ],
            }
        )

    return templates.TemplateResponse(
        request,
        "word.html",
        {
            "title": word.lemma,
            "word": word_data,
            "senses": sense_list,
            "has_any_definition": has_any_def,
            "dwds_attribution": "DWDS — Digitales Wörterbuch der deutschen Sprache",
        },
    )


@router.get("/api/word/{word_id}", response_model=WordDetail)
def word_api(
    session: SessionDep,
    word_id: int,
) -> WordDetail:
    """JSON API endpoint for word details."""
    word = session.get(Word, word_id)
    if word is None:
        raise HTTPException(404, "Word not found")

    senses = (
        session.execute(
            select(Sense)
            .where(Sense.word_id == word_id)
            .order_by(Sense.order)
            .options(joinedload(Sense.examples))
        )
        .scalars()
        .unique()
        .all()
    )

    return WordDetail(
        id=word.id,
        lemma=word.lemma,
        article=word.article,
        pos=word.pos,
        level=word.level,
        frequency=word.frequency,
        senses=[
            {
                "id": s.id,
                "order": s.order,
                "definition_de": s.definition_de or "",
                "register": s.register,
                "domain": s.domain,
                "examples": [{"text_de": e.text_de, "source": e.source} for e in s.examples],
            }
            for s in senses
        ],
    )
