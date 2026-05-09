"""Shared Jinja2Templates instance used by every route module."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def build_query_string(
    filters: dict,
    limit: int,
    offset: int,
) -> str:
    """Build a query string for pagination links preserving current filters."""
    params = {}
    for k, v in filters.items():
        if v is not None and v != "":
            params[k] = v
    params["limit"] = str(limit)
    params["offset"] = str(offset)
    return urlencode(params)


templates.env.globals["_build_q"] = build_query_string
