"""Internationalisation (i18n) support for deutsch-haufig.

Translations live in ``src/deutsch_haufig/i18n/{lang}.json``.

Language selection is resolved from:
1. ``lang`` query parameter (e.g. ``?lang=tr``)
2. ``dh_lang`` cookie
3. ``Accept-Language`` header (first matching prefix)
4. Default: ``de``

The active language is injected into the Jinja2 template context as ``_lang``
and a ``_t`` filter is registered for translating strings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Request

I18N_DIR = Path(__file__).resolve().parent

SUPPORTED_LANGS = {"de", "en", "tr"}
DEFAULT_LANG = "de"

_translations: dict[str, dict[str, str]] = {}


def _load_translations() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for path in I18N_DIR.glob("*.json"):
        lang = path.stem
        try:
            result[lang] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return result


def get_translations() -> dict[str, dict[str, str]]:
    global _translations
    if not _translations:
        _translations = _load_translations()
    return _translations


def resolve_lang(request: Request) -> str:
    """Determine the active language for the current request."""
    # 1. Query parameter
    qlang = request.query_params.get("lang")
    if qlang in SUPPORTED_LANGS:
        return qlang

    # 2. Cookie
    clang = request.cookies.get("dh_lang")
    if clang in SUPPORTED_LANGS:
        return clang

    # 3. Accept-Language header
    accept = request.headers.get("accept-language", "")
    for part in accept.split(","):
        code = part.split(";")[0].strip().split("-")[0].split("_")[0]
        if code in SUPPORTED_LANGS:
            return code

    return DEFAULT_LANG


def translate(key: str, lang: str, **kwargs: Any) -> str:
    """Look up ``key`` in the translation file for ``lang``.

    Falls back to the key itself if no translation is found.
    Supports ``{{ placeholder }}`` substitution via ``**kwargs``.
    """
    translations = get_translations()
    table = translations.get(lang, {})
    text = table.get(key, key)
    if kwargs:
        for k, v in kwargs.items():
            text = text.replace("{{ " + k + " }}", str(v))
    return text


def jinja_translate(key: str, **kwargs: Any) -> str:
    """Jinja2 filter: ``{{ 'browse.title' | _t }}`` or ``{{ 'browse.count' | _t(count=5) }}``.

    The language is taken from the template context's ``_lang`` variable.
    """
    # This will be called with the context having _lang available
    # But as a filter it only receives the key and kwargs
    # We use a global/context variable set in the template
    raise RuntimeError("Use _t as a Jinja2 global function or pass lang explicitly")


def t_filter(key: str, lang: str = DEFAULT_LANG, **kwargs: Any) -> str:
    """Jinja2 filter: ``{{ 'browse.title' | t('de') }}``."""
    return translate(key, lang, **kwargs)
