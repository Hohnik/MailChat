from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from mailchat.accounts import repository as accounts_repository
from mailchat.conversations import service as conversations_service
from mailchat.conversations.models import Contact, Conversation
from mailchat.mail.imap import FetchedMessage
from mailchat.messages.models import INBOUND, OUTBOUND, Message
from mailchat.shared.security import encrypt
from mailchat.sync.grouping import ME
from mailchat.sync.ingest import ingest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "emails"

LOUIS_THREAD = [
    "louis_ticket_opened.eml",
    "louis_ticket_answer.eml",
    "louis_ticket_forwarded.eml",
]


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _fetched(
    name: str, *, folder: str = "INBOX", uid: int = 1, uidvalidity: int = 42, is_read: bool = False
) -> FetchedMessage:
    return FetchedMessage(
        folder=folder, uid=uid, uidvalidity=uidvalidity, is_read=is_read, raw=_load(name)
    )


async def _account(session, *, address: str = "kunde@example.com", sent_folder: str | None = None):
    account = await accounts_repository.create_account(
        session,
        provider="generic",
        address=address,
        imap_host="imap.example.com",
        imap_port=993,
        smtp_host="smtp.example.com",
        smtp_port=465,
        encrypted_password=encrypt("app-specific-secret"),
    )
    if sent_folder is not None:
        await accounts_repository.set_sent_folder(session, account, sent_folder)
    return account


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def _contacts(session) -> list[Contact]:
    result = await session.execute(select(Contact).order_by(Contact.address))
    return list(result.scalars().all())
async def _stored_for(session, account_id: int) -> list[Message]:
    """What this account has in the table, oldest first."""
    result = await session.execute(
        select(Message).where(Message.account_id == account_id).order_by(Message.date)
    )
    return list(result.scalars().all())


async def test_ingest_stores_every_field_of_a_message(session):
    account = await _account(session)

    stored = await ingest(
        session,
        account=account,
        fetched=[_fetched("reply_with_cc.eml", folder="INBOX", uid=17, uidvalidity=9)],
    )

    message = stored[0]
    assert message.id is not None
    assert message.account_id == account.id
    assert message.conversation_id is not None
    assert message.message_id == "<reply-6789@beispiel-service.de>"
    assert message.in_reply_to == "<original-1111@example.com>"
    assert message.references == "<original-1111@example.com>"
    assert message.subject == "Re: Terminanfrage"
    assert message.from_header == "Beispiel Support <support@beispiel-service.de>"
    assert message.to_header == "kunde@example.com"
    assert message.cc_header == "Kollege <kollege@beispiel-service.de>"
    assert message.date == datetime(2026, 7, 22, 14, 30, tzinfo=timezone(timedelta(hours=2)))
    assert "Vielen Dank" in message.body
    assert message.direction == INBOUND
    assert message.is_read is False
    assert message.imap_uid == 17
    assert message.imap_folder == "INBOX"
    assert message.imap_uidvalidity == 9


async def test_ingest_returns_a_stored_message_per_raw_message_in_order(session):
    account = await _account(session)
    fetched = [_fetched("simple_text_plain.eml", uid=1), _fetched("reply_with_cc.eml", uid=2)]

    stored = await ingest(session, account=account, fetched=fetched)

    assert [message.subject for message in stored] == [
        "MailChat SMTP proof of concept",
        "Re: Terminanfrage",
    ]
    assert len(await _stored_for(session, account.id)) == 2


async def test_ingest_is_idempotent_across_polls(session):
    account = await _account(session)
    fetched = [_fetched("simple_text_plain.eml")]

    first = await ingest(session, account=account, fetched=fetched)
    second = await ingest(session, account=account, fetched=fetched)

    assert second[0].id == first[0].id
    assert len(await _stored_for(session, account.id)) == 1


async def test_ingest_is_idempotent_within_one_fetch(session):
    account = await _account(session)
    fetched = _fetched("simple_text_plain.eml")

    stored = await ingest(session, account=account, fetched=[fetched, fetched])

    assert stored[0].id == stored[1].id
    assert len(await _stored_for(session, account.id)) == 1


async def test_ingest_keeps_one_message_id_on_two_accounts_apart(session):
    first_account = await _account(session, address="erste@example.com")
    second_account = await _account(session, address="zweite@example.com")
    fetched = [_fetched("simple_text_plain.eml")]

    first = await ingest(session, account=first_account, fetched=fetched)
    second = await ingest(session, account=second_account, fetched=fetched)

    assert first[0].id != second[0].id
    assert len(await _stored_for(session, first_account.id)) == 1
    assert len(await _stored_for(session, second_account.id)) == 1


