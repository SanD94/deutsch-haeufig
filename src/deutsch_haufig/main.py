"""FastAPI entrypoint for deutsch-haufig.

Exposes:

  - ``GET /``        → "Hello, Deutschland" landing page (M0).
  - ``GET /browse``  → seed-corpus browse with vocabeo-style filters (M1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from deutsch_haufig.db import init_db
from deutsch_haufig.routes.browse import router as browse_router
from deutsch_haufig.routes.learn import router as learn_router
from deutsch_haufig.routes.word import router as word_router
from deutsch_haufig.templating import templates


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="deutsch-haufig", version="0.0.1", lifespan=lifespan)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", {"title": "Hello, Deutschland"})

    app.include_router(browse_router)
    app.include_router(word_router)
    app.include_router(learn_router)
    return app


app = create_app()


def run() -> None:
    """Console-script entry: ``uv run web``."""
    import uvicorn

    uvicorn.run(
        "deutsch_haufig.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    run()
