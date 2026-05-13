"""M2c — DWDS frequency API parser tests.

Tests for ``ingest/dwds.py`` that parse the DWDS frequency API JSON responses
and for the pipeline ``--with-frequency`` flag.

Fixtures:

  fixtures/dwds/freq/haus.json    frequency API response for "Haus"
  fixtures/dwds/freq/geben.json   frequency API response for "geben"
  fixtures/dwds/freq/sein.json    frequency API response for "sein"
"""

from __future__ import annotations

import json
from pathlib import Path

from deutsch_haufig.ingest.dwds import DWDSFrequency, parse_frequency_response

FIXTURES = Path(__file__).parent / "fixtures" / "dwds"


def _read_freq(name: str) -> dict:
    path = FIXTURES / "freq" / name
    return json.loads(path.read_text(encoding="utf-8"))


class TestParseFrequencyResponse:
    def test_parse_haus(self) -> None:
        data = _read_freq("haus.json")
        result = parse_frequency_response("Haus", data)
        assert result is not None
        assert isinstance(result, DWDSFrequency)
        assert result.lemma == "Haus"
        assert result.frequency == 6
        assert result.hits == 591681

    def test_parse_geben(self) -> None:
        data = _read_freq("geben.json")
        result = parse_frequency_response("geben", data)
        assert result is not None
        assert result.lemma == "geben"
        assert result.frequency == 5
        assert result.hits == 123456

    def test_parse_sein(self) -> None:
        data = _read_freq("sein.json")
        result = parse_frequency_response("sein", data)
        assert result is not None
        assert result.lemma == "sein"
        assert result.frequency == 6
        assert result.hits == 789012

    def test_parse_none_input(self) -> None:
        result = parse_frequency_response("test", None)
        assert result is None

    def test_parse_empty_dict(self) -> None:
        result = parse_frequency_response("test", {})
        assert result is None

    def test_parse_missing_frequency(self) -> None:
        result = parse_frequency_response("test", {"hits": 100})
        assert result is None

    def test_parse_missing_hits(self) -> None:
        result = parse_frequency_response("test", {"frequency": 3})
        assert result is None

    def test_parse_zero_values(self) -> None:
        result = parse_frequency_response("test", {"q": "test", "frequency": 0, "hits": 0})
        assert result is not None
        assert result.frequency == 0
        assert result.hits == 0

    def test_dwdsfrequency_dataclass(self) -> None:
        freq = DWDSFrequency(lemma="Auto", frequency=4, hits=50000)
        assert freq.lemma == "Auto"
        assert freq.frequency == 4
        assert freq.hits == 50000

    def test_parse_string_values(self) -> None:
        """The API may return ints or strings; we coerce to int."""
        data = {"q": "test", "frequency": "3", "hits": "999"}
        result = parse_frequency_response("test", data)
        assert result is not None
        assert result.frequency == 3
        assert result.hits == 999
