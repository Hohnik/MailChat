from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.messages import repository as messages_repository
from mailchat.messages.models import Message
from mailchat.sync.parser import ParsedMessage, parse

logger = logging.getLogger(__name__)


async def ingest(
    session: AsyncSession, *, account_id: int, raw_messages: Sequence[bytes]
) -> list[Message]:
    """Turn one account's raw fetched mail into its stored messages: parse it,
    skip whatever is stored already, persist the rest. Callers hand over what a
    fetch returned and get a stored message back for each one it could parse, in
    the order they were fetched — no second pass, and nothing to match back up
    afterwards.

    Mail is recognised by its `Message-ID`, per account, so the same message
    fetched by two polls — or twice by one — is stored once, while the same id
    arriving at two accounts is two messages.
    """
    parsed_messages = _parse_all(raw_messages)
    stored_by_message_id = await messages_repository.get_by_message_ids(
        session,
        account_id=account_id,
        message_ids=[
            parsed.message_id for parsed in parsed_messages if parsed.message_id is not None
        ],
    )

    messages: list[Message] = []
    new_messages: list[Message] = []
    for parsed in parsed_messages:
        message = (
            stored_by_message_id.get(parsed.message_id) if parsed.message_id is not None else None
        )
        if message is None:
            message = _message_for(account_id, parsed)
            new_messages.append(message)
            if parsed.message_id is not None:
                stored_by_message_id[parsed.message_id] = message
        messages.append(message)

    await messages_repository.store_messages(session, new_messages)
    return messages


def _parse_all(raw_messages: Sequence[bytes]) -> list[ParsedMessage]:
    """Every message of the fetch that can be parsed at all. Mail written in an
    encoding Python doesn't know — or malformed some other way parsing can't
    survive — is logged and left out, because one message must not cost the
    account the rest of the fetch: a poll re-reads the same window, so a fetch
    abandoned over one bad message would be abandoned again on every poll after.
    """
    parsed_messages = []
    for raw_message in raw_messages:
        try:
            parsed_messages.append(parse(raw_message))
        except Exception:
            logger.exception("Could not parse a fetched message; leaving it out of this sync")
    return parsed_messages


def _message_for(account_id: int, parsed: ParsedMessage) -> Message:
    """The one place a parsed mail becomes a row: every field is named here and
    nowhere else between the parsed form and the table. A field that arrives
    with the fetch rather than in the mail itself is this function and its
    column, with no keyword list in between to keep in step.
    """
    return Message(
        account_id=account_id,
        message_id=parsed.message_id,
        in_reply_to=parsed.in_reply_to,
        references=parsed.references,
        subject=parsed.subject,
        from_header=parsed.from_header,
        to_header=parsed.to_header,
        cc_header=parsed.cc_header,
        date=parsed.date,
        body=parsed.body,
    )
