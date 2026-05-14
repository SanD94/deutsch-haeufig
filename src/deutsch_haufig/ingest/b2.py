"""Generate project-defined B2 word candidates via DWDS random API.

Implements ROADMAP M8a strategy using the simple approach:

  1. Fetch random words from ``/api/wb/random?count=5``.
  2. Skip words already in Goethe A1/A2/B1.
  3. Skip obscure entries (type != Basisartikel / Vollartikel).
  4. Collect until we have ~1,000 candidates.
  5. Persist as ``level="B2"``, ``source_ref="dwds:b2:random:v1"``.

This is a project-defined label, not an official CEFR certification.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import text

from deutsch_haufig.db import SessionLocal, init_db
from deutsch_haufig.models import Word

logger = logging.getLogger(__name__)

UA = "deutsch-haufig/0.1"
RANDOM_URL = "https://www.dwds.de/api/wb/random"

POS_MAP: dict[str, str] = {
    "Substantiv": "noun",
    "Verb": "verb",
    "Adjektiv": "adj",
    "Adverb": "adv",
    "Präposition": "prep",
    "Konjunktion": "conj",
    "Pronomen": "pron",
    "Partikel": "particle",
    "Interjektion": "interj",
    "Mehrwortausdruck": "phrase",
    "Affix": "affix",
    "Symbol": "symbol",
    "Eigenname": "noun",
    "Kardinalzahlwort": "num",
    "Ordinalzahlwort": "num",
    "Bruchzahlwort": "num",
}


@dataclass
class B2Candidate:
    lemma: str
    pos: str
    article: str | None = None


def _normalize_pos(dwds_pos: str) -> str:
    return POS_MAP.get(dwds_pos.strip(), dwds_pos.strip().lower())


def _load_goethe_lemmas() -> set[str]:
    """Load all A1/A2/B1 lemmas from DB (POS-agnostic check)."""
    with SessionLocal() as session:
        rows = session.execute(
            text("SELECT DISTINCT lemma FROM words WHERE level IN ('A1', 'A2', 'B1')")
        ).fetchall()
        return {r[0] for r in rows}


def _load_existing_b2_lemmas() -> set[str]:
    """Load already-persisted B2 lemmas to avoid duplicates across runs."""
    with SessionLocal() as session:
        rows = session.execute(
            text("SELECT DISTINCT lemma FROM words WHERE level = 'B2'")
        ).fetchall()
        return {r[0] for r in rows}


def _is_noise(lemma: str, pos: str) -> bool:
    """Quick noise check — skip affixes, symbols, multiword."""
    if pos in ("affix", "symbol", "phrase"):
        return True
    if " " in lemma:
        return True
    if lemma.startswith("-") or lemma.endswith("-"):
        return True
    return False


async def fetch_batch(client: httpx.AsyncClient, count: int = 5) -> list[dict]:
    """Fetch a batch of random words from DWDS."""
    try:
        resp = await client.get(
            f"{RANDOM_URL}?count={count}",
            headers={"User-Agent": UA},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        return resp.json()
    except (httpx.HTTPError, OSError):
        return []


async def generate_b2_candidates(
    *,
    target: int = 1000,
    batch_size: int = 5,
    rate_limit: float = 1.0,
) -> list[B2Candidate]:
    """Collect B2 candidates from DWDS random API until target is reached."""
    init_db()
    goethe = _load_goethe_lemmas()
    existing_b2 = _load_existing_b2_lemmas()
    skip_lemmas = goethe | existing_b2

    logger.info("Goethe A1/A2/B1 lemmas: %d", len(goethe))
    logger.info("Existing B2 lemmas: %d", len(existing_b2))

    candidates: list[B2Candidate] = []
    seen: set[str] = set() | skip_lemmas
    attempts = 0
    last_req = 0.0

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        while len(candidates) < target:
            # Rate limit
            now = time.monotonic()
            wait = rate_limit - (now - last_req)
            if wait > 0:
                await asyncio.sleep(wait)
            last_req = time.monotonic()

            batch = await fetch_batch(client, count=batch_size)
            attempts += 1

            if not batch:
                logger.warning("empty batch at attempt %d, sleeping 5s", attempts)
                await asyncio.sleep(5)
                continue

            for entry in batch:
                lemma = entry.get("lemma", "")
                dwds_pos = entry.get("pos", "")
                art = entry.get("articles", [None])[0]
                entry_type = entry.get("type", "")

                if not lemma or not dwds_pos:
                    continue

                if lemma in seen:
                    continue
                seen.add(lemma)

                pos = _normalize_pos(dwds_pos)

                if _is_noise(lemma, pos):
                    continue

                # Skip obscure entries (not a proper dictionary article)
                if "Basisartikel" not in entry_type and "Vollartikel" not in entry_type:
                    continue

                candidates.append(B2Candidate(lemma=lemma, pos=pos, article=art))

                if len(candidates) % 50 == 0:
                    logger.info(
                        "progress: %d/%d candidates (attempts=%d)",
                        len(candidates),
                        target,
                        attempts,
                    )

                if len(candidates) >= target:
                    break

    logger.info(
        "collection done: %d candidates in %d attempts",
        len(candidates),
        attempts,
    )
    return candidates


def persist(candidates: list[B2Candidate]) -> tuple[int, int]:
    """Persist B2 words to DB. Returns (inserted, skipped)."""
    inserted = skipped = 0
    for cand in candidates:
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
                    source_ref="dwds:b2:random:v1",
                )
            )
            session.commit()
            inserted += 1
    return inserted, skipped
