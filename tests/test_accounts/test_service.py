from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from mailchat.accounts.models import Account
from mailchat.accounts.schemas import AccountConnect
from mailchat.accounts.service import connect, disconnect, list_account_folders, set_sent_folder
from mailchat.mail.imap import ImapCredentials, ImapLoginError, ImapOperationError
from mailchat.shared.exceptions import AccountConnectionError, UnknownFolderError
from mailchat.shared.security import decrypt
from tests.fakes import FakeImap

REQUEST = AccountConnect(
    provider="t-online",
    address="user@t-online.de",
    imap_host="secureimap.t-online.de",
    imap_port=993,
    smtp_host="securesmtp.t-online.de",
    smtp_port=465,
    password=SecretStr("app-specific-secret"),
)


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
async def test_connect_persists_account_on_successful_validation(mock_smtp_ssl, session):
    connected = await connect(session, REQUEST, imap=FakeImap().offer("INBOX", "Sent"))

    password = REQUEST.password.get_secret_value()
    mock_smtp_ssl.return_value.login.assert_called_once_with(REQUEST.address, password)
    assert connected.account.address == REQUEST.address
    assert decrypt(connected.account.credentials.encrypted_password) == password


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
async def test_connect_returns_the_folders_the_server_listed(mock_smtp_ssl, session):
    connected = await connect(session, REQUEST, imap=FakeImap().offer("INBOX", "Gesendet", "Entwürfe"))

    assert connected.folders == ["INBOX", "Gesendet", "Entwürfe"]


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
async def test_connect_leaves_sent_folder_unset_until_the_user_picks(mock_smtp_ssl, session):
    connected = await connect(session, REQUEST, imap=FakeImap().offer("INBOX", "Sent"))

    assert connected.account.sent_folder is None


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
async def test_connect_still_succeeds_when_the_server_refuses_to_list_folders(mock_smtp_ssl, session):
    imap = FakeImap(folders_error=ImapOperationError("LIST failed: NO"))

    connected = await connect(session, REQUEST, imap=imap)

    assert connected.account.address == REQUEST.address
    assert connected.folders == []


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
async def test_list_account_folders_reconnects_with_the_stored_credentials(mock_smtp_ssl, session):
    imap = FakeImap().offer("INBOX", "Sent")
    connected = await connect(session, REQUEST, imap=imap)

    listed = await list_account_folders(session, connected.account.id, imap=imap)

    assert listed.folders == ["INBOX", "Sent"]
    assert imap.seen[-1] == ImapCredentials(
        host=REQUEST.imap_host,
        port=REQUEST.imap_port,
        username=REQUEST.address,
        password=REQUEST.password.get_secret_value(),
    )


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
async def test_list_account_folders_fails_when_the_stored_password_stops_working(mock_smtp_ssl, session):
    imap = FakeImap().offer("INBOX", "Sent")
    connected = await connect(session, REQUEST, imap=imap)
    imap.errors = {REQUEST.address: ImapLoginError("bad credentials")}

    with pytest.raises(AccountConnectionError):
        await list_account_folders(session, connected.account.id, imap=imap)


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
async def test_set_sent_folder_persists_the_selection(mock_smtp_ssl, session):
    imap = FakeImap().offer("INBOX", "Gesendet")
    connected = await connect(session, REQUEST, imap=imap)

    await set_sent_folder(session, connected.account.id, "Gesendet", imap=imap)

    result = await session.execute(select(Account))
    assert result.scalars().one().sent_folder == "Gesendet"


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
async def test_set_sent_folder_rejects_a_folder_the_account_does_not_have(mock_smtp_ssl, session):
    imap = FakeImap().offer("INBOX", "Gesendet")
    connected = await connect(session, REQUEST, imap=imap)

    with pytest.raises(UnknownFolderError):
        await set_sent_folder(session, connected.account.id, "Sent", imap=imap)

    result = await session.execute(select(Account))
    assert result.scalars().one().sent_folder is None


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
async def test_connect_raises_and_does_not_persist_on_imap_failure(mock_smtp_ssl, session):
    imap = FakeImap(errors={REQUEST.address: ImapLoginError("bad credentials")})

    with pytest.raises(AccountConnectionError):
        await connect(session, REQUEST, imap=imap)

    result = await session.execute(select(Account))
    assert result.scalars().first() is None


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
async def test_connect_raises_and_does_not_persist_on_smtp_failure(mock_smtp_ssl, session):
    mock_smtp_ssl.return_value.login.side_effect = Exception("bad credentials")

    with pytest.raises(AccountConnectionError):
        await connect(session, REQUEST, imap=FakeImap().offer("INBOX", "Sent"))

    result = await session.execute(select(Account))
    assert result.scalars().first() is None


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
async def test_disconnect_removes_account(mock_smtp_ssl, session):
    connected = await connect(session, REQUEST, imap=FakeImap().offer("INBOX", "Sent"))

    await disconnect(session, connected.account.id)

    result = await session.execute(select(Account))
    assert result.scalars().first() is None
