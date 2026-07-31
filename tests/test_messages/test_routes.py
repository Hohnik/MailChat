from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailchat.accounts import repository as accounts_repository
from mailchat.main import create_app
from mailchat.messages.models import Message
from mailchat.shared.db import get_db
from mailchat.shared.security import encrypt


@pytest.fixture
def client(session_factory: async_sessionmaker[AsyncSession]):
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client


async def _seed_account_with_messages(session_factory, *, message_count: int = 2):
    async with session_factory() as session:
        account = await accounts_repository.create_account(
            session,
            provider="t-online",
            address="user@t-online.de",
            imap_host="secureimap.t-online.de",
            imap_port=993,
            smtp_host="securesmtp.t-online.de",
            smtp_port=465,
            encrypted_password=encrypt("app-specific-secret"),
        )
        for i in range(message_count):
            session.add(
                Message(
                    account_id=account.id,
                    message_id=f"<msg-{i}@example.com>",
                    subject=f"Subject {i}",
                    from_header="sender@example.com",
                    to_header="user@t-online.de",
                    body="body",
                )
            )
        await session.commit()
        return account


async def test_messages_page_renders_placeholder_when_empty(session_factory, client):
    account = await _seed_account_with_messages(session_factory, message_count=0)

    response = client.get(f"/accounts/{account.id}/messages")

    assert response.status_code == 200
    assert "No messages synced yet." in response.text


async def test_messages_page_lists_seeded_messages(session_factory, client):
    account = await _seed_account_with_messages(session_factory, message_count=2)

    response = client.get(f"/accounts/{account.id}/messages")

    assert response.status_code == 200
    assert "Subject 0" in response.text
    assert "Subject 1" in response.text


async def test_messages_list_fragment_used_for_polling(session_factory, client):
    account = await _seed_account_with_messages(session_factory, message_count=1)

    response = client.get(f"/accounts/{account.id}/messages/list")

    assert response.status_code == 200
    assert "Subject 0" in response.text
    assert "<html" not in response.text


async def test_messages_page_404s_for_unknown_account(client):
    response = client.get("/accounts/999/messages")

    assert response.status_code == 404
