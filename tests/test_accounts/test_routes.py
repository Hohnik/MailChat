from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailchat.mail import get_imap
from mailchat.mail.imap import ImapLoginError, ImapOperationError
from mailchat.main import create_app
from mailchat.shared.db import get_db
from tests.fakes import FakeImap

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
def imap() -> FakeImap:
    """The IMAP server the app talks to for the whole test; seed it per test."""
    return FakeImap()


@pytest.fixture
def client(session_factory: async_sessionmaker[AsyncSession], imap: FakeImap):
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_imap] = lambda: imap

    with TestClient(app) as test_client:
        yield test_client


def test_accounts_page_renders_form(client):
    response = client.get("/accounts")

    assert response.status_code == 200
    assert '<form hx-post="/accounts"' in response.text
    assert "No accounts connected yet." in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_submitted_account_appears_in_list(mock_smtp_ssl, client, imap):
    imap.offer("INBOX", "Sent")

    response = client.post("/accounts", data=ACCOUNT_FORM_DATA)

    assert response.status_code == 200
    assert "user@t-online.de" in response.text
    assert "No accounts connected yet." not in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_connection_failure_shows_error_and_does_not_list_account(mock_smtp_ssl, client, imap):
    imap.errors = {"user@t-online.de": ImapLoginError("bad credentials")}

    response = client.post("/accounts", data=ACCOUNT_FORM_DATA)

    assert response.status_code == 200
    assert "Could not connect" in response.text
    assert "No accounts connected yet." in response.text
    assert "sent_folder" not in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_multiple_accounts_are_all_listed(mock_smtp_ssl, client, imap):
    imap.offer("INBOX", "Sent")
    for address in ("first@t-online.de", "second@t-online.de"):
        client.post("/accounts", data={**ACCOUNT_FORM_DATA, "address": address})

    response = client.get("/accounts")

    assert "first@t-online.de" in response.text
    assert "second@t-online.de" in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_disconnect_removes_account_from_list(mock_smtp_ssl, client, imap):
    imap.offer("INBOX", "Sent")
    client.post("/accounts", data=ACCOUNT_FORM_DATA)

    response = client.post("/accounts/1/disconnect")

    assert response.status_code == 200
    assert "user@t-online.de" not in response.text
    assert "No accounts connected yet." in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_connecting_offers_a_picker_of_the_servers_folders(mock_smtp_ssl, client, imap):
    imap.offer("INBOX", "Sent", "Drafts")

    response = client.post("/accounts", data=ACCOUNT_FORM_DATA)

    assert '<select name="sent_folder"' in response.text
    for folder in ("INBOX", "Sent", "Drafts"):
        assert f'<option value="{folder}"' in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_picker_preselects_sent_when_the_server_has_it(mock_smtp_ssl, client, imap):
    imap.offer("INBOX", "Sent", "Drafts")

    response = client.post("/accounts", data=ACCOUNT_FORM_DATA)

    assert '<option value="Sent" selected>Sent</option>' in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_picker_preselects_no_folder_when_the_server_has_no_sent(mock_smtp_ssl, client, imap):
    imap.offer("INBOX", "Gesendet", "Entwürfe")

    response = client.post("/accounts", data=ACCOUNT_FORM_DATA)

    assert "selected>Gesendet</option>" not in response.text
    assert "selected>INBOX</option>" not in response.text
    assert "Choose a folder" in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_chosen_sent_folder_is_stored_and_listed(mock_smtp_ssl, client, imap):
    imap.offer("INBOX", "Gesendet")
    client.post("/accounts", data=ACCOUNT_FORM_DATA)

    response = client.post("/accounts/1/sent-folder", data={"sent_folder": "Gesendet"})

    assert response.status_code == 200
    assert "Sent folder: Gesendet" in response.text
    assert "Sent folder: Gesendet" in client.get("/accounts").text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_account_without_a_sent_folder_can_pick_one_later(mock_smtp_ssl, client, imap):
    imap.offer("INBOX", "Gesendet")
    client.post("/accounts", data=ACCOUNT_FORM_DATA)

    response = client.get("/accounts/1/sent-folder")

    assert response.status_code == 200
    assert '<option value="Gesendet"' in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_account_connects_without_a_picker_when_folders_cannot_be_listed(mock_smtp_ssl, client, imap):
    imap.folders_error = ImapOperationError("LIST failed: NO")

    response = client.post("/accounts", data=ACCOUNT_FORM_DATA)

    assert "user@t-online.de" in response.text
    assert '<select name="sent_folder"' not in response.text
    assert "Choose sent folder" in response.text


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_choosing_a_folder_the_server_lacks_shows_an_error(mock_smtp_ssl, client, imap):
    imap.offer("INBOX", "Gesendet")
    client.post("/accounts", data=ACCOUNT_FORM_DATA)

    response = client.post("/accounts/1/sent-folder", data={"sent_folder": "Sent"})

    assert response.status_code == 200
    assert "No folder named" in response.text
