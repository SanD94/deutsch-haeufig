"""FastAPI entrypoint for deutsch-haufig.

Exposes the M0 demo surface:

  - `GET /`        → "Hello, Deutschland" landing page.
  - `GET /browse`  → empty browse page (filled in M1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from deutsch_haufig.db import init_db

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="deutsch-haufig", version="0.0.1", lifespan=lifespan)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "index.html", {"title": "Hello, Deutschland"}
        )

    @app.get("/browse", response_class=HTMLResponse)
    def browse(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "browse.html", {"title": "Browse", "words": []}
        )

    return app


app = create_app()


def run() -> None:
    """Console-script entry: `uv run web`."""
    import uvicorn

    uvicorn.run(
        "deutsch_haufig.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    run()
