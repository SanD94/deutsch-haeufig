"""Behavioral tests for M0 — Project skeleton.

These tests pin the M0 acceptance criteria from ROADMAP.md:

  - FastAPI app exists and is importable.
  - `GET /` renders a "Hello, Deutschland" landing page.
  - `GET /browse` renders an (empty) browse page.
  - SQLite schema can be created from the ORM metadata with no rows.

They are deliberately black-box: they exercise the public HTTP surface and
the public DB bootstrap, not internal helpers, so the skeleton can be
re-implemented freely as long as the demo behavior holds.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# --- App wiring ------------------------------------------------------------


def test_app_is_a_fastapi_instance() -> None:
    from deutsch_haufig.main import app

    assert isinstance(app, FastAPI)


@pytest.fixture()
def client() -> TestClient:
    from deutsch_haufig.main import app

    return TestClient(app)


# --- HTTP surface ----------------------------------------------------------


def test_root_renders_hello_deutschland(client: TestClient) -> None:
    """ROADMAP M0: `uv run web` serves a 'Hello, Deutschland' page at /."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Hello, Deutschland" in response.text


def test_root_is_html(client: TestClient) -> None:
    response = client.get("/")
    assert response.headers["content-type"].startswith("text/html")


def test_browse_page_renders_empty(client: TestClient) -> None:
    """ROADMAP M0 demo: open localhost:8000 → empty browse page renders."""
    response = client.get("/browse")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_unknown_route_returns_404(client: TestClient) -> None:
    response = client.get("/this-route-does-not-exist")
    assert response.status_code == 404


# --- Database bootstrap ----------------------------------------------------


def test_metadata_creates_empty_schema(tmp_path) -> None:
    """ROADMAP M0: SQLite + create_all yields an empty schema we can open."""
    from sqlalchemy import create_engine, inspect

    from deutsch_haufig.models import Base

    db_path = tmp_path / "m0.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    tables = set(inspect(engine).get_table_names())
    # The PLAN §3 entities should at minimum be present after create_all.
    expected = {"words", "senses", "examples", "dialogues", "users",
                "review_cards", "review_logs"}
    missing = expected - tables
    assert not missing, f"missing tables after create_all: {sorted(missing)}"

    # Schema is empty: every expected table has zero rows.
    with engine.connect() as conn:
        from sqlalchemy import text

        for table in expected:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            assert count == 0, f"{table} should be empty in a fresh schema"
