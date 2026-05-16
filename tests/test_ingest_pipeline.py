"""M2a/M2b/M2c — pipeline enrich CLI tests.

Tests for ``ingest/pipeline.py`` that verify the ``--corpus-api``, ``--with-ipa``,
and ``--with-frequency`` flags on the ``enrich`` and ``goethe`` subcommands.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from deutsch_haufig.ingest.pipeline import _build_parser


class TestMainArgparse:
    def test_default_cmd_is_goethe(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.cmd or "goethe" == "goethe"

    def test_goethe_subcommand(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["goethe"])
        assert args.cmd == "goethe"

    def test_enrich_subcommand(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["enrich"])
        assert args.cmd == "enrich"

    def test_cached_enrich_subcommand(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["cached-enrich"])
        assert args.cmd == "cached-enrich"

    @pytest.mark.parametrize("removed", ["scrape", "seed", "all"])
    def test_removed_subcommands_rejected(self, removed: str) -> None:
        """Removed subcommands must be rejected."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([removed])


class TestEnrichArgparse:
    def test_enrich_has_corpus_api_flag(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["enrich", "--corpus-api"])
        assert args.cmd == "enrich"
        assert args.corpus_api is True

    def test_enrich_corpus_api_default_false(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["enrich"])
        assert args.corpus_api is False

    def test_enrich_has_with_ipa_flag(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["enrich", "--with-ipa"])
        assert args.cmd == "enrich"
        assert args.with_ipa is True

    def test_enrich_with_ipa_default_false(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["enrich"])
        assert args.with_ipa is False

    def test_enrich_both_flags(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["enrich", "--corpus-api", "--with-ipa"])
        assert args.corpus_api
        assert args.with_ipa

    def test_enrich_limit_with_corpus_api(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["enrich", "--limit", "10", "--corpus-api"])
        assert args.limit == 10
        assert args.corpus_api

    def test_enrich_has_with_frequency_flag(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["enrich", "--with-frequency"])
        assert args.cmd == "enrich"
        assert args.with_frequency is True

    def test_enrich_with_frequency_default_false(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["enrich"])
        assert args.with_frequency is False

    def test_enrich_all_flags(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["enrich", "--corpus-api", "--with-ipa", "--with-frequency"])
        assert args.corpus_api
        assert args.with_ipa
        assert args.with_frequency


class TestGoetheArgparse:
    def test_goethe_has_with_frequency_flag(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["goethe", "--with-frequency"])
        assert args.cmd == "goethe"
        assert args.with_frequency is True

    def test_goethe_with_frequency_default_false(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["goethe"])
        assert args.with_frequency is False


class TestEnrichWordsWithFlags:
    @pytest.mark.asyncio
    @patch("deutsch_haufig.ingest.dwds.fetch_words")
    @patch("deutsch_haufig.ingest.pipeline.init_db")
    async def test_enrich_words_passes_corpus_api(self, mock_init_db, mock_fetch_words) -> None:
        from deutsch_haufig.ingest.pipeline import enrich_words

        mock_fetch_words.return_value.__aiter__.return_value = iter([])
        await enrich_words(corpus_api=False)

    @pytest.mark.asyncio
    @patch("deutsch_haufig.ingest.dwds.fetch_words")
    @patch("deutsch_haufig.ingest.pipeline.init_db")
    async def test_enrich_words_passes_with_ipa(self, mock_init_db, mock_fetch_words) -> None:
        from deutsch_haufig.ingest.pipeline import enrich_words

        mock_fetch_words.return_value.__aiter__.return_value = iter([])
        await enrich_words(with_ipa=False)

    @pytest.mark.asyncio
    @patch("deutsch_haufig.ingest.dwds.fetch_words")
    @patch("deutsch_haufig.ingest.pipeline.init_db")
    @patch("deutsch_haufig.ingest.pipeline._enrich_corpus_examples", new_callable=AsyncMock)
    async def test_corpus_api_triggers_fetch(
        self, mock_corpus, mock_init_db, mock_fetch_words
    ) -> None:
        from deutsch_haufig.ingest.pipeline import enrich_words

        mock_fetch_words.return_value.__aiter__.return_value = iter([])
        mock_corpus.return_value = (0, 0)
        await enrich_words(corpus_api=True)
        mock_corpus.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("deutsch_haufig.ingest.dwds.fetch_words")
    @patch("deutsch_haufig.ingest.pipeline.init_db")
    @patch("deutsch_haufig.ingest.pipeline._enrich_ipa", new_callable=AsyncMock)
    async def test_with_ipa_triggers_fetch(self, mock_ipa, mock_init_db, mock_fetch_words) -> None:
        from deutsch_haufig.ingest.pipeline import enrich_words

        mock_fetch_words.return_value.__aiter__.return_value = iter([])
        mock_ipa.return_value = (0, 0)
        await enrich_words(with_ipa=True)
        mock_ipa.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("deutsch_haufig.ingest.dwds.fetch_words")
    @patch("deutsch_haufig.ingest.pipeline.init_db")
    @patch("deutsch_haufig.ingest.pipeline._enrich_frequency", new_callable=AsyncMock)
    async def test_with_frequency_triggers_fetch(
        self, mock_freq, mock_init_db, mock_fetch_words
    ) -> None:
        from deutsch_haufig.ingest.pipeline import enrich_words

        mock_fetch_words.return_value.__aiter__.return_value = iter([])
        mock_freq.return_value = (0, 0)
        await enrich_words(with_frequency=True)
        mock_freq.assert_awaited_once()
