"""Tests for M4 — on-demand dialogue generation.

Covers:
- DialogueProvider protocol + NoOpProvider fallback
- OpenAIProvider HTTP client behaviour (via respx mock)
- provider_from_config with and without opencode.json
- Word detail page: button shown/hidden based on config
- POST /word/{id}/dialogue/{sense_id}: generate, cache, return cached
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from deutsch_haufig.db import SessionLocal, get_session
from deutsch_haufig.dialogue import (
    DialogueGenerationError,
    NoOpProvider,
    provider_from_config,
)
from deutsch_haufig.main import create_app
from deutsch_haufig.models import Base, Dialogue, Sense, Word


@pytest.fixture(autouse=True)
def _reset_db():
    from deutsch_haufig.db import engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def app(db_session):
    app = create_app()

    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    return app


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def sample_sense(db_session) -> Sense:
    w = Word(lemma="geben", pos="verb", level="A1", frequency=5)
    db_session.add(w)
    db_session.flush()
    s = Sense(word_id=w.id, definition_de="etwas aushändigen oder reichen")
    db_session.add(s)
    db_session.commit()
    return s


# ---------------------------------------------------------------------------
# DialogueProvider protocol / NoOpProvider
# ---------------------------------------------------------------------------


class TestNoOpProvider:
    @pytest.mark.asyncio
    async def test_raises_on_generate(self) -> None:
        p = NoOpProvider()
        with pytest.raises(DialogueGenerationError, match="No dialogue provider configured"):
            await p.generate("geben", "to give")


# ---------------------------------------------------------------------------
# provider_from_config
# ---------------------------------------------------------------------------


class TestProviderFromConfig:
    def test_no_opencode_returns_nop(self, tmp_path: Path) -> None:
        with patch("deutsch_haufig.config.PROJECT_ROOT", tmp_path):
            p = provider_from_config()
        assert isinstance(p, NoOpProvider)

    def test_with_api_key_returns_openai_provider(self, tmp_path: Path) -> None:
        cfg = {
            "provider": {
                "test": {
                    "options": {
                        "baseURL": "https://example.com/v1",
                        "apiKey": "sk-test",
                    },
                    "models": {"test-model": {}},
                }
            }
        }
        opencode = tmp_path / "opencode.json"
        opencode.write_text(json.dumps(cfg))
        with patch("deutsch_haufig.config.PROJECT_ROOT", tmp_path):
            p = provider_from_config()
        from deutsch_haufig.dialogue.openai_provider import OpenAIProvider

        assert isinstance(p, OpenAIProvider)
        assert p._api_key == "sk-test"
        assert p._base_url == "https://example.com/v1"
        assert p._model == "test-model"

    def test_missing_api_key_returns_nop(self, tmp_path: Path) -> None:
        cfg = {
            "provider": {
                "test": {
                    "options": {"baseURL": "https://example.com/v1", "apiKey": ""},
                    "models": {"test-model": {}},
                }
            }
        }
        opencode = tmp_path / "opencode.json"
        opencode.write_text(json.dumps(cfg))
        with patch("deutsch_haufig.config.PROJECT_ROOT", tmp_path):
            p = provider_from_config()
        assert isinstance(p, NoOpProvider)


# ---------------------------------------------------------------------------
# Word detail page — button visibility
# ---------------------------------------------------------------------------


class TestWordPageDialogueButton:
    def test_button_hidden_when_no_provider(self, client, sample_sense):
        with patch("deutsch_haufig.config.get_dialogue_provider_config") as mock:
            mock.return_value = None
            resp = client.get(f"/word/{sample_sense.word_id}")
        assert resp.status_code == 200
        assert "Mini-Dialog zeigen" not in resp.text

    def test_button_shown_when_provider_configured(self, client, sample_sense):
        with patch("deutsch_haufig.config.get_dialogue_provider_config") as mock:
            mock.return_value = {
                "api_key": "sk-test",
                "base_url": "https://example.com/v1",
                "model": "test-model",
            }
            resp = client.get(f"/word/{sample_sense.word_id}")
        assert resp.status_code == 200
        assert "Mini-Dialog zeigen" in resp.text

    def test_cached_dialogue_shows_regenerate(self, client, db_session, sample_sense):
        d = Dialogue(
            sense_id=sample_sense.id,
            text_de="A: Hallo!\nB: Tag!",
            generated_by="test:test-model",
        )
        db_session.add(d)
        db_session.commit()

        with patch("deutsch_haufig.config.get_dialogue_provider_config") as mock:
            mock.return_value = {
                "api_key": "sk-test",
                "base_url": "https://example.com/v1",
                "model": "test-model",
            }
            resp = client.get(f"/word/{sample_sense.word_id}")
        assert resp.status_code == 200
        assert "Neu generieren" in resp.text
        assert "Hallo" in resp.text


# ---------------------------------------------------------------------------
# POST /word/{id}/dialogue/{sense_id}
# ---------------------------------------------------------------------------


class TestGenerateDialogue:
    def test_route_404_on_missing_word(self, client):
        resp = client.post("/word/999/dialogue/1")
        assert resp.status_code == 404

    def test_route_404_on_mismatched_sense(self, client, db_session):
        w = Word(lemma="haben", pos="verb")
        db_session.add(w)
        db_session.flush()
        s = Sense(word_id=w.id)
        db_session.add(s)
        db_session.commit()

        resp = client.post(f"/word/{w.id}/dialogue/99999")
        assert resp.status_code == 404

    def test_generate_caches_and_returns_dialogue(self, client, db_session, sample_sense):
        with patch("deutsch_haufig.routes.word.provider_from_config") as mock_prov:
            mock_prov.return_value = _FakeProvider("A: Test!\nB: OK!")
            resp = client.post(
                f"/word/{sample_sense.word_id}/dialogue/{sample_sense.id}"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_dialogue"] is True
        assert "A: Test!" in data["html"]
        assert "dialogue-box" in data["html"]

        count = db_session.execute(
            select(func.count(Dialogue.id)).where(Dialogue.sense_id == sample_sense.id)
        ).scalar_one()
        assert count == 1

    def test_returns_cached_dialogue(self, client, db_session, sample_sense):
        d = Dialogue(
            sense_id=sample_sense.id,
            text_de="A: Cached!\nB: Yes!",
            generated_by="test:test-model",
        )
        db_session.add(d)
        db_session.commit()

        with patch("deutsch_haufig.routes.word.provider_from_config") as mock_prov:
            resp = client.post(
                f"/word/{sample_sense.word_id}/dialogue/{sample_sense.id}"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "Cached!" in data["html"]
        # Provider should NOT be called
        mock_prov.assert_not_called()

    def test_generation_error_returns_503(self, client, db_session, sample_sense):
        class FailingProvider:
            async def generate(self, lemma, definition_de):
                raise DialogueGenerationError("API down")

        with patch("deutsch_haufig.routes.word.provider_from_config") as mock_prov:
            mock_prov.return_value = FailingProvider()
            resp = client.post(
                f"/word/{sample_sense.word_id}/dialogue/{sample_sense.id}"
            )
        assert resp.status_code == 503
        data = resp.json()
        assert data["has_dialogue"] is False
        assert "konnte nicht generiert" in data["html"]


# ---------------------------------------------------------------------------
# Fake provider for tests
# ---------------------------------------------------------------------------


class _FakeProvider:
    def __init__(self, response: str):
        self._response = response

    async def generate(self, lemma: str, definition_de: str) -> str:
        return self._response
