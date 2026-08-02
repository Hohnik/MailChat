from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailchat.mail import get_imap, get_smtp
from mailchat.main import create_app
from mailchat.shared.db import Database
from tests.fakes import FakeImap, FakeSmtp


def pytest_configure() -> None:
    """MailChat won't encrypt credentials without a key, and no test cares which
    one it gets. Nothing reads the settings at import, so this only has to land
    before the first test that reaches for the key — no import order to keep.
    """
    os.environ.setdefault("MAILCHAT_CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())


@pytest.fixture
async def database(tmp_path) -> AsyncIterator[Database]:
    """The database for one test — hand it to `create_app` and the app under
    test reads and writes the same rows the test does."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.create_tables()

    yield database

    await database.close()


@pytest.fixture
def session_factory(database: Database) -> async_sessionmaker[AsyncSession]:
    """What a caller that only opens sessions — the sync worker — is handed."""
    return database.sessions


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as db_session:
        yield db_session


@pytest.fixture
def imap() -> FakeImap:
    """The IMAP server the app talks to for the whole test; seed it per test."""
    return FakeImap()


@pytest.fixture
def smtp() -> FakeSmtp:
    """The SMTP server the app talks to for the whole test; it accepts every login."""
    return FakeSmtp()


@pytest.fixture
def client(database: Database, imap: FakeImap, smtp: FakeSmtp) -> Iterator[TestClient]:
    """The app a route test drives: the test's own database, fake mail servers,
    and no sync worker."""
    app = create_app(database, sync_worker=None)
    app.dependency_overrides[get_imap] = lambda: imap
    app.dependency_overrides[get_smtp] = lambda: smtp

    with TestClient(app) as test_client:
        yield test_client