async def test_ingest_recognises_a_message_id_the_server_left_empty(session):
    # An empty header is still an id to match on: recognising it keeps a poll
    # from storing the same malformed message again on every later poll.
    account = await _account(session)
    fetched = [_fetched("empty_message_id.eml")]

    first = await ingest(session, account=account, fetched=fetched)
    second = await ingest(session, account=account, fetched=fetched)

    assert second[0].id == first[0].id
    assert len(await _stored_for(session, account.id)) == 1


async def test_ingest_stores_every_copy_of_mail_without_a_message_id(session):
    account = await _account(session)
    fetched = _fetched("without_message_id.eml")

    stored = await ingest(session, account=account, fetched=[fetched, fetched])

    assert stored[0].id != stored[1].id
    assert len(await _stored_for(session, account.id)) == 2


async def test_ingest_stores_the_rest_of_a_fetch_around_a_message_it_cannot_parse(session):
    account = await _account(session)
    fetched = [
        _fetched("simple_text_plain.eml"),
        _fetched("unknown_charset.eml"),
        _fetched("reply_with_cc.eml"),
    ]

    stored = await ingest(session, account=account, fetched=fetched)

    assert [message.subject for message in stored] == [
        "MailChat SMTP proof of concept",
        "Re: Terminanfrage",
    ]
    assert len(await _stored_for(session, account.id)) == 2


async def test_ingest_stores_nothing_for_an_empty_fetch(session):
    account = await _account(session)

    stored = await ingest(session, account=account, fetched=[])

    assert stored == []
    assert await _stored_for(session, account.id) == []


async def test_a_thread_a_ticketing_system_mangled_stays_one_conversation(session):
    """The real DL-4916597 shape: the same subject spelled four ways."""
    account = await _account(session, sent_folder="Gesendet")
    fetched = [_fetched(name, uid=index) for index, name in enumerate(LOUIS_THREAD)]
    fetched.append(_fetched("louis_ticket_replied_to.eml", folder="Gesendet", uid=1))

    stored = await ingest(session, account=account, fetched=fetched)

    assert await _count(session, Conversation) == 1
    assert len({message.conversation_id for message in stored}) == 1

    conversation = await session.get(Conversation, stored[0].conversation_id)
    assert conversation is not None
    assert conversation.normalized_subject == "[DL-4916597] Ihre Anfrage an Louis"
    assert conversation.contact.address == "service@louis.de"


async def test_the_subjects_a_thread_arrived_under_are_kept_on_its_messages(session):
    # Grouping reads a stripped subject; the user reads what the sender wrote.
    account = await _account(session)

    stored = await ingest(
        session, account=account, fetched=[_fetched(name) for name in LOUIS_THREAD]
    )

    assert [message.subject for message in stored] == [
        "[DL-4916597] Ihre Anfrage an Louis",
        "AW: [DL-4916597] Ihre Anfrage an Louis",
        "WG: AW: [DL-4916597] Ihre Anfrage an Louis",
    ]


async def test_a_contact_is_called_what_the_latest_message_calls_them(session):
    account = await _account(session)

    await ingest(session, account=account, fetched=[_fetched(name) for name in LOUIS_THREAD[:2]])

    assert [contact.display_name for contact in await _contacts(session)] == ["Louis Kundenservice"]


async def test_the_latest_message_names_a_contact_wherever_it_sits_in_the_fetch(session):
    # A fetch reads the inbox before the sent folder, so the last message to
    # arrive is not the last one sent. Whoever wrote most recently is who the
    # contact is called after, however the fetch happened to be ordered.
    account = await _account(session)

    await ingest(
        session,
        account=account,
        fetched=[
            _fetched("louis_ticket_answer.eml"),
            _fetched("louis_ticket_opened.eml"),
        ],
    )

    assert [contact.display_name for contact in await _contacts(session)] == ["Louis Kundenservice"]


