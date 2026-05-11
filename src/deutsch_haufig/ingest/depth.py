"""Pipeline for enriching M8 content depth (collocations, conjugations).

CLI subcommands:
  collocations  Extract collocations from cached DWDS pages
  conjugations  Fetch verb conjugations from verbformen.de
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from deutsch_haufig.db import SessionLocal, init_db
from deutsch_haufig.models import Collocation, Conjugation, Word

logger = logging.getLogger(__name__)


def enrich_collocations() -> int:
    """Extract collocations from cached DWDS HTML for all words."""
    init_db()
    from deutsch_haufig.ingest.collocations import (  # noqa: PLC0415
        extract_for_lemma,
    )

    total = 0
    with SessionLocal() as session:
        words = session.execute(select(Word.id, Word.lemma, Word.pos)).all()
        # Check which already have collocations
        existing = set(
            row[0] for row in session.execute(select(Collocation.word_id).distinct()).all()
        )

    for word_id, lemma, pos in words:
        if word_id in existing:
            continue

        entries = extract_for_lemma(lemma, pos)
        if not entries:
            continue

        with SessionLocal() as session:
            for entry in entries:
                session.add(
                    Collocation(
                        word_id=word_id,
                        collocate=entry.collocate,
                        category=entry.category,
                        frequency=entry.frequency,
                    )
                )
            session.commit()
            total += len(entries)

    return total


async def enrich_conjugations(limit: int | None = None) -> int:
    """Fetch verb conjugations from verbformen.de."""
    init_db()
    from deutsch_haufig.ingest.verbformen import fetch_conjugations  # noqa: PLC0415

    total = 0
    count = 0
    with SessionLocal() as session:
        verbs = (
            session.execute(select(Word).where(Word.pos == "verb").order_by(Word.frequency.desc()))
            .scalars()
            .all()
        )

    for word in verbs:
        if limit is not None and count >= limit:
            break

        # Check existing
        with SessionLocal() as s:
            existing = s.execute(
                select(Conjugation).where(Conjugation.word_id == word.id).limit(1)
            ).scalar_one_or_none()
            if existing:
                count += 1
                continue

        result = await fetch_conjugations(word.lemma)
        if result is None:
            count += 1
            continue

        with SessionLocal() as session:
            for entry in result:
                session.add(
                    Conjugation(
                        word_id=word.id,
                        tense=entry.tense,
                        pronoun=entry.pronoun,
                        form=entry.form,
                    )
                )
            session.commit()
            total += len(result)
            count += 1

        import asyncio

        await asyncio.sleep(0.3)

    return total


def main() -> None:
    """CLI entry: ``uv run enrich-depth``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="M8 content depth enrichment")
    sub = parser.add_subparsers(dest="cmd")

    p_coll = sub.add_parser("collocations", help="Extract collocations from cached DWDS")
    p_coll.add_argument("--limit", type=int, default=None)

    p_conj = sub.add_parser("conjugations", help="Fetch verb conjugations from verbformen.de")
    p_conj.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()

    if args.cmd == "collocations":
        total = enrich_collocations()
        print(f"collocations: {total} entries extracted")
    elif args.cmd == "conjugations":
        total = asyncio.run(enrich_conjugations(limit=args.limit))
        print(f"conjugations: {total} entries fetched")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
