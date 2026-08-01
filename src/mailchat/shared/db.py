from __future__ import annotations

from collections.abc import AsyncIterator
from sqlite3 import Connection

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from mailchat.config import settings


class Base(DeclarativeBase):
    pass


# aiosqlite's default busy_timeout is 0: a writer that finds the database
# locked by another connection fails immediately instead of waiting. Several
# accounts sync concurrently (see sync/worker.py), so a 30s timeout gives a
# second writer room to wait its turn rather than erroring. WAL mode lets
# readers (htmx routes) proceed without blocking on the sync worker's writes.
engine = create_async_engine(settings.database_url, connect_args={"timeout": 30})


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection: Connection, _connection_record: object) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
