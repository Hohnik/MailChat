from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.accounts import service as accounts_service
from mailchat.accounts.models import Account
from mailchat.conversations import service as conversations_service
from mailchat.mail.imap import FetchedMessage
from mailchat.messages import repository as messages_repository
from mailchat.messages.models import Direction, Message
from mailchat.sync.grouping import Grouping, direction_of, group
from mailchat.sync.parser import ParsedMessage, parse

logger = logging.getLogger(__name__)

_UNDATED = datetime.min.replace(tzinfo=timezone.utc)
"""Where mail carrying no date sorts: before anything that says when it was sent."""


@dataclass(frozen=True)
class Arrival:
    """One message as this fetch found it, read as far as it can be without the
    database: where on the server it was, what it says, which way it was going,
    and which conversation it belongs in. Everything after this is rows."""

    fetched: FetchedMessage
    parsed: ParsedMessage
    direction: Direction
    grouping: Grouping


async def ingest(
    session: AsyncSession, *, account: Account, fetched: Sequence[FetchedMessage]
) -> list[Message]:
    """Turn one account's fetched mail into its stored messages: parse it, group
    it into conversations, and store what isn't stored already. Callers hand over
    what a fetch returned and get a stored message back for each one it could
    parse, in the order they were fetched — no second pass, and nothing to match
    back up afterwards.

    Mail is recognised by its `Message-ID`, per account, so the same message
    fetched by two polls — or twice by one — is stored once, while the same id
    arriving at two accounts is two messages. A message already stored is not
    left alone, though: read state and the address it lives at belong to the
    server, so every poll that reaches a message takes the server's word for
    both again.
    """
    arrivals = await _arrivals(session, account, fetched)
    stored_by_message_id = await messages_repository.get_by_message_ids(
        session,
        account_id=account.id,
        message_ids=[
            arrival.parsed.message_id for arrival in arrivals if arrival.parsed.message_id is not None
        ],
    )
    display_names = _display_names(arrivals)

    messages: list[Message] = []
    new_messages: list[Message] = []
    for arrival in arrivals:
        message_id = arrival.parsed.message_id
        message = stored_by_message_id.get(message_id) if message_id is not None else None
        if message is None:
            conversation = await conversations_service.conversation_for(
                session,
                address=arrival.grouping.address,
                display_name=display_names.get(arrival.grouping.address),
                normalized_subject=arrival.grouping.normalized_subject,
            )
            message = _message_for(arrival, account_id=account.id, conversation_id=conversation.id)
            new_messages.append(message)
            if message_id is not None:
                stored_by_message_id[message_id] = message
        else:
            _refresh(message, arrival.fetched)
        messages.append(message)

    await messages_repository.store_messages(session, new_messages)
    return messages


async def _arrivals(
    session: AsyncSession, account: Account, fetched: Sequence[FetchedMessage]
) -> list[Arrival]:
    """Every message of the fetch that can be parsed at all, read as far as it
    can be without touching the database.

    Which way a message was going is settled first, because it decides who its
    conversation is with: the sender of mail that arrived, the recipient of mail
    the user sent. Every connected account's address is asked for, not just this
    one's, so a conversation is never filed under a mailbox the user owns.

    Mail written in an encoding Python doesn't know — or malformed some other way
    parsing can't survive — is logged and left out, because one message must not
    cost the account the rest of the fetch: a poll re-reads the same window, so a
    fetch abandoned over one bad message would be abandoned again on every poll
    after.
    """
    connected_addresses = [
        connected.address for connected in await accounts_service.list_accounts(session)
    ]

    arrivals = []
    for fetched_message in fetched:
        try:
            parsed = parse(fetched_message.raw)
        except Exception:
            logger.exception("Could not parse a fetched message; leaving it out of this sync")
            continue

        direction = direction_of(account, fetched_message.folder)
        arrivals.append(
            Arrival(
                fetched=fetched_message,
                parsed=parsed,
                direction=direction,
                grouping=group(
                    parsed, direction=direction, account_addresses=connected_addresses
                ),
            )
        )
    return arrivals


def _display_names(arrivals: Sequence[Arrival]) -> dict[str, str]:
    """What to call each contact this fetch brought mail for: the name on the
    most recently sent message that named them.

    Settled across the whole fetch rather than message by message, because a
    fetch reads the inbox before the sent folder — so taking each name as it
    came would let last year's reply rename someone over a mail from this
    morning. Contacts nothing named keep the name they already had.
    """
    latest: dict[str, tuple[datetime, str]] = {}
    for arrival in arrivals:
        name = arrival.grouping.display_name
        if name is None:
            continue
        sent_at = arrival.parsed.date or _UNDATED
        known = latest.get(arrival.grouping.address)
        if known is None or sent_at >= known[0]:
            latest[arrival.grouping.address] = (sent_at, name)

    return {address: name for address, (_, name) in latest.items()}


def _message_for(arrival: Arrival, *, account_id: int, conversation_id: int) -> Message:
    """The one place a parsed mail becomes a row: every field is named here and
    nowhere else between the parsed form and the table. A field that arrives
    with the fetch rather than in the mail itself is this function and its
    column, with no keyword list in between to keep in step.
    """
    parsed, fetched = arrival.parsed, arrival.fetched
    return Message(
        account_id=account_id,
        conversation_id=conversation_id,
        message_id=parsed.message_id,
        in_reply_to=parsed.in_reply_to,
        references=parsed.references,
        subject=parsed.subject,
        from_header=parsed.from_header,
        to_header=parsed.to_header,
        cc_header=parsed.cc_header,
        date=parsed.date,
        body=parsed.body,
        direction=arrival.direction,
        is_read=fetched.is_read,
        imap_uid=fetched.uid,
        imap_folder=fetched.folder,
        imap_uidvalidity=fetched.uidvalidity,
    )


def _refresh(message: Message, fetched: FetchedMessage) -> None:
    """Take the server's word again for the two things it owns about a message
    MailChat already has.

    Read state is the server's: whatever is stored gives way to the flag that
    came back, in both directions, so a message read in another client reads as
    read here and there is no local state to reconcile. The address is the
    server's too, and it is one thing rather than three — a UID renumbered by a
    `UIDVALIDITY` change means nothing without the folder and the validity it
    was handed out under, so all three heal together on the next poll that
    reaches this message.

    Which conversation the message belongs to isn't touched. Grouping is
    MailChat's own reading of mail that hasn't changed, and a message the user
    is looking at should not move house because a second folder holds a copy.
    """
    message.is_read = fetched.is_read
    message.imap_uid = fetched.uid
    message.imap_folder = fetched.folder
    message.imap_uidvalidity = fetched.uidvalidity