async def test_a_thread_is_stored_in_the_order_it_was_said_across_time_zones(session):
    account = await _account(session)
    # Sent between the answer and the forward by the clock that matters, and
    # before both by the one written on it.
    thread = [
        "louis_ticket_opened.eml",
        "louis_ticket_answer.eml",
        "louis_ticket_from_abroad.eml",
        "louis_ticket_forwarded.eml",
    ]

    stored = await ingest(session, account=account, fetched=[_fetched(name) for name in thread])

    in_order = await conversations_service.messages_in(session, stored[0].conversation_id)
    assert [message.message_id for message in in_order] == [
        "<dl-4916597-1@louis.de>",
        "<dl-4916597-2@louis.de>",
        "<dl-4916597-5@louis.de>",
        "<dl-4916597-3@louis.de>",
    ]


async def test_someone_in_copy_is_kept_on_the_message_and_out_of_the_grouping(session):
    account = await _account(session)

    stored = await ingest(
        session,
        account=account,
        fetched=[_fetched("horbach_with_cc.eml"), _fetched("horbach_without_cc.eml")],
    )

    # Dropping the assistant from the second mail must not start a second
    # conversation, and must not lose that she was on the first.
    assert await _count(session, Conversation) == 1
    assert [contact.address for contact in await _contacts(session)] == [
        "j.horbach@horbach-beratung.de"
    ]
    assert stored[0].cc_header == "Assistenz <assistenz@horbach-beratung.de>"
    assert stored[1].cc_header is None


async def test_a_new_subject_from_the_same_contact_starts_its_own_conversation(session):
    account = await _account(session)

    stored = await ingest(
        session,
        account=account,
        fetched=[_fetched("louis_ticket_opened.eml"), _fetched("horbach_with_cc.eml")],
    )

    assert stored[0].conversation_id != stored[1].conversation_id
    assert await _count(session, Contact) == 2


async def test_the_folder_a_message_came_from_says_which_way_it_was_going(session):
    account = await _account(session, sent_folder="Gesendet")

    stored = await ingest(
        session,
        account=account,
        fetched=[
            _fetched("louis_ticket_opened.eml"),
            _fetched("louis_ticket_replied_to.eml", folder="Gesendet"),
        ],
    )

    assert [message.direction for message in stored] == [INBOUND, OUTBOUND]


async def test_mail_between_the_users_own_accounts_still_lands_somewhere(session):
    await _account(session, address="kunde@example.com")
    second_account = await _account(session, address="niklas-hohn@t-online.de")

    stored = await ingest(session, account=second_account, fetched=[_fetched("simple_text_plain.eml")])

    contact = await session.get(Contact, (await session.get(Conversation, stored[0].conversation_id)).contact_id)
    assert contact is not None
    assert contact.address == ME
    assert contact.display_name == "Me"


async def test_ingest_takes_the_servers_word_for_what_has_been_read(session):
    account = await _account(session)
    first_poll = _fetched("louis_ticket_opened.eml", uid=4, is_read=False)
    second_poll = _fetched("louis_ticket_opened.eml", uid=4, is_read=True)

    stored = await ingest(session, account=account, fetched=[first_poll])
    assert stored[0].is_read is False

    # Read in another mail client between the two polls. The server is the one
    # source of read state, so the local value gives way to it — and gives way
    # back again when it is unread there.
    refreshed = await ingest(session, account=account, fetched=[second_poll])
    assert refreshed[0].id == stored[0].id
    assert refreshed[0].is_read is True

    unread_again = await ingest(session, account=account, fetched=[first_poll])
    assert unread_again[0].is_read is False


async def test_a_poll_heals_the_address_of_a_message_the_server_renumbered(session):
    account = await _account(session, sent_folder="Gesendet")
    await ingest(
        session, account=account, fetched=[_fetched("louis_ticket_opened.eml", uid=4, uidvalidity=42)]
    )

    # A folder whose UIDVALIDITY moved renumbered everything in it: the stored
    # address now points at whatever else took that number.
    stored = await ingest(
        session,
        account=account,
        fetched=[_fetched("louis_ticket_opened.eml", uid=8, uidvalidity=77)],
    )

    assert stored[0].imap_uid == 8
    assert stored[0].imap_uidvalidity == 77
    assert stored[0].imap_folder == "INBOX"


async def test_a_known_message_keeps_the_conversation_it_was_filed_under(session):
    account = await _account(session)
    fetched = [_fetched("louis_ticket_opened.eml")]

    first = await ingest(session, account=account, fetched=fetched)
    second = await ingest(session, account=account, fetched=fetched)

    assert second[0].conversation_id == first[0].conversation_id
    assert await _count(session, Conversation) == 1
