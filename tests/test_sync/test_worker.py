from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from mailchat.accounts import repository as accounts_repository
from mailchat.messages import repository as messages_repository
from mailchat.shared.security import encrypt
from mailchat.sync.worker import sync_account, sync_all_accounts

FIXTURES = Path(__file__).parent.parent / "fixtures" / "emails"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


async def _create_account(session, *, address="user@t-online.de", imap_host="secureimap.t-online.de"):
    return await accounts_repository.create_account(
        session,
        provider="t-online",
        address=address,
        imap_host=imap_host,
        imap_port=993,
        smtp_host="securesmtp.t-online.de",
        smtp_port=465,
        encrypted_password=encrypt("app-specific-secret"),
    )


def _connection_returning(raw_message: bytes) -> MagicMock:
    connection = MagicMock()
    connection.select.return_value = ("OK", [b"1"])
    connection.search.return_value = ("OK", [b"1"])
    connection.fetch.return_value = ("OK", [(b"1 (RFC822 {n}", raw_message)])
    return connection


def _slow_connection_returning(raw_message: bytes, delay_seconds: float) -> MagicMock:
    connection = MagicMock()
    connection.select.return_value = ("OK", [b"1"])
    connection.search.return_value = ("OK", [b"1"])

    def slow_fetch(*args, **kwargs):
        time.sleep(delay_seconds)
        return ("OK", [(b"1 (RFC822 {n}", raw_message)])

    connection.fetch.side_effect = slow_fetch
    return connection


@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
async def test_sync_account_persists_fetched_messages(mock_imap_ssl, session):
    account = await _create_account(session)
    mock_imap_ssl.return_value = _connection_returning(_load("simple_text_plain.eml"))

    messages = await sync_account(session, account)

    assert len(messages) == 1
    assert messages[0].subject == "MailChat SMTP proof of concept"
    assert messages[0].account_id == account.id


@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
async def test_sync_account_is_idempotent_across_polls(mock_imap_ssl, session):
    account = await _create_account(session)
    mock_imap_ssl.return_value = _connection_returning(_load("simple_text_plain.eml"))

    await sync_account(session, account)
    await sync_account(session, account)

    stored = await messages_repository.list_messages_for_account(session, account.id)
    assert len(stored) == 1


@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
async def test_sync_all_accounts_isolates_one_account_failure(mock_imap_ssl, session_factory):
    async with session_factory() as setup_session:
        working_account = await _create_account(
            setup_session, address="working@t-online.de", imap_host="secureimap.t-online.de"
        )
        broken_account = await _create_account(
            setup_session, address="broken@t-online.de", imap_host="broken.example.com"
        )

    def imap_ssl_factory(host, port):
        if host == "broken.example.com":
            connection = MagicMock()
            connection.login.side_effect = Exception("boom")
            return connection
        return _connection_returning(_load("simple_text_plain.eml"))

    mock_imap_ssl.side_effect = imap_ssl_factory

    await sync_all_accounts(session_factory)

    async with session_factory() as check_session:
        working_messages = await messages_repository.list_messages_for_account(check_session, working_account.id)
        broken_messages = await messages_repository.list_messages_for_account(check_session, broken_account.id)

    assert len(working_messages) == 1
    assert len(broken_messages) == 0


@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
async def test_sync_all_accounts_runs_slow_accounts_concurrently(mock_imap_ssl, session_factory):
    async with session_factory() as setup_session:
        first_account = await _create_account(
            setup_session, address="first@t-online.de", imap_host="first.example.com"
        )
        second_account = await _create_account(
            setup_session, address="second@t-online.de", imap_host="second.example.com"
        )

    delay_seconds = 0.3
    raw = _load("simple_text_plain.eml")
    mock_imap_ssl.side_effect = lambda host, port: _slow_connection_returning(raw, delay_seconds)

    start = time.monotonic()
    await sync_all_accounts(session_factory)
    elapsed = time.monotonic() - start

    # Blocking imaplib calls are offloaded via asyncio.to_thread; if they ran
    # serially on the event loop this would take ~2x delay_seconds instead.
    assert elapsed < delay_seconds * 1.5

    async with session_factory() as check_session:
        first_messages = await messages_repository.list_messages_for_account(check_session, first_account.id)
        second_messages = await messages_repository.list_messages_for_account(check_session, second_account.id)

    assert len(first_messages) == 1
    assert len(second_messages) == 1
