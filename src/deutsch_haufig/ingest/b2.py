"""Generate project-defined B2 word candidates from a curated frequency list.

Replaces the old DWDS random API approach with a data-driven method using
corpus-frequency analysis (from the deutsch-stat project at
``~/projects/deutsch-stat/outputs/b2_candidates_top1000.csv``).

Usage::

    uv run ingest b2-candidates
    uv run ingest enrich  # then enrich with DWDS definitions
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from deutsch_haufig.db import SessionLocal, init_db
from deutsch_haufig.models import Word

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "b2" / "candidates.csv"

# --- POS detection -----------------------------------------------------------

KNOWN_ADVERBS: set[str] = {
    "sowie",
    "dazu",
    "zudem",
    "davon",
    "derzeit",
    "zuvor",
    "weiterhin",
    "bislang",
    "dennoch",
    "demnach",
    "daran",
    "darunter",
    "erstmals",
    "dadurch",
    "darin",
    "daraufhin",
    "wiederum",
    "hingegen",
    "hinzu",
    "durchaus",
    "darum",
    "davor",
    "somit",
    "wobei",
    "einst",
    "teils",
    "mehrfach",
    "immerhin",
    "jedenfalls",
    "ohnehin",
    "vorerst",
    "stets",
    "lediglich",
    "daraus",
    "hervor",
    "letztlich",
    "insbesondere",
    "zunehmend",
    "zugleich",
    "statdessen",
    "beispielsweise",
    "nach wie vor",
}

KNOWN_PREPOSITIONS: set[str] = {
    "aufgrund",
    "angesichts",
    "zufolge",
    "einschließlich",
    "trotz",
}

KNOWN_CONJUNCTIONS: set[str] = {
    "bzw.",
    "sodass",
    "so dass",
    "indem",
    "sofern",
}

KNOWN_PRONOUNS: set[str] = {
    "einiger",
    "jener",
    "diejenige",
}


def detect_pos(lemma: str) -> str:
    """Detect POS for a German B2 candidate using word form heuristics."""
    if not lemma:
        return "noun"
    first = lemma[0]
    if first.isupper():
        return "noun"
    if lemma in KNOWN_ADVERBS:
        return "adv"
    if lemma in KNOWN_PREPOSITIONS:
        return "prep"
    if lemma in KNOWN_CONJUNCTIONS:
        return "conj"
    if lemma in KNOWN_PRONOUNS:
        return "pron"
    if lemma.endswith(("ieren", "eien")):
        return "verb"
    if lemma.endswith("en") and len(lemma) >= 4:
        return "verb"
    if lemma.endswith(("eln", "ern")) and len(lemma) >= 5:
        return "verb"
    return "adj"


# --- CSV reading -------------------------------------------------------------


@dataclass
class B2Candidate:
    lemma: str
    pos: str
    article: str | None = None
    is_title_case: bool = False


def read_candidates(csv_path: Path = CSV_PATH) -> list[B2Candidate]:
    """Read B2 candidates from the curated CSV file.

    Returns a list of B2Candidate objects with POS detected via heuristics.
    """
    if not csv_path.exists():
        msg = f"B2 candidates CSV not found: {csv_path}"
        raise FileNotFoundError(msg)

    candidates: list[B2Candidate] = []
    seen: set[str] = set()

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lemma = (row.get("lemma") or "").strip()
            if not lemma:
                continue
            if lemma in seen:
                continue
            seen.add(lemma)

            is_title_case = row.get("is_title_case", "").strip().lower() == "true"
            pos = detect_pos(lemma)
            candidates.append(B2Candidate(lemma=lemma, pos=pos, is_title_case=is_title_case))

    logger.info("read %d B2 candidates from %s", len(candidates), csv_path)
    return candidates


# --- persistence -------------------------------------------------------------


def _load_existing_goethe_lemmas() -> set[str]:
    """Load all A1/A2/B1 lemmas from DB (POS-agnostic)."""
    with SessionLocal() as session:
        rows = session.execute(
            text("SELECT DISTINCT lemma FROM words WHERE level IN ('A1', 'A2', 'B1')")
        ).fetchall()
        return {r[0] for r in rows}


def persist(
    candidates: list[B2Candidate], *, source_ref: str = "dwds:b2:stat:v1"
) -> tuple[int, int]:
    """Persist B2 words to DB. Returns (inserted, skipped).

    Skips lemmas that already exist at A1/A2/B1 level.
    """
    init_db()
    goethe = _load_existing_goethe_lemmas()
    inserted = skipped = 0
    for cand in candidates:
        if cand.lemma in goethe:
            skipped += 1
            continue
        with SessionLocal() as session:
            exists = session.execute(
                text("SELECT id FROM words WHERE lemma = :lemma AND pos = :pos"),
                {"lemma": cand.lemma, "pos": cand.pos},
            ).scalar_one_or_none()
            if exists:
                skipped += 1
                continue
            session.add(
                Word(
                    lemma=cand.lemma,
                    article=cand.article if cand.pos == "noun" else None,
                    pos=cand.pos,
                    level="B2",
                    source_ref=source_ref,
                )
            )
            session.commit()
            inserted += 1
    logger.info("persist: %d inserted, %d skipped", inserted, skipped)
    return inserted, skipped


# --- cleanup ----------------------------------------------------------------


def clear_existing_b2() -> int:
    """Delete all existing B2 words and their senses. Returns count deleted."""
    init_db()
    with SessionLocal() as session:
        result = session.execute(text("DELETE FROM words WHERE level = 'B2'"))
        session.commit()
        count = result.rowcount
        logger.info("deleted %d existing B2 words", count)
        return count
