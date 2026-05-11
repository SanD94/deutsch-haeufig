"""Auth routes — email magic-link login (M6).

Uses itsdangerous for signed tokens.  SMTP is optional — when not configured,
tokens are printed to stdout (dev mode).
"""

from __future__ import annotations

import json
import smtplib
from email.mime.text import MIMEText
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from deutsch_haufig.config import settings
from deutsch_haufig.db import get_session
from deutsch_haufig.models import User
from deutsch_haufig.scheduler import FSRSScheduler
from deutsch_haufig.templating import template_response

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


def _get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="auth-magic-link")


@router.get("/auth/login", response_class=HTMLResponse)
def login_page(request: Request):
    return template_response(
        request,
        "auth_login.html",
        {"title": "Login", "smtp_configured": bool(settings.smtp_host)},
    )


@router.post("/auth/send-link")
async def send_magic_link(
    request: Request,
    session: SessionDep,
    email: str = Form(),
):
    s = _get_serializer()
    token = s.dumps(email)
    link = f"{settings.app_url}/auth/verify?token={token}"

    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            settings_json=json.dumps(
                {
                    "new_per_day": FSRSScheduler.DEFAULT_NEW_PER_DAY,
                    "reviews_per_day": FSRSScheduler.DEFAULT_REVIEWS_PER_DAY,
                    "desired_retention": 0.9,
                }
            ),
        )
        session.add(user)
        session.commit()

    if settings.smtp_host:
        await _send_email(email, link)
    else:
        print(f"[auth] Magic link for {email}: {link}")

    return template_response(
        request,
        "auth_sent.html",
        {"title": "Link gesendet", "email": email},
    )


@router.get("/auth/verify")
def verify_magic_link(
    request: Request,
    session: SessionDep,
    token: str = "",
):
    s = _get_serializer()
    max_age = 3600
    try:
        email = s.loads(token, max_age=max_age)
    except Exception:
        return template_response(
            request,
            "auth_error.html",
            {"title": "Fehler", "error": "Link ungültig oder abgelaufen."},
            status_code=400,
        )

    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        return template_response(
            request,
            "auth_error.html",
            {"title": "Fehler", "error": "Benutzer nicht gefunden."},
            status_code=400,
        )

    resp = RedirectResponse(url="/learn", status_code=303)
    resp.set_cookie(
        "dh_user_id",
        str(user.id),
        max_age=365 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.get("/auth/logout")
def logout():
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie("dh_user_id")
    return resp


async def _send_email(to: str, link: str) -> None:
    msg = MIMEText(
        f"Hier ist dein Login-Link für deutsch-häufig:\n\n{link}\n\nDer Link ist 1 Stunde gültig.\n"
    )
    msg["Subject"] = "Dein Login-Link für deutsch-häufig"
    msg["From"] = settings.from_email
    msg["To"] = to

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_user:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
