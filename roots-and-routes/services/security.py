from __future__ import annotations

import hmac
import secrets

from flask import session


def csrf_token() -> str:
    token = session.get("_csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def valid_csrf_token(candidate: str | None) -> bool:
    expected = session.get("_csrf_token")
    return (
        isinstance(expected, str)
        and isinstance(candidate, str)
        and hmac.compare_digest(expected, candidate)
    )
