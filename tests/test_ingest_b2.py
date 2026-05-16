"""Tests for the B2 candidate generator (``ingest/b2.py``).

Tests pure functions — no real HTTP calls or DB access (except ``persist``
which needs a test DB).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deutsch_haufig.ingest.b2 import (
    B2Candidate,
    detect_pos,
    read_candidates,
)


class TestDetectPos:
    def test_noun_uppercase(self) -> None:
        assert detect_pos("Haus") == "noun"
        assert detect_pos("Auto") == "noun"

    def test_verb_ieren(self) -> None:
        assert detect_pos("studieren") == "verb"
        assert detect_pos("reagieren") == "verb"

    def test_verb_en_suffix(self) -> None:
        assert detect_pos("arbeiten") == "verb"
        assert detect_pos("kochen") == "verb"

    def test_verb_eln_ern(self) -> None:
        assert detect_pos("klingeln") == "verb"
        assert detect_pos("verbessern") == "verb"

    def test_known_adverb(self) -> None:
        assert detect_pos("sowie") == "adv"
        assert detect_pos("dennoch") == "adv"
        assert detect_pos("insbesondere") == "adv"

    def test_known_preposition(self) -> None:
        assert detect_pos("aufgrund") == "prep"
        assert detect_pos("trotz") == "prep"

    def test_known_conjunction(self) -> None:
        assert detect_pos("bzw.") == "conj"
        assert detect_pos("indem") == "conj"

    def test_known_pronoun(self) -> None:
        assert detect_pos("einiger") == "pron"
        assert detect_pos("jener") == "pron"

    def test_adj_fallback(self) -> None:
        assert detect_pos("schön") == "adj"
        assert detect_pos("groß") == "adj"

    def test_empty_lemma(self) -> None:
        assert detect_pos("") == "noun"


class TestReadCandidates:
    def test_parses_csv(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "candidates.csv"
        csv_file.write_text(
            "lemma,is_title_case\nHaus,true\narbeiten,false\nschön,false\nsowie,false\n"
        )
        candidates = read_candidates(csv_file)
        assert len(candidates) == 4
        assert candidates[0] == B2Candidate(lemma="Haus", pos="noun", is_title_case=True)
        assert candidates[1] == B2Candidate(lemma="arbeiten", pos="verb", is_title_case=False)
        assert candidates[2] == B2Candidate(lemma="schön", pos="adj", is_title_case=False)
        assert candidates[3] == B2Candidate(lemma="sowie", pos="adv", is_title_case=False)

    def test_deduplicates(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "candidates.csv"
        csv_file.write_text("lemma\nHaus\nHaus\nAuto\n")
        candidates = read_candidates(csv_file)
        assert len(candidates) == 2

    def test_skips_empty_rows(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "candidates.csv"
        csv_file.write_text("lemma\nHaus\n\nAuto\n")
        candidates = read_candidates(csv_file)
        assert len(candidates) == 2

    def test_raises_on_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            read_candidates(Path("/nonexistent/path.csv"))


class TestB2Candidate:
    def test_defaults(self) -> None:
        c = B2Candidate(lemma="Auto", pos="noun")
        assert c.lemma == "Auto"
        assert c.pos == "noun"
        assert c.article is None
        assert c.is_title_case is False

    def test_with_article(self) -> None:
        c = B2Candidate(lemma="Haus", pos="noun", article="das")
        assert c.article == "das"

    def test_with_title_case(self) -> None:
        c = B2Candidate(lemma="Haus", pos="noun", is_title_case=True)
        assert c.is_title_case is True
