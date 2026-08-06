from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import func, select

from mailchat.accounts import repository as accounts_repository
from mailchat.conversations import service as conversations_service
from mailchat.conversations.models import Contact, Conversation
from mailchat.mail.imap import ImapLoginError
from mailchat.messages.models import INBOUND, OUTBOUND, Message
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
async def _stored_for(session, account_id: int) -> list[Message]:
    """What this account has in the table, oldest first."""
    result = await session.execute(
        select(Message).where(Message.account_id == account_id).order_by(Message.date)
    )
    return list(result.scalars().all())


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

    stored = await _stored_for(session, account.id)
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
        stored = await _stored_for(check_session, account.id)
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
            account.address: await _stored_for(check_session, account.id)
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
        working_messages = await _stored_for(check_session, working_account.id)
        broken_messages = await _stored_for(check_session, broken_account.id)

    assert len(working_messages) == 1
    assert len(broken_messages) == 0


async def test_a_sync_files_a_whole_mangled_thread_into_one_conversation(session):
    # The whole path with only the server faked: the DL-4916597 thread as it
    # really arrives — three inbound spellings of one subject and the reply the
    # user sent, sitting in two folders.
    account = await _create_account(session)
    await accounts_repository.set_sent_folder(session, account, "Gesendet")
    imap = FakeImap(
        mailboxes={
            "INBOX": [
                _load("louis_ticket_opened.eml"),
                _load("louis_ticket_answer.eml"),
                _load("louis_ticket_forwarded.eml"),
            ],
            "Gesendet": [_load("louis_ticket_replied_to.eml")],
        },
        # Only the second message of the inbox; the sent folder has no UID 2.
        read_uids={2},
    )

    messages = await sync_account(session, account, imap=imap)

    conversation = await session.scalar(select(Conversation))
    assert conversation is not None
    assert conversation.normalized_subject == "[DL-4916597] Ihre Anfrage an Louis"
    assert conversation.contact.address == "service@louis.de"
    assert [message.conversation_id for message in messages] == [conversation.id] * 4
    assert [message.direction for message in messages] == [INBOUND, INBOUND, INBOUND, OUTBOUND]
    # The one message this server holds flagged read, and the folder and UID a
    # flag written back would have to be addressed to.
    assert [message.is_read for message in messages] == [False, True, False, False]
    assert [(message.imap_folder, message.imap_uid) for message in messages] == [
        ("INBOX", 1),
        ("INBOX", 2),
        ("INBOX", 3),
        ("Gesendet", 1),
    ]


async def test_two_accounts_meeting_one_contact_at_once_create_one_of_each(session_factory):
    # The same person writes to both of the user's mailboxes, and both accounts
    # sync at the same time — the moment two tasks would each find no contact
    # and each create one. One conversation is the point of not keying it by
    # account; two rows for it would be two half-conversations instead.
    async with session_factory() as setup_session:
        for address in ("first@t-online.de", "second@t-online.de"):
            await _create_account(setup_session, address=address)

    imap = _inbox_holding(_load("louis_ticket_opened.eml"), delay_seconds=0.05)

    await sync_all_accounts(session_factory, imap=imap)

    async with session_factory() as check_session:
        assert await check_session.scalar(select(func.count()).select_from(Contact)) == 1
        assert await check_session.scalar(select(func.count()).select_from(Conversation)) == 1
        # Both accounts stored the message: one conversation holding both is
        # what proves they met in it rather than one of them failing quietly.
        conversation = await check_session.scalar(select(Conversation))
        assert conversation is not None
        messages = await conversations_service.messages_in(check_session, conversation.id)
        assert len(messages) == 2


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
        first_messages = await _stored_for(check_session, first_account.id)
        second_messages = await _stored_for(check_session, second_account.id)

    assert len(first_messages) == 1
    assert len(second_messages) == 1
