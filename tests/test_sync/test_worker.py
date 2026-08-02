from __future__ import annotations

import time
from pathlib import Path

from mailchat.accounts import repository as accounts_repository
from mailchat.mail.imap import ImapLoginError
from mailchat.messages import repository as messages_repository
from mailchat.shared.security import encrypt
from mailchat.sync.worker import sync_account, sync_all_accounts
from tests.fakes import FakeImap

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


def _inbox_holding(raw_message: bytes, **kwargs) -> FakeImap:
    return FakeImap(mailboxes={"INBOX": [raw_message]}, **kwargs)


def _server_with_sent_mail(**kwargs) -> FakeImap:
    """One message in the inbox, another in a sent folder — so what a sync
    stored says which folders it read."""
    return FakeImap(
        mailboxes={"INBOX": [_load("simple_text_plain.eml")], "Gesendet": [_load("reply_with_cc.eml")]},
        **kwargs,
    )


async def test_sync_account_persists_fetched_messages(session):
    account = await _create_account(session)
    imap = _inbox_holding(_load("simple_text_plain.eml"))

    messages = await sync_account(session, account, imap=imap)

    assert len(messages) == 1
    assert messages[0].subject == "MailChat SMTP proof of concept"
    assert messages[0].account_id == account.id


async def test_sync_account_is_idempotent_across_polls(session):
    account = await _create_account(session)
    imap = _inbox_holding(_load("simple_text_plain.eml"))

    await sync_account(session, account, imap=imap)
    await sync_account(session, account, imap=imap)

    stored = await messages_repository.list_messages_for_account(session, account.id)
    assert len(stored) == 1


async def test_sync_account_reads_the_sent_folder_the_account_chose(session):
    account = await _create_account(session)
    await accounts_repository.set_sent_folder(session, account, "Gesendet")

    messages = await sync_account(session, account, imap=_server_with_sent_mail())

    assert [message.subject for message in messages] == [
        "MailChat SMTP proof of concept",
        "Re: Terminanfrage",
    ]


async def test_sync_account_reads_the_inbox_alone_when_no_sent_folder_is_chosen(session):
    account = await _create_account(session)

    messages = await sync_account(session, account, imap=_server_with_sent_mail())

    assert [message.subject for message in messages] == ["MailChat SMTP proof of concept"]


async def test_choosing_a_sent_folder_takes_effect_on_the_next_poll(session_factory):
    imap = _server_with_sent_mail()
    async with session_factory() as setup_session:
        account = await _create_account(setup_session)

    await sync_all_accounts(session_factory, imap=imap)

    # The choice a user makes between two polls, with nothing restarted around it.
    async with session_factory() as picking_session:
        picked = await accounts_repository.get_account(picking_session, account.id)
        assert picked is not None
        await accounts_repository.set_sent_folder(picking_session, picked, "Gesendet")

    await sync_all_accounts(session_factory, imap=imap)

    async with session_factory() as check_session:
        stored = await messages_repository.list_messages_for_account(check_session, account.id)
    assert {message.subject for message in stored} == {
        "MailChat SMTP proof of concept",
        "Re: Terminanfrage",
    }


async def test_syncing_several_folders_costs_one_login_per_account_per_poll(session_factory):
    imap = _server_with_sent_mail()
    async with session_factory() as setup_session:
        for address in ("first@t-online.de", "second@t-online.de"):
            account = await _create_account(setup_session, address=address)
            await accounts_repository.set_sent_folder(setup_session, account, "Gesendet")

    await sync_all_accounts(session_factory, imap=imap)

    async with session_factory() as check_session:
        stored = {
            account.address: await messages_repository.list_messages_for_account(check_session, account.id)
            for account in await accounts_repository.list_accounts(check_session)
        }

    # Two folders read per account — the premise the login count is counted
    # against, and without it one login per account proves nothing.
    assert [len(messages) for messages in stored.values()] == [2, 2]
    # Still two logins: folders are read within one session, so picking a sent
    # folder doesn't double what a poll costs.
    assert sorted(credentials.username for credentials in imap.seen) == [
        "first@t-online.de",
        "second@t-online.de",
    ]


async def test_sync_all_accounts_isolates_one_account_failure(session_factory):
    async with session_factory() as setup_session:
        working_account = await _create_account(setup_session, address="working@t-online.de")
        broken_account = await _create_account(setup_session, address="broken@t-online.de")

    imap = _inbox_holding(
        _load("simple_text_plain.eml"),
        errors={"broken@t-online.de": ImapLoginError("bad credentials")},
    )

    await sync_all_accounts(session_factory, imap=imap)

    async with session_factory() as check_session:
        working_messages = await messages_repository.list_messages_for_account(check_session, working_account.id)
        broken_messages = await messages_repository.list_messages_for_account(check_session, broken_account.id)

    assert len(working_messages) == 1
    assert len(broken_messages) == 0


async def test_sync_all_accounts_runs_slow_accounts_concurrently(session_factory):
    async with session_factory() as setup_session:
        first_account = await _create_account(setup_session, address="first@t-online.de")
        second_account = await _create_account(setup_session, address="second@t-online.de")

    delay_seconds = 0.3
    imap = _inbox_holding(_load("simple_text_plain.eml"), delay_seconds=delay_seconds)

    start = time.monotonic()
    await sync_all_accounts(session_factory, imap=imap)
    elapsed = time.monotonic() - start

    # Accounts are synced together; one slow server must not hold up the rest.
    assert elapsed < delay_seconds * 1.5

    async with session_factory() as check_session:
        first_messages = await messages_repository.list_messages_for_account(check_session, first_account.id)
        second_messages = await messages_repository.list_messages_for_account(check_session, second_account.id)

    assert len(first_messages) == 1
    assert len(second_messages) == 1
