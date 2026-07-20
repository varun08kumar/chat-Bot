"""Password hashing and JWT issuing/verification.

Two tokens, both short opaque JWTs signed with the same server secret:

- **Access token** (``token_type: "access"``) — sent as a cookie on every
  request, short-lived (``access_token_ttl_s``, default 3 minutes). This is
  what ``get_identity`` actually verifies; a stolen access token is only
  useful for a few minutes.
- **Refresh token** (``token_type: "refresh"``) — long-lived, only ever sent
  to ``POST /auth/refresh``, which exchanges it for a fresh access token
  (and a fresh refresh token, rotating it). Keeping the two separate — and
  checking ``token_type`` on every verification — means a leaked access
  token can never be replayed against the refresh endpoint to mint new
  sessions indefinitely.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import bcrypt
import jwt

from app.config import Settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        # Malformed stored hash — never let this crash into a 500 that
        # might hint at *why* verification failed.
        return False


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    token_type: str  # "access" | "refresh"
    jti: str  # unique per token; not checked against a revocation list here,
    # but present so one exists if a blocklist is added later.


class TokenError(Exception):
    """Raised for any invalid, expired, or wrong-type token."""


def _create_token(*, user_id: str, token_type: str, ttl_s: int, settings: Settings) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + ttl_s,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, settings: Settings) -> str:
    return _create_token(user_id=user_id, token_type="access", ttl_s=settings.access_token_ttl_s, settings=settings)


def create_refresh_token(user_id: str, settings: Settings) -> str:
    return _create_token(user_id=user_id, token_type="refresh", ttl_s=settings.refresh_token_ttl_s, settings=settings)


def verify_token(token: str, *, expected_type: str, settings: Settings) -> TokenPayload:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"expected a {expected_type} token, got {payload.get('type')}")
    return TokenPayload(user_id=payload["sub"], token_type=payload["type"], jti=payload["jti"])
