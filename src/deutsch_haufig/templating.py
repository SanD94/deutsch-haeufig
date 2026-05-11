"""Shared Jinja2Templates instance used by every route module."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates

from deutsch_haufig.i18n import resolve_lang, translate

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


# ---------------------------------------------------------------------------
# i18n: inject ``_t`` function and ``_lang`` into every template response
# ---------------------------------------------------------------------------


def template_response(
    request,
    template_name: str,
    context: dict | None = None,
    **kwargs,
):
    """Like ``templates.TemplateResponse`` but auto-injects i18n context."""
    ctx = dict(context or {})
    lang = resolve_lang(request)
    ctx.setdefault("_lang", lang)
    ctx.setdefault("_t", lambda key, **kw: translate(key, lang, **kw))
    ctx.setdefault("_langs", {"de": "Deutsch", "en": "English", "tr": "Türkçe"})
    return templates.TemplateResponse(request, template_name, ctx, **kwargs)
