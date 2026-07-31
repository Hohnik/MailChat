from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailchat.main import create_app
from mailchat.shared.db import get_db

ACCOUNT_FORM_DATA = {
    "provider": "t-online",
    "address": "user@t-online.de",
    "imap_host": "secureimap.t-online.de",
    "imap_port": 993,
    "smtp_host": "securesmtp.t-online.de",
    "smtp_port": 465,
    "password": "app-specific-secret",
}


@pytest.fixture
def client(session_factory: async_sessionmaker[AsyncSession]):
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client


def test_accounts_page_renders_form(client):
    response = client.get("/accounts")

    assert response.status_code == 200
    assert '<form hx-post="/accounts"' in response.text
    assert "No accounts connected yet." in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
def test_submitted_account_appears_in_list(mock_imap_ssl, mock_smtp_ssl, client):
    response = client.post("/accounts", data=ACCOUNT_FORM_DATA)

    assert response.status_code == 200
    assert "user@t-online.de" in response.text
    assert "No accounts connected yet." not in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
def test_connection_failure_shows_error_and_does_not_list_account(mock_imap_ssl, mock_smtp_ssl, client):
    mock_imap_ssl.return_value.login.side_effect = Exception("bad credentials")

    response = client.post("/accounts", data=ACCOUNT_FORM_DATA)

    assert response.status_code == 200
    assert "Could not connect" in response.text
    assert "No accounts connected yet." in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
def test_multiple_accounts_are_all_listed(mock_imap_ssl, mock_smtp_ssl, client):
    for address in ("first@t-online.de", "second@t-online.de"):
        client.post("/accounts", data={**ACCOUNT_FORM_DATA, "address": address})

    response = client.get("/accounts")

    assert "first@t-online.de" in response.text
    assert "second@t-online.de" in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
def test_disconnect_removes_account_from_list(mock_imap_ssl, mock_smtp_ssl, client):
    client.post("/accounts", data=ACCOUNT_FORM_DATA)

    response = client.post("/accounts/1/disconnect")

    assert response.status_code == 200
    assert "user@t-online.de" not in response.text
    assert "No accounts connected yet." in response.text
