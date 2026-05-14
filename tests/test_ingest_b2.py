"""Tests for the B2 candidate generator (``ingest/b2.py``).

Tests only pure functions — no real HTTP calls to DWDS.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from deutsch_haufig.ingest.b2 import (
    B2Candidate,
    _is_noise,
    _normalize_pos,
    fetch_batch,
    persist,
)


class TestNormalizePos:
    def test_substantiv(self) -> None:
        assert _normalize_pos("Substantiv") == "noun"

    def test_verb(self) -> None:
        assert _normalize_pos("Verb") == "verb"

    def test_adjektiv(self) -> None:
        assert _normalize_pos("Adjektiv") == "adj"

    def test_adverb(self) -> None:
        assert _normalize_pos("Adverb") == "adv"

    def test_unknown_pos(self) -> None:
        assert _normalize_pos("FooBar") == "foobar"


class TestIsNoise:
    def test_affix(self) -> None:
        assert _is_noise("-abel", "affix") is True

    def test_symbol(self) -> None:
        assert _is_noise("%", "symbol") is True

    def test_phrase(self) -> None:
        assert _is_noise("a cappella", "phrase") is True

    def test_multiword_not_phrase(self) -> None:
        assert _is_noise("a b", "noun") is True

    def test_hyphen_start(self) -> None:
        assert _is_noise("-abel", "noun") is True

    def test_normal_word(self) -> None:
        assert _is_noise("Haus", "noun") is False
        assert _is_noise("geben", "verb") is False

    def test_hyphen_end_is_ok(self) -> None:
        # "Kaffee-Ersatz" style — but these have spaces usually
        assert _is_noise("Kaffee-", "noun") is True


class TestB2Candidate:
    def test_defaults(self) -> None:
        c = B2Candidate(lemma="Auto", pos="noun")
        assert c.lemma == "Auto"
        assert c.pos == "noun"
        assert c.article is None

    def test_with_article(self) -> None:
        c = B2Candidate(lemma="Haus", pos="noun", article="das")
        assert c.article == "das"


class TestFetchBatch:
    @pytest.mark.asyncio
    async def test_returns_json_on_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"lemma": "Test", "pos": "Substantiv"}]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        result = await fetch_batch(mock_client, count=5)
        assert result == [{"lemma": "Test", "pos": "Substantiv"}]

    @pytest.mark.asyncio
    async def test_returns_empty_on_non_200(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 429

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        result = await fetch_batch(mock_client, count=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self) -> None:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("boom"))

        result = await fetch_batch(mock_client, count=5)
        assert result == []


class TestPersist:
    def test_persist_empty(self) -> None:
        ins, skip = persist([])
        assert ins == 0
        assert skip == 0
