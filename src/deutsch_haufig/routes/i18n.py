"""Language-switching route."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from deutsch_haufig.i18n import SUPPORTED_LANGS

router = APIRouter()


@router.get("/lang/{lang}")
def set_language(lang: str, request: Request):
    """Set language via cookie and redirect back."""
    if lang not in SUPPORTED_LANGS:
        lang = "de"

    referer = request.headers.get("referer", "/")
    resp = RedirectResponse(url=referer, status_code=303)
    resp.set_cookie(
        "dh_lang",
        lang,
        max_age=365 * 24 * 3600,  # 1 year
        httponly=True,
        samesite="lax",
    )
    return resp
