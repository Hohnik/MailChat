from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select

from mailchat.accounts.models import Account
from mailchat.accounts.schemas import AccountConnect
from mailchat.accounts.service import connect, disconnect
from mailchat.shared.exceptions import AccountConnectionError
from mailchat.shared.security import decrypt

REQUEST = AccountConnect(
    provider="t-online",
    address="user@t-online.de",
    imap_host="secureimap.t-online.de",
    imap_port=993,
    smtp_host="securesmtp.t-online.de",
    smtp_port=465,
    password="app-specific-secret",
)


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
async def test_connect_persists_account_on_successful_validation(mock_imap_ssl, mock_smtp_ssl, session):
    account = await connect(session, REQUEST)

    mock_imap_ssl.return_value.login.assert_called_once_with(REQUEST.address, REQUEST.password)
    mock_smtp_ssl.return_value.login.assert_called_once_with(REQUEST.address, REQUEST.password)
    assert account.address == REQUEST.address
    assert decrypt(account.credentials.encrypted_password) == REQUEST.password


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
async def test_connect_raises_and_does_not_persist_on_imap_failure(mock_imap_ssl, mock_smtp_ssl, session):
    mock_imap_ssl.return_value.login.side_effect = Exception("bad credentials")

    with pytest.raises(AccountConnectionError):
        await connect(session, REQUEST)

    result = await session.execute(select(Account))
    assert result.scalars().first() is None


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
async def test_connect_raises_and_does_not_persist_on_smtp_failure(mock_imap_ssl, mock_smtp_ssl, session):
    mock_smtp_ssl.return_value.login.side_effect = Exception("bad credentials")

    with pytest.raises(AccountConnectionError):
        await connect(session, REQUEST)

    result = await session.execute(select(Account))
    assert result.scalars().first() is None


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
async def test_disconnect_removes_account(mock_imap_ssl, mock_smtp_ssl, session):
    account = await connect(session, REQUEST)

    await disconnect(session, account.id)

    result = await session.execute(select(Account))
    assert result.scalars().first() is None
