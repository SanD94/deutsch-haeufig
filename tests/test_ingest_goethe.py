"""M1-DWDS — DWDS Goethe-Zertifikat word list parser tests.

Tests for ``ingest/goethe.py`` that fetches and parses the official
Goethe-Zertifikat word lists published by DWDS at:

  https://www.dwds.de/api/lemma/goethe/{A1,A2,B1}.csv

Each CSV row contains: Lemma, URL, Wortart, Genus, Artikel, nur_im_Plural.

The parser :func:`parse_goethe_csv` is a pure function exercised here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deutsch_haufig.ingest.goethe import GoetheEntry, parse_goethe_csv

FIXTURES = Path(__file__).parent / "fixtures" / "goethe"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- CSV parser tests --------------------------------------------------------


def test_parse_a1_noun_with_article() -> None:
    csv = _read("a1_sample.csv")
    entries = parse_goethe_csv(csv, level="A1")
    haus = [e for e in entries if e.lemma == "Haus"]
    assert len(haus) == 1
    assert haus[0].level == "A1"
    assert haus[0].pos == "noun"
    assert haus[0].article == "das"


def test_parse_a2_noun_multi_article() -> None:
    csv = _read("a2_sample.csv")
    entries = parse_goethe_csv(csv, level="A2")
    teil = [e for e in entries if e.lemma == "Teil"]
    assert len(teil) == 1
    assert teil[0].pos == "noun"
    assert teil[0].article == "der, das"  # DWDS CSV uses comma-separated


def test_parse_b1_plural_only() -> None:
    csv = _read("b1_sample.csv")
    entries = parse_goethe_csv(csv, level="B1")
    leute = [e for e in entries if e.lemma == "Leute"]
    assert len(leute) == 1
    assert leute[0].pos == "noun"
    assert leute[0].level == "B1"
    assert leute[0].only_plural is True


def test_parse_verb_without_article() -> None:
    csv = _read("a1_sample.csv")
    entries = parse_goethe_csv(csv, level="A1")
    geben = [e for e in entries if e.lemma == "geben"]
    assert len(geben) == 1
    assert geben[0].pos == "verb"
    assert geben[0].article is None


def test_parse_adjective() -> None:
    csv = _read("a1_sample.csv")
    entries = parse_goethe_csv(csv, level="A1")
    gut = [e for e in entries if e.lemma == "gut"]
    assert len(gut) == 1
    assert gut[0].pos == "adj"
    assert gut[0].article is None


def test_parse_all_entries_returned() -> None:
    csv = _read("a1_sample.csv")
    entries = parse_goethe_csv(csv, level="A1")
    assert len(entries) == 5


# --- POS normalization -------------------------------------------------------


@pytest.mark.parametrize(
    "dwds_pos,expected",
    [
        ("Substantiv", "noun"),
        ("Verb", "verb"),
        ("Adjektiv", "adj"),
        ("Adverb", "adv"),
        ("Präposition", "prep"),
        ("Konjunktion", "conj"),
        ("Pronomen", "pron"),
        ("Interjektion", "interj"),
        ("Partikel", "particle"),
        ("Kardinalzahlwort", "num"),
        ("Bruchzahlwort", "num"),
        ("Ordinalzahlwort", "num"),
        ("Eigenname", "noun"),
        ("Demonstrativpronomen", "pron"),
        ("Possessivpronomen", "pron"),
        ("Indefinitpronomen", "pron"),
        ("Interrogativpronomen", "pron"),
        ("Personalpronomen", "pron"),
        ("Reflexivpronomen", "pron"),
        ("Relativpronomen", "pron"),
        ("Reziprokes Pronomen", "pron"),
        ("Pronominaladverb", "adv"),
        ("bestimmter Artikel", "article"),
        ("Mehrwortausdruck", "phrase"),
        ("Affix", "affix"),
    ],
)
def test_normalize_pos(dwds_pos: str, expected: str) -> None:
    from deutsch_haufig.ingest.goethe import _normalize_pos

    assert _normalize_pos(dwds_pos) == expected


# --- GoetheEntry dataclass ---------------------------------------------------


def test_goethe_entry_fields() -> None:
    entry = GoetheEntry(
        lemma="Haus",
        url="https://www.dwds.de/wb/Haus",
        pos="noun",
        level="A1",
        article="das",
        genus="neutr.",
        only_plural=False,
    )
    assert entry.lemma == "Haus"
    assert entry.url == "https://www.dwds.de/wb/Haus"
    assert entry.source_ref == "dwds:goethe:A1"


def test_goethe_entry_repr() -> None:
    entry = GoetheEntry(lemma="Haus", url="", pos="noun", level="A1")
    r = repr(entry)
    assert "Haus" in r
    assert "A1" in r
