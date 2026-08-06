from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.conversations import repository
from mailchat.conversations.models import Conversation
from mailchat.conversations.repository import ConversationSummary
from mailchat.messages.models import Message
from mailchat.shared.exceptions import ConversationNotFoundError

_grouping_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()


def _grouping_lock() -> asyncio.Lock:
    """The lock a find-or-create is held under, for the loop asking.

    Accounts sync side by side (`sync/worker.py`), and a conversation belongs to
    no account — so two of them meeting the same person for the first time in
    one poll are two tasks about to create the same two rows. One lock across
    both lookups and both creates, released only once the pair is committed, is
    what makes the second task find what the first one wrote instead of writing
    it again. MailChat is one process, so this is the whole mechanism; the same
    keys are spelled out on the tables, but only so that a lapse here is a
    refused write to fix rather than a second half-conversation nobody notices.

    One lock per event loop, because an `asyncio.Lock` belongs to the loop that
    first waited on it. The app runs one loop for its whole life, so that is one
    lock; a process that runs several — a test suite — gets one each, which is
    the same guarantee, since tasks on different loops share no database either.
    """
    return _grouping_locks.setdefault(asyncio.get_running_loop(), asyncio.Lock())


async def conversation_for(
    session: AsyncSession, *, address: str, display_name: str | None, normalized_subject: str
) -> Conversation:
    """The conversation with this contact about this subject, creating either if new.

    The contact's display name is refreshed from every message that carries one,
    so a person who changes how they sign their mail is called what they call
    themselves now.
    """
    async with _grouping_lock():
        contact = await repository.get_contact(session, address)
        if contact is None:
            contact = await repository.add_contact(
                session, address=address, display_name=display_name
            )
        elif display_name:
            contact.display_name = display_name

        conversation = await repository.get_conversation_about(
            session, contact_id=contact.id, normalized_subject=normalized_subject
        )
        if conversation is None:
            conversation = await repository.add_conversation(
                session, contact=contact, normalized_subject=normalized_subject
            )

        await session.commit()
        return conversation


async def list_conversations(session: AsyncSession) -> list[ConversationSummary]:
    """Every conversation for the conversation list, most recent first."""
    return await repository.list_conversations(session)


async def get_conversation(session: AsyncSession, conversation_id: int) -> Conversation:
    """The one answer to "is there a conversation with this id?".

    Raises rather than returning `None`, the way the accounts module does, so a
    link to a conversation that has gone means one thing everywhere.
    """
    conversation = await repository.get_conversation(session, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(f"No conversation with id {conversation_id}")
    return conversation


async def messages_in(session: AsyncSession, conversation_id: int) -> list[Message]:
    """What was said in this conversation, oldest first."""
    return await repository.list_messages(session, conversation_id)
