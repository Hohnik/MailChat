from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from mailchat.messages import repository as messages_repository
from mailchat.sync.ingest import ingest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "emails"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


async def test_ingest_stores_every_field_of_a_message(session):
    stored = await ingest(session, account_id=1, raw_messages=[_load("reply_with_cc.eml")])

    message = stored[0]
    assert message.id is not None
    assert message.account_id == 1
    assert message.message_id == "<reply-6789@beispiel-service.de>"
    assert message.in_reply_to == "<original-1111@example.com>"
    assert message.references == "<original-1111@example.com>"
    assert message.subject == "Re: Terminanfrage"
    assert message.from_header == "Beispiel Support <support@beispiel-service.de>"
    assert message.to_header == "kunde@example.com"
    assert message.cc_header == "Kollege <kollege@beispiel-service.de>"
    assert message.date == datetime(2026, 7, 22, 14, 30, tzinfo=timezone(timedelta(hours=2)))
    assert "Vielen Dank" in message.body


async def test_ingest_returns_a_stored_message_per_raw_message_in_order(session):
    raw_messages = [_load("simple_text_plain.eml"), _load("reply_with_cc.eml")]

    stored = await ingest(session, account_id=1, raw_messages=raw_messages)

    assert [message.subject for message in stored] == [
        "MailChat SMTP proof of concept",
        "Re: Terminanfrage",
    ]
    assert len(await messages_repository.list_messages_for_account(session, 1)) == 2


async def test_ingest_is_idempotent_across_polls(session):
    raw_messages = [_load("simple_text_plain.eml")]

    first = await ingest(session, account_id=1, raw_messages=raw_messages)
    second = await ingest(session, account_id=1, raw_messages=raw_messages)

    assert second[0].id == first[0].id
    assert len(await messages_repository.list_messages_for_account(session, 1)) == 1


async def test_ingest_is_idempotent_within_one_fetch(session):
    raw_message = _load("simple_text_plain.eml")

    stored = await ingest(session, account_id=1, raw_messages=[raw_message, raw_message])

    assert stored[0].id == stored[1].id
    assert len(await messages_repository.list_messages_for_account(session, 1)) == 1


async def test_ingest_keeps_one_message_id_on_two_accounts_apart(session):
    raw_messages = [_load("simple_text_plain.eml")]

    first = await ingest(session, account_id=1, raw_messages=raw_messages)
    second = await ingest(session, account_id=2, raw_messages=raw_messages)

    assert first[0].id != second[0].id
    assert len(await messages_repository.list_messages_for_account(session, 1)) == 1
    assert len(await messages_repository.list_messages_for_account(session, 2)) == 1


async def test_ingest_recognises_a_message_id_the_server_left_empty(session):
    # An empty header is still an id to match on: recognising it keeps a poll
    # from storing the same malformed message again on every later poll.
    raw_messages = [_load("empty_message_id.eml")]

    first = await ingest(session, account_id=1, raw_messages=raw_messages)
    second = await ingest(session, account_id=1, raw_messages=raw_messages)

    assert second[0].id == first[0].id
    assert len(await messages_repository.list_messages_for_account(session, 1)) == 1


async def test_ingest_stores_every_copy_of_mail_without_a_message_id(session):
    raw_message = _load("without_message_id.eml")

    stored = await ingest(session, account_id=1, raw_messages=[raw_message, raw_message])

    assert stored[0].id != stored[1].id
    assert len(await messages_repository.list_messages_for_account(session, 1)) == 2


async def test_ingest_stores_the_rest_of_a_fetch_around_a_message_it_cannot_parse(session):
    raw_messages = [
        _load("simple_text_plain.eml"),
        _load("unknown_charset.eml"),
        _load("reply_with_cc.eml"),
    ]

    stored = await ingest(session, account_id=1, raw_messages=raw_messages)

    assert [message.subject for message in stored] == [
        "MailChat SMTP proof of concept",
        "Re: Terminanfrage",
    ]
    assert len(await messages_repository.list_messages_for_account(session, 1)) == 2


async def test_ingest_stores_nothing_for_an_empty_fetch(session):
    stored = await ingest(session, account_id=1, raw_messages=[])

    assert stored == []
    assert await messages_repository.list_messages_for_account(session, 1) == []
