"""Word detail route — show definition, examples, and on-demand dialogue.

M2: Monolingual definition from DWDS, with fallback for missing definitions.
M4: On-demand mini-dialogue via LLM, cached in Dialogue table.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from deutsch_haufig.db import get_session
from deutsch_haufig.dialogue import (
    DialogueGenerationError,
    provider_from_config,
)
from deutsch_haufig.models import Collocation, Conjugation, Dialogue, Example, Sense, Word
from deutsch_haufig.schemas import WordDetail
from deutsch_haufig.templating import templates

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


def _dialogue_provider_enabled() -> bool:
    """Check if a real dialogue provider is configured in opencode.json."""
    from deutsch_haufig.config import get_dialogue_provider_config  # noqa: PLC0415

    return get_dialogue_provider_config() is not None


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
        # Check for existing dialogues
        dialogues = (
            session.execute(
                select(Dialogue).where(Dialogue.sense_id == s.id)
                .order_by(Dialogue.created_at.desc())
            )
            .scalars()
            .all()
        )
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
                "dialogues": [
                    {
                        "id": d.id,
                        "text_de": d.text_de,
                        "generated_by": d.generated_by,
                        "created_at": d.created_at.isoformat() if d.created_at else None,
                    }
                    for d in dialogues
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
            "dialogue_enabled": _dialogue_provider_enabled(),
            "collocations": _get_collocations(session, word_id),
            "conjugations": _get_conjugations(session, word, word_id),
        },
    )


def _get_collocations(session: Session, word_id: int) -> list[dict]:
    entries = (
        session.execute(
            select(Collocation)
            .where(Collocation.word_id == word_id)
            .order_by(Collocation.frequency.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    return [
        {"collocate": e.collocate, "category": e.category, "frequency": e.frequency}
        for e in entries
    ]


def _get_conjugations(session: Session, word: Word, word_id: int) -> list[dict]:
    if word.pos != "verb":
        return []
    entries = (
        session.execute(
            select(Conjugation).where(Conjugation.word_id == word_id).order_by(Conjugation.id)
        )
        .scalars()
        .all()
    )
    grouped: dict[str, list] = {}
    for e in entries:
        grouped.setdefault(e.tense, []).append({"pronoun": e.pronoun, "form": e.form})
    return [{"tense": tense, "rows": rows} for tense, rows in grouped.items()]


@router.post("/word/{word_id}/dialogue/{sense_id}")
async def generate_dialogue(
    request: Request,
    session: SessionDep,
    word_id: int,
    sense_id: int,
) -> JSONResponse:
    """Generate and cache a dialogue for the given sense. Returns HTML partial."""
    word = session.get(Word, word_id)
    if word is None:
        raise HTTPException(404, "Word not found")

    sense = session.get(Sense, sense_id)
    if sense is None or sense.word_id != word_id:
        raise HTTPException(404, "Sense not found")

    # Check for existing cached dialogues
    existing = (
        session.execute(
            select(Dialogue)
            .where(Dialogue.sense_id == sense_id)
            .order_by(Dialogue.created_at.desc())
        )
        .scalars()
        .all()
    )
    if existing:
        return JSONResponse(
            content={
                "html": _render_dialogue_partial(word.lemma, existing[0]),
                "has_dialogue": True,
            }
        )

    # Generate
    provider = provider_from_config()
    definition_de = sense.definition_de or "(keine Definition)"
    try:
        text = await provider.generate(lemma=word.lemma, definition_de=definition_de)
    except DialogueGenerationError:
        return JSONResponse(
            content={
                "html": "<p class='error'>Dialog konnte nicht generiert werden.</p>",
                "has_dialogue": False,
            },
            status_code=503,
        )

    dialogue = Dialogue(
        sense_id=sense_id,
        text_de=text,
        generated_by=f"opencode:{_dialogue_model()}",
    )
    session.add(dialogue)
    session.commit()
    session.refresh(dialogue)

    return JSONResponse(
        content={
            "html": _render_dialogue_partial(word.lemma, dialogue),
            "has_dialogue": True,
        }
    )


def _dialogue_model() -> str:
    from deutsch_haufig.config import get_dialogue_provider_config  # noqa: PLC0415

    cfg = get_dialogue_provider_config()
    return cfg["model"] if cfg else "unknown"


def _render_dialogue_partial(lemma: str, dialogue: Dialogue) -> str:
    """Render a dialogue as an HTML string for HTMX injection."""
    lines = dialogue.text_de.strip().split("\n")
    lines_html = "".join(
        f"<p class='dialogue-line'>{line.strip()}</p>" for line in lines if line.strip()
    )
    return f"""<div class="dialogue-box" id="dialogue-{dialogue.sense_id}">
  <div class="dialogue-header">
    <span class="dialogue-label">Mini-Dialog</span>
    <span class="dialogue-source">{dialogue.generated_by}</span>
  </div>
  <div class="dialogue-body">
    {lines_html}
  </div>
</div>"""


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
