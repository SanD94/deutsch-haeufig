# AGENTS.md — deutsch-haufig

Web app to learn most-frequent German words with German-only definitions (dwds.de), rich examples, and FSRS spaced repetition. See [PLAN.md](./PLAN.md) and [ROADMAP.md](./ROADMAP.md) for full context. **Status: pre-code; only PLAN/ROADMAP exist.** Honor the planned layout and stack below when adding code.

## Stack
Python 3.13 · FastAPI · SQLAlchemy 2.x + SQLite (`app.db`) · Pydantic · Jinja2 + HTMX + Alpine.js + Tailwind · httpx + selectolax (scraping) · `fsrs` PyPI pkg · pytest · uv + `pyproject.toml`.

## Commands (planned; create as part of PoC)
- Install: `uv sync`
- Run web: `uv run web` (FastAPI at http://localhost:8000)
- Ingest seed corpus: `uv run ingest` (or `python -m deutsch_haufig.ingest`)
- Test all: `uv run pytest`
- Single test: `uv run pytest tests/test_scheduler.py::test_name -q`
- Lint/format: `uv run ruff check .` and `uv run ruff format .`

## Architecture
Code lives under `src/deutsch_haufig/`: `main.py` (FastAPI entry), `db.py`, `models.py` (Word, Sense, Example, Dialogue, User, ReviewCard, ReviewLog), `schemas.py`, `scheduler/` (FSRS + SM-2 behind a `Scheduler` interface), `ingest/` (`vocabeo.py`, `dwds.py`, `pipeline.py`), `dialogue/` (provider interface, on-demand LLM, cached in DB), `routes/` (`browse`, `word`, `learn`, `api`), `templates/` (Jinja2 + HTMX partials). Data: `data/vocabeo_seed.jsonl`, `data/dwds_cache/`. Ingest is idempotent on `(lemma, pos)`.

## Conventions
- Type hints everywhere; Pydantic v2 models for I/O; SQLAlchemy 2.x typed `Mapped[...]` ORM.
- snake_case modules/functions, PascalCase classes, UPPER_SNAKE constants.
- Imports: stdlib → third-party → local, separated by blank lines (ruff/isort).
- Async-first in FastAPI routes and httpx scrapers; never block the loop.
- Keep external integrations behind interfaces (`Scheduler`, `DialogueProvider`) for mocking.
- Cache scraped HTML to `data/dwds_cache/`; one fixture per word for parser tests.
- Errors: raise typed exceptions in `ingest`/`scheduler`; convert to `HTTPException` at route boundaries; never swallow.
- Respect dwds/vocabeo ToS: single low-rate ingest, no redistribution of raw seed.
- `app.db` and `data/dwds_cache/` are gitignored.

