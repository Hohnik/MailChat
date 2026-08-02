from __future__ import annotations

from collections.abc import AsyncIterator
from sqlite3 import Connection

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Database:
    """One database MailChat runs on. It owns the engine and hands out
    `sessions`, the factory every caller opens sessions with; no caller — the
    app, the sync worker, a test — ever sees an engine.

    aiosqlite's default busy_timeout is 0: a writer that finds the database
    locked by another connection fails immediately instead of waiting. Several
    accounts sync concurrently (see sync/worker.py), so a 30s timeout gives a
    second writer room to wait its turn rather than erroring. WAL mode lets
    readers (htmx routes) proceed without blocking on the sync worker's writes.
    """

    def __init__(self, url: str) -> None:
        self._engine = create_async_engine(url, connect_args={"timeout": 30})
        event.listen(self._engine.sync_engine, "connect", _set_sqlite_pragma)
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def create_tables(self) -> None:
        """Every table MailChat stores, for a database that may not have them yet."""
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        """Let go of every connection the database holds open."""
        await self._engine.dispose()


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One session on the database the app was built with, for one request."""
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def _set_sqlite_pragma(dbapi_connection: Connection, _connection_record: object) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
