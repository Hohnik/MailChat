from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from mailchat.messages.models import Message
from mailchat.sync.normalize import normalize
from mailchat.sync.parser import ParsedMessage

PARSED = ParsedMessage(
    message_id="<msg-1@example.com>",
    in_reply_to=None,
    references=None,
    subject="Hello",
    from_header="sender@example.com",
    to_header="recipient@example.com",
    cc_header=None,
    date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    body="Hello there",
)


async def test_normalize_persists_a_new_message(session):
    message = await normalize(session, account_id=1, parsed=PARSED)

    assert message.id is not None
    assert message.account_id == 1
    assert message.message_id == "<msg-1@example.com>"
    assert message.subject == "Hello"
    assert message.body == "Hello there"


async def test_normalize_is_idempotent_for_same_message_id(session):
    first = await normalize(session, account_id=1, parsed=PARSED)
    second = await normalize(session, account_id=1, parsed=PARSED)

    assert first.id == second.id
    result = await session.execute(select(Message).where(Message.account_id == 1))
    assert len(result.scalars().all()) == 1


async def test_normalize_treats_same_message_id_on_different_accounts_as_distinct(session):
    first = await normalize(session, account_id=1, parsed=PARSED)
    second = await normalize(session, account_id=2, parsed=PARSED)

    assert first.id != second.id
