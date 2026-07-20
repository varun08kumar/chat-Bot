"""Auth endpoints: register, login, refresh, logout, and the current user.

Both JWTs are set as httpOnly cookies (never readable by JavaScript, so
immune to theft via XSS) — see app/services/auth.py for what each token is
for. A third, non-httpOnly `csrf_token` cookie is set alongside them for the
double-submit CSRF pattern: the frontend reads it and echoes it back as an
`X-CSRF-Token` header on mutating requests, and `dependencies.py` verifies
the two match. httpOnly cookies alone don't protect against CSRF (the
browser attaches them automatically to *any* site's request to this origin);
this is what does.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from app.api.schemas import LoginRequest, RegisterRequest, UserOut
from app.config import Settings, get_settings
from app.dependencies import get_db
from app.repositories.user_repository import UserRepository
from app.services.auth import (
    TokenError,
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from llm_obs_shared.db.session import Database

router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"


def _set_session_cookies(response: Response, *, user_id: str, settings: Settings) -> None:
    access = create_access_token(user_id, settings)
    refresh = create_refresh_token(user_id, settings)
    csrf = secrets.token_urlsafe(32)

    common = dict(path="/", secure=settings.cookie_secure, samesite="lax")
    response.set_cookie(ACCESS_COOKIE, access, max_age=settings.access_token_ttl_s, httponly=True, **common)
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=settings.refresh_token_ttl_s, httponly=True, **common)
    # Deliberately NOT httponly — the frontend must be able to read this one.
    response.set_cookie(CSRF_COOKIE, csrf, max_age=settings.refresh_token_ttl_s, httponly=False, **common)


def _clear_session_cookies(response: Response) -> None:
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/")


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    response: Response,
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserOut:
    async with db.session() as session:
        repo = UserRepository(session)
        if await repo.get_by_email(payload.email) is not None:
            raise HTTPException(status_code=409, detail="An account with that email already exists")
        user = await repo.create(email=payload.email, password_hash=hash_password(payload.password))
        user_out = UserOut(id=user.id, email=user.email, is_admin=user.is_admin, created_at=user.created_at)

    _set_session_cookies(response, user_id=user_out.id, settings=settings)
    return user_out


@router.post("/login", response_model=UserOut)
async def login(
    payload: LoginRequest,
    response: Response,
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserOut:
    async with db.session() as session:
        repo = UserRepository(session)
        user = await repo.get_by_email(payload.email)
        # Same error for "no such user" and "wrong password" - don't let a
        # login form reveal which emails are registered.
        if user is None or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Incorrect email or password")
        user_out = UserOut(id=user.id, email=user.email, is_admin=user.is_admin, created_at=user.created_at)

    _set_session_cookies(response, user_id=user_out.id, settings=settings)
    return user_out


@router.post("/refresh", response_model=UserOut)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserOut:
    if refresh_token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = verify_token(refresh_token, expected_type="refresh", settings=settings)
    except TokenError:
        raise HTTPException(status_code=401, detail="Session expired, please log in again")

    async with db.session() as session:
        user = await UserRepository(session).get_by_id(payload.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Session expired, please log in again")
        user_out = UserOut(id=user.id, email=user.email, is_admin=user.is_admin, created_at=user.created_at)

    # Issue a fresh pair (not just a new access token). Note this is
    # reissuance, not revocation: these are stateless JWTs with no
    # server-side blocklist, so the *old* refresh token remains technically
    # valid until it expires on its own rather than being invalidated here.
    # A production version would track spent `jti`s (e.g. in Redis, already
    # in this stack) to reject reuse of a rotated-out refresh token.
    _set_session_cookies(response, user_id=user_out.id, settings=settings)
    return user_out


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    _clear_session_cookies(response)
    return {"logged_out": True}


@router.get("/me", response_model=UserOut)
async def me(
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserOut:
    if access_token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = verify_token(access_token, expected_type="access", settings=settings)
    except TokenError:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with db.session() as session:
        user = await UserRepository(session).get_by_id(payload.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return UserOut(id=user.id, email=user.email, is_admin=user.is_admin, created_at=user.created_at)
