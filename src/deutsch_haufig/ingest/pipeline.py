"""Ingest CLI for M1/M2.

Subcommands:

  scrape   Drive Playwright over vocabeo.com/browse and write
           ``data/vocabeo_seed.jsonl``.
  seed    Upsert the JSONL seed into the SQLite ``words`` table.
  enrich  Fetch DWDS definitions and examples and upsert to senses + examples.
  all     scrape + seed + enrich (the default).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from deutsch_haufig.config import settings
from deutsch_haufig.db import SessionLocal, init_db
from deutsch_haufig.ingest.dwds import (
    DWDSEntry,
)
from deutsch_haufig.ingest.goethe import (
    GoetheEntry,
    fetch_all_goethe_lists,
)
from deutsch_haufig.ingest.vocabeo import (
    VocabeoEntry,
    read_jsonl,
    scrape_browse_list,
    write_jsonl,
)
from deutsch_haufig.models import Example, Sense, Word

logger = logging.getLogger(__name__)

DEFAULT_SEED_PATH = settings.data_dir / "vocabeo_seed.jsonl"


# --- goethe (CSV → SQLite) ---------------------------------------------------


def _normalize_level_for_duplicates(
    existing: Word | None, new_level: str | None
) -> str | None:
    """Keep the lowest (most basic) level when the same lemma+pos appears
    across multiple Goethe levels (e.g. ``Haus`` in A1 + B1 → keep A1).
    """
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
    stmt = select(Word).where(
        Word.lemma == entry.lemma,
        Word.pos == entry.pos,
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
    existing.source_ref = entry.source_ref
    session.commit()
    return False


def seed_goethe(
    entries: dict[str, list[GoetheEntry]],
) -> dict[str, tuple[int, int]]:
    """Idempotently upsert Goethe entries into Word. Returns ``{level: (inserted, skipped)}``."""
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
    return result


# --- seed (jsonl → SQLite) -------------------------------------------------


def upsert_word(session: Session, entry: VocabeoEntry) -> bool:
    """Insert or update a Word by ``(lemma, pos, en_gloss)``.

    Returns True on insert, False on update. The (lemma, pos, en_gloss)
    triple matches the dedup key used by the scraper, so homographs
    like ``sein/verb`` and ``sein/pron`` end up as separate rows.
    """
    stmt = select(Word).where(
        Word.lemma == entry.lemma,
        Word.pos == entry.pos,
        Word.source_ref == entry.source_ref,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        # Fall back to a (lemma, pos) match for stable upserts when the
        # source_ref drifts between scrapes (the row index can shift).
        existing = session.execute(
            select(Word).where(Word.lemma == entry.lemma, Word.pos == entry.pos)
        ).scalar_one_or_none()
    if existing is None:
        session.add(
            Word(
                lemma=entry.lemma,
                article=entry.article,
                pos=entry.pos,
                level=entry.level,
                frequency=entry.frequency or 0,
                source_ref=entry.source_ref,
            )
        )
        return True
    existing.article = entry.article or existing.article
    existing.level = existing.level or entry.level
    existing.frequency = max(existing.frequency or 0, entry.frequency or 0)
    existing.source_ref = entry.source_ref or existing.source_ref
    return False


def seed_words(entries: list[VocabeoEntry]) -> tuple[int, int]:
    """Idempotently upsert ``entries`` into Word. Returns ``(inserted, updated)``."""
    init_db()
    inserted = updated = 0
    with SessionLocal() as session:
        for entry in entries:
            if upsert_word(session, entry):
                inserted += 1
            else:
                updated += 1
        session.commit()
    return inserted, updated


# --- enrich (DWDS definitions + examples) -------------------------------


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


async def enrich_words(limit: int | None = None) -> tuple[int, int]:
    """Fetch DWDS for words without definitions, upsert senses + examples.

    Returns (enriched_count, failed_count).
    """
    init_db()
    enriched = failed = 0

    with SessionLocal() as session:
        words = session.execute(select(Word).where(Word.id > 0).order_by(Word.id)).scalars().all()

    async def word_iter():
        for w in words:
            with SessionLocal() as sess:
                senses = sess.execute(select(Sense).where(Sense.word_id == w.id)).scalars().all()
            has_def = any(s.definition_de for s in senses)
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

    return enriched, failed


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


def _run_scrape(seed_path: Path, *, headless: bool = True) -> int:
    entries = asyncio.run(scrape_browse_list(headless=headless))
    written = write_jsonl(entries, seed_path)
    print(f"scrape: wrote {written} entries → {seed_path}")
    return written


def _run_seed(seed_path: Path) -> tuple[int, int]:
    if not seed_path.exists():
        raise SystemExit(f"seed file not found: {seed_path}\n  → run `uv run ingest scrape` first.")
    entries = read_jsonl(seed_path)
    inserted, updated = seed_words(entries)
    print(
        f"seed: {inserted} inserted, {updated} updated "
        f"({inserted + updated} total) → {settings.database_url}"
    )
    return inserted, updated


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingest", description=__doc__)
    parser.add_argument(
        "--seed-path",
        type=Path,
        default=DEFAULT_SEED_PATH,
        help=f"path to vocabeo_seed.jsonl (default: {DEFAULT_SEED_PATH})",
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("goethe", help="fetch & seed DWDS Goethe-Zertifikat word lists (A1, A2, B1)")
    p_scrape = sub.add_parser("scrape", help="drive Playwright over vocabeo /browse → JSONL")
    p_scrape.add_argument("--headed", action="store_true", help="show the browser window (debug)")
    sub.add_parser("seed", help="upsert JSONL into SQLite Word rows")
    sub.add_parser("cached-enrich", help="enrich all words from local DWDS cache only (no HTTP)")
    p_enrich = sub.add_parser("enrich", help="fetch DWDS definitions + examples")
    p_enrich.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum words to process (default: all without definitions)",
    )
    p_all = sub.add_parser("all", help="scrape then seed then enrich (default)")
    p_all.add_argument("--headed", action="store_true", help="show the browser window (debug)")
    p_all.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum words to enrich",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Console-script entry: ``uv run ingest [scrape|seed|enrich|all]``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)
    cmd = args.cmd or "all"
    headless = not getattr(args, "headed", False)

    if cmd == "goethe":
        entries = asyncio.run(fetch_all_goethe_lists())
        result = seed_goethe(entries)
        for level, (ins, skip) in result.items():
            print(f"goethe {level}: {ins} inserted, {skip} skipped")
        total_ins = sum(ins for _, (ins, _) in result.items())
        total_skip = sum(skip for _, (_, skip) in result.items())
        print(f"goethe total: {total_ins} inserted, {total_skip} skipped")
    elif cmd == "scrape":
        _run_scrape(args.seed_path, headless=headless)
    elif cmd == "seed":
        _run_seed(args.seed_path)
    elif cmd == "cached-enrich":
        enriched, failed = enrich_all_cached()
        print(f"cached-enrich: {enriched} enriched, {failed} failed")
    elif cmd == "enrich":
        limit = getattr(args, "limit", None)
        enriched, failed = asyncio.run(enrich_words(limit=limit))
        print(f"enrich: {enriched} enriched, {failed} failed (no definition)")
    elif cmd == "all":
        _run_scrape(args.seed_path, headless=headless)
        _run_seed(args.seed_path)
        limit = getattr(args, "limit", None)
        enriched, failed = asyncio.run(enrich_words(limit=limit))
        print(f"enrich: {enriched} enriched, {failed} failed (no definition)")
    else:  # pragma: no cover - argparse rejects unknowns
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
