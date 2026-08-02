from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailchat.accounts import repository as accounts_repository
from mailchat.main import create_app
from mailchat.shared.db import Database
from mailchat.shared.security import encrypt


@dataclass
class FakeSyncWorker:
    """Stands in for the poll loop wherever the app takes a `SyncWorker`. Records
    the sessions it was started on, then — like the real one — never returns."""

    started_on: list[async_sessionmaker[AsyncSession]] = field(default_factory=list)

    async def __call__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.started_on.append(session_factory)
        await asyncio.Event().wait()


def test_app_syncs_the_database_it_was_given(database: Database):
    worker = FakeSyncWorker()

    with TestClient(create_app(database, sync_worker=worker)) as client:
        client.get("/accounts")

    assert worker.started_on == [database.sessions]


async def test_routes_read_the_database_the_app_was_given(database: Database):
    async with database.sessions() as session:
        await accounts_repository.create_account(
            session,
            provider="t-online",
            address="user@t-online.de",
            imap_host="secureimap.t-online.de",
            imap_port=993,
            smtp_host="securesmtp.t-online.de",
            smtp_port=465,
            encrypted_password=encrypt("app-specific-secret"),
        )

    with TestClient(create_app(database, sync_worker=None)) as client:
        response = client.get("/accounts")

    assert "user@t-online.de" in response.text
