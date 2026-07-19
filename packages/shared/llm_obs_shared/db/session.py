"""Async database engine and session lifecycle management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """Owns the async engine and hands out sessions.

    A single instance lives for the process lifetime and is created/disposed in
    the FastAPI (or worker) lifespan.
    """

    def __init__(
        self,
        dsn: str,
        *,
        echo: bool = False,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_pre_ping: bool = True,
    ) -> None:
        self._engine: AsyncEngine = create_async_engine(
            dsn,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=pool_pre_ping,
            pool_recycle=1800,
        )
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session inside a transaction; commit on success, rollback on error."""

        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def healthcheck(self) -> bool:
        """Return True if a trivial round-trip to the database succeeds."""

        from sqlalchemy import text

        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001
            return False
