"""M2a/M2b — DWDS corpus API and IPA API tests.

Tests for ``ingest/dwds.py`` that parse the DWDS korpus API JSON responses
and the DWDS IPA API JSON responses.

Fixtures:

  fixtures/dwds/corpus/haus.json    corpus API response for "Haus"
  fixtures/dwds/corpus/geben.json   corpus API response for "geben"
  fixtures/dwds/ipa/haus.json       IPA API response for "Haus"
  fixtures/dwds/ipa/geben.json      IPA API response for "geben"
  fixtures/dwds/ipa/sein.json       IPA API response for "sein"
"""

from __future__ import annotations

import json
from pathlib import Path


from deutsch_haufig.ingest.dwds import (
    DWDSExample,
    parse_corpus_response,
    parse_ipa_response,
    _reconstruct_sentence,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dwds"


def _read_corpus(name: str) -> list:
    path = FIXTURES / "corpus" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _read_ipa(name: str) -> list:
    path = FIXTURES / "ipa" / name
    return json.loads(path.read_text(encoding="utf-8"))


# --- sentence reconstruction ------------------------------------------------


class TestReconstructSentence:
    def test_simple_sentence(self) -> None:
        ctx = [
            "",
            [
                {"ws": "1", "hl_": 0, "w": "Das"},
                {"ws": "1", "hl_": 1, "w": "Haus"},
                {"ws": "1", "hl_": 0, "w": "ist"},
                {"ws": "1", "hl_": 0, "w": "groß"},
                {"ws": "0", "hl_": 0, "w": "."},
            ],
            "",
        ]
        result = _reconstruct_sentence(ctx)
        assert result == "Das Haus ist groß."

    def test_no_space_between_words(self) -> None:
        ctx = [
            "",
            [
                {"ws": "1", "hl_": 0, "w": "Haus"},
                {"ws": "0", "hl_": 0, "w": ","},
                {"ws": "1", "hl_": 0, "w": "das"},
            ],
            "",
        ]
        result = _reconstruct_sentence(ctx)
        assert result == "Haus, das"

    def test_first_word_no_leading_space(self) -> None:
        ctx = [
            "",
            [
                {"ws": "1", "hl_": 0, "w": "Haus"},
            ],
            "",
        ]
        result = _reconstruct_sentence(ctx)
        assert result == "Haus"

    def test_empty_context_returns_empty(self) -> None:
        result = _reconstruct_sentence(["", [], ""])
        assert result == ""

    def test_first_word_does_not_get_leading_space(self) -> None:
        ctx = [
            "",
            [
                {"ws": "1", "hl_": 0, "w": "Erster"},
            ],
            "",
        ]
        result = _reconstruct_sentence(ctx)
        assert result == "Erster"

    def test_missing_ws_defaults_to_no_space(self) -> None:
        ctx = [
            "",
            [
                {"ws": "1", "hl_": 0, "w": "a"},
                {"hl_": 0, "w": "b"},
            ],
            "",
        ]
        result = _reconstruct_sentence(ctx)
        assert result == "ab"


# --- corpus API parser -------------------------------------------------------


class TestParseCorpusResponse:
    def test_parse_haus_returns_examples(self) -> None:
        data = _read_corpus("haus.json")
        examples = parse_corpus_response(data)
        assert len(examples) == 3
        assert isinstance(examples[0], DWDSExample)
        assert examples[0].text_de
        assert len(examples[0].text_de) > 15

    def test_parse_haus_example_text(self) -> None:
        data = _read_corpus("haus.json")
        examples = parse_corpus_response(data)
        assert "Nichts" in examples[0].text_de
        assert "Haus" in examples[0].text_de

    def test_parse_haus_source_attribution(self) -> None:
        data = _read_corpus("haus.json")
        examples = parse_corpus_response(data)
        assert "Degenhardt" in examples[0].source

    def test_parse_haus_limit_two(self) -> None:
        data = _read_corpus("haus.json")
        examples = parse_corpus_response(data, limit=2)
        assert len(examples) == 2

    def test_parse_haus_limit_one(self) -> None:
        data = _read_corpus("haus.json")
        examples = parse_corpus_response(data, limit=1)
        assert len(examples) == 1

    def test_parse_geben_returns_examples(self) -> None:
        data = _read_corpus("geben.json")
        examples = parse_corpus_response(data)
        assert len(examples) == 2

    def test_parse_geben_example_text(self) -> None:
        data = _read_corpus("geben.json")
        examples = parse_corpus_response(data)
        assert "Kannst" in examples[0].text_de or "Es" in examples[0].text_de

    def test_parse_empty_response(self) -> None:
        examples = parse_corpus_response([])
        assert examples == []

    def test_parse_malformed_response(self) -> None:
        examples = parse_corpus_response([{"no_ctx": True}])
        assert examples == []

    def test_parse_response_without_ctx(self) -> None:
        examples = parse_corpus_response([{"bibl_string": "test"}])
        assert examples == []

    def test_example_has_default_source(self) -> None:
        data = _read_corpus("haus.json")
        examples = parse_corpus_response(data)
        assert examples[0].source != "dwds-korpus"
        assert "Degenhardt" in examples[0].source


# --- IPA API parser ----------------------------------------------------------


class TestParseIpaResponse:
    def test_parse_haus_ipa(self) -> None:
        data = _read_ipa("haus.json")
        ipa = parse_ipa_response(data)
        assert ipa == "haʊ̯s"

    def test_parse_geben_ipa(self) -> None:
        data = _read_ipa("geben.json")
        ipa = parse_ipa_response(data)
        assert ipa == "ɡeːbən"

    def test_parse_sein_ipa(self) -> None:
        data = _read_ipa("sein.json")
        ipa = parse_ipa_response(data)
        assert ipa == "zaɪn"

    def test_parse_empty_response(self) -> None:
        ipa = parse_ipa_response([])
        assert ipa is None

    def test_parse_missing_ipa_field(self) -> None:
        ipa = parse_ipa_response([{"status": "missing"}])
        assert ipa is None

    def test_parse_none_input(self) -> None:
        ipa = parse_ipa_response([])
        assert ipa is None

    def test_parse_returns_first_result(self) -> None:
        data = [{"ipa": "haʊ̯s", "status": "proved"}, {"ipa": "haʊzəs", "status": "variant"}]
        ipa = parse_ipa_response(data)
        assert ipa == "haʊ̯s"
