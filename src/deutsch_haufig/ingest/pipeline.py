"""Ingest CLI for M1-DWDS seed + M2 enrichment.

Subcommands:

  goethe  Fetch and seed DWDS Goethe-Zertifikat word lists (A1, A2, B1)
          (default when no subcommand is given).
  enrich  Fetch DWDS definitions + examples + optional IPA.
  cached-enrich  Enrich from local DWDS cache only (no HTTP).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from deutsch_haufig.db import SessionLocal, init_db
from deutsch_haufig.ingest.b2 import clear_existing_b2, persist, read_candidates
from deutsch_haufig.ingest.dwds import (
    DWDSEntry,
)
from deutsch_haufig.ingest.goethe import (
    GoetheEntry,
    fetch_all_goethe_lists,
)
from deutsch_haufig.models import Example, Sense, Word

logger = logging.getLogger(__name__)


# --- goethe (CSV → SQLite) ---------------------------------------------------


def _normalize_level_for_duplicates(existing: Word | None, new_level: str | None) -> str | None:
    if existing is None or not existing.level:
        return new_level
    if new_level is None:
        return existing.level
    level_order = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5}
    existing_rank = level_order.get(existing.level, 99)
    new_rank = level_order.get(new_level, 99)
    return existing.level if existing_rank <= new_rank else new_level


def upsert_goethe_word(session: Session, entry: GoetheEntry) -> bool:
    """Insert or update a Word from a Goethe list entry.

    Returns True on insert, False on update.
    """
    session.commit()
    stmt = (
        select(Word)
        .where(
            Word.lemma == entry.lemma,
            Word.pos == entry.pos,
        )
        .limit(1)
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        level = entry.level
        session.add(
            Word(
                lemma=entry.lemma,
                article=entry.article if entry.pos == "noun" else None,
                pos=entry.pos,
                level=level,
                frequency=0,
                source_ref=entry.source_ref,
            )
        )
        session.commit()
        return True
    existing.level = _normalize_level_for_duplicates(existing, entry.level)
    if entry.pos == "noun" and entry.article:
        existing.article = entry.article
    # Only update source_ref when the entry's level is the same as the
    # existing level, or when the existing level was null. This prevents
    # overwriting a lower-level source_ref (e.g. A1) with a higher one (B1).
    if existing.level == entry.level or entry.level is None:
        existing.source_ref = entry.source_ref
    session.commit()
    return False


def seed_goethe(
    entries: dict[str, list[GoetheEntry]],
    *,
    with_frequency: bool = False,
) -> dict[str, tuple[int, int]]:
    """Idempotently upsert Goethe entries into Word. Returns ``{level: (inserted, skipped)}``.

    When ``with_frequency=True``, fetches frequency data from DWDS for each
    newly inserted word and sets ``frequency`` + ``frequency_hits``.
    """
    init_db()
    result: dict[str, tuple[int, int]] = {}
    for level, level_entries in entries.items():
        inserted = skipped = 0
        with SessionLocal() as session:
            for entry in level_entries:
                if upsert_goethe_word(session, entry):
                    inserted += 1
                else:
                    skipped += 1
        result[level] = (inserted, skipped)
    if with_frequency:
        import asyncio

        from deutsch_haufig.ingest.dwds import fetch_frequency

        all_new: list[Word] = []
        with SessionLocal() as session:
            for _level, level_entries in entries.items():
                for entry in level_entries:
                    stmt = (
                        select(Word)
                        .where(
                            Word.lemma == entry.lemma,
                            Word.pos == entry.pos,
                        )
                        .limit(1)
                    )
                    w = session.execute(stmt).scalar_one_or_none()
                    if w:
                        all_new.append(w)

        async def _fetch_all():
            for w in all_new:
                freq_data = await fetch_frequency(w.lemma)
                if freq_data is None:
                    continue
                with SessionLocal() as session:
                    word = session.get(Word, w.id)
                    if word:
                        word.frequency = freq_data.frequency
                        word.frequency_hits = freq_data.hits
                        session.commit()

        asyncio.run(_fetch_all())
    return result


# --- enrich (DWDS definitions + examples) -------------------------------


def _has_definitions(session: Session, word_id: int) -> bool:
    senses = session.execute(select(Sense).where(Sense.word_id == word_id)).scalars().all()
    return any(s.definition_de for s in senses)


def upsert_sense_and_examples(
    session: Session,
    word_id: int,
    entry: DWDSEntry,
) -> int:
    """Upsert senses and examples for a word from DWDS. Returns number of senses added/updated."""
    if entry.not_found:
        existing = session.execute(select(Sense).where(Sense.word_id == word_id)).scalars().all()
        for sense in existing:
            sense.definition_de = None
        return 0

    existing_senses = {
        s.order: s
        for s in session.execute(select(Sense).where(Sense.word_id == word_id)).scalars().all()
    }

    count = 0
    for sense_data in entry.senses:
        if sense_data.order in existing_senses:
            sense = existing_senses[sense_data.order]
            sense.definition_de = sense_data.definition_de
            sense.register = sense_data.register
            sense.domain = sense_data.domain
        else:
            sense = Sense(
                word_id=word_id,
                order=sense_data.order,
                definition_de=sense_data.definition_de,
                register=sense_data.register,
                domain=sense_data.domain,
            )
            session.add(sense)
            session.flush()
            existing_senses[sense_data.order] = sense
        count += 1

        examples = entry.examples.get(sense_data.order, ())
        for ex_data in examples:
            ex = Example(
                sense_id=sense.id,
                text_de=ex_data.text_de,
                source=ex_data.source,
                translation_en=ex_data.translation_en,
            )
            session.add(ex)

    return count


async def enrich_words(
    limit: int | None = None,
    *,
    corpus_api: bool = False,
    with_ipa: bool = False,
    with_frequency: bool = False,
) -> tuple[int, int]:
    """Fetch DWDS for words without definitions, upsert senses + examples.

    When ``corpus_api=True``, also fetch corpus examples via the DWDS korpus API
    for each word (replacing HTML-embedded examples).

    When ``with_ipa=True``, also fetch IPA pronunciation for each word.

    Returns (enriched_count, failed_count).
    """
    init_db()
    enriched = failed = 0

    with SessionLocal() as session:
        words = session.execute(select(Word).where(Word.id > 0).order_by(Word.id)).scalars().all()

    async def word_iter():
        for w in words:
            with SessionLocal() as sess:
                has_def = _has_definitions(sess, w.id)
            if not has_def:
                yield w.id, w.lemma, w.pos

    from deutsch_haufig.ingest.dwds import fetch_words

    async for word_id, entry in fetch_words(word_iter(), limit=limit):
        if entry is None:
            failed += 1
            continue

        with SessionLocal() as session:
            upsert_sense_and_examples(session, word_id, entry)
            session.commit()

        if not entry.not_found:
            enriched += 1
        else:
            failed += 1

        if limit and enriched >= limit:
            break

    if corpus_api:
        c_ok, c_fail = await _enrich_corpus_examples(words)
        enriched += c_ok
        failed += c_fail

    if with_ipa:
        ipa_ok, ipa_fail = await _enrich_ipa(words)
        enriched += ipa_ok
        failed += ipa_fail

    if with_frequency:
        freq_ok, freq_fail = await _enrich_frequency(words)
        enriched += freq_ok
        failed += freq_fail

    return enriched, failed


async def _enrich_corpus_examples(words: list) -> tuple[int, int]:
    from deutsch_haufig.ingest.dwds import fetch_corpus_examples

    ok = fail = 0
    for w in words:
        examples = await fetch_corpus_examples(w.lemma)
        if not examples:
            fail += 1
            continue
        with SessionLocal() as session:
            senses = (
                session.execute(select(Sense).where(Sense.word_id == w.id).order_by(Sense.order))
                .scalars()
                .all()
            )
            for sense in senses[:1]:
                for ex_data in examples:
                    ex = Example(
                        sense_id=sense.id,
                        text_de=ex_data.text_de,
                        source=ex_data.source,
                        translation_en=ex_data.translation_en,
                    )
                    session.add(ex)
            session.commit()
            ok += 1
    return ok, fail


async def _enrich_ipa(words: list) -> tuple[int, int]:
    from deutsch_haufig.ingest.dwds import fetch_ipa

    ok = fail = 0
    for w in words:
        ipa = await fetch_ipa(w.lemma)
        if not ipa:
            fail += 1
            continue
        with SessionLocal() as session:
            word = session.get(Word, w.id)
            if word:
                word.ipa = ipa
                session.commit()
                ok += 1
    return ok, fail


async def _enrich_frequency(words: list) -> tuple[int, int]:
    from deutsch_haufig.ingest.dwds import fetch_frequency

    ok = fail = 0
    for w in words:
        freq_data = await fetch_frequency(w.lemma)
        if freq_data is None:
            fail += 1
            continue
        with SessionLocal() as session:
            word = session.get(Word, w.id)
            if word:
                word.frequency = freq_data.frequency
                word.frequency_hits = freq_data.hits
                session.commit()
                ok += 1
    return ok, fail


def enrich_all_cached() -> tuple[int, int]:
    """Enrich all words that have cached DWDS HTML but no definitions yet.

    Unlike ``enrich_words``, this reads from the local cache only — no HTTP.
    """
    init_db()
    enriched = failed = 0

    with SessionLocal() as session:
        words = session.execute(select(Word).where(Word.id > 0).order_by(Word.id)).scalars().all()

    skip = 0
    for w in words:
        with SessionLocal() as sess:
            senses = sess.execute(select(Sense).where(Sense.word_id == w.id)).scalars().all()
        has_def = any(s.definition_de for s in senses)
        if has_def:
            skip += 1
            continue

        from deutsch_haufig.ingest.dwds import _cache_path  # noqa: PLC0415

        cache_path = _cache_path(w.lemma, w.pos)
        if not cache_path.exists():
            skip += 1
            continue

        from deutsch_haufig.ingest.dwds import parse_entry  # noqa: PLC0415

        html = cache_path.read_text(encoding="utf-8")
        entry = parse_entry(w.lemma, w.pos, html)

        with SessionLocal() as sess:
            upsert_sense_and_examples(sess, w.id, entry)
            sess.commit()

        if not entry.not_found:
            enriched += 1
        else:
            failed += 1

        if (enriched + failed) % 100 == 0:
            logger.info(
                "cached-enrich: %d enriched, %d failed, %d skipped",
                enriched,
                failed,
                skip,
            )

    logger.info(
        "cached-enrich done: %d enriched, %d failed, %d skipped",
        enriched,
        failed,
        skip,
    )
    return enriched, failed


# --- CLI -------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingest", description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    p_goethe = sub.add_parser(
        "goethe",
        help="fetch & seed DWDS Goethe-Zertifikat word lists (A1, A2, B1)",
    )
    p_goethe.add_argument(
        "--with-frequency",
        action="store_true",
        help="fetch frequency data (bucket + hits) from DWDS for each word",
    )
    sub.add_parser("cached-enrich", help="enrich all words from local DWDS cache only (no HTTP)")
    p_enrich = sub.add_parser("enrich", help="fetch DWDS definitions + examples")
    p_enrich.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum words to process (default: all without definitions)",
    )
    p_enrich.add_argument(
        "--corpus-api",
        action="store_true",
        help="fetch corpus examples via DWDS korpus API (replaces HTML-embedded)",
    )
    p_enrich.add_argument(
        "--with-ipa",
        action="store_true",
        help="fetch IPA pronunciation for each word",
    )
    p_enrich.add_argument(
        "--with-frequency",
        action="store_true",
        help="fetch frequency data (bucket + hits) from DWDS for each word",
    )
    p_b2 = sub.add_parser(
        "b2-candidates",
        help="seed B2 words from curated corpus-frequency CSV (deutsch-stat)",
    )
    p_b2.add_argument(
        "--csv",
        type=str,
        default=None,
        help="path to B2 candidates CSV (default: data/b2/candidates.csv)",
    )
    p_b2.add_argument(
        "--clear",
        action="store_true",
        help="delete existing B2 words before seeding",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Console-script entry: ``uv run ingest [goethe|enrich|cached-enrich]``.

    When called without a subcommand, defaults to ``goethe``.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)
    cmd = args.cmd or "goethe"

    if cmd == "goethe":
        entries = asyncio.run(fetch_all_goethe_lists())
        with_freq = getattr(args, "with_frequency", False)
        result = seed_goethe(entries, with_frequency=with_freq)
        for level, (ins, skip) in result.items():
            print(f"goethe {level}: {ins} inserted, {skip} skipped")
        total_ins = sum(ins for _, (ins, _) in result.items())
        total_skip = sum(skip for _, (_, skip) in result.items())
        print(f"goethe total: {total_ins} inserted, {total_skip} skipped")
    elif cmd == "cached-enrich":
        enriched, failed = enrich_all_cached()
        print(f"cached-enrich: {enriched} enriched, {failed} failed")
    elif cmd == "enrich":
        limit = getattr(args, "limit", None)
        enriched, failed = asyncio.run(
            enrich_words(
                limit,
                corpus_api=getattr(args, "corpus_api", False),
                with_ipa=getattr(args, "with_ipa", False),
                with_frequency=getattr(args, "with_frequency", False),
            )
        )
        print(f"enrich: {enriched} enriched, {failed} failed (no definition)")
    elif cmd == "b2-candidates":
        if args.clear:
            deleted = clear_existing_b2()
            print(f"b2-candidates: cleared {deleted} existing words")

        csv_path = Path(args.csv) if args.csv else None
        candidates = read_candidates(csv_path) if csv_path else read_candidates()
        ins, skip = persist(candidates)
        print(f"b2-candidates: {len(candidates)} loaded from CSV, {ins} inserted, {skip} skipped")
    else:  # pragma: no cover - argparse rejects unknowns
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
