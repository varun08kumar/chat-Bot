"""Verify-only JWT handling.

metrics-service never issues tokens (that's chat-service's job, see
``apps/chat-service/app/services/auth.py``) — it only needs to verify the
same access-token cookie the browser already sends, using the same shared
``JWT_SECRET``, so the dashboard can be scoped to the requesting user.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt

from app.config import Settings


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    token_type: str


class TokenError(Exception):
    """Raised for any invalid, expired, or wrong-type token."""


def verify_token(token: str, *, expected_type: str, settings: Settings) -> TokenPayload:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"expected a {expected_type} token, got {payload.get('type')}")
    return TokenPayload(user_id=payload["sub"], token_type=payload["type"])
