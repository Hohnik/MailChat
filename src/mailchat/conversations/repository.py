from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.conversations.models import Contact, Conversation
from mailchat.messages.models import INBOUND, Message


@dataclass(frozen=True)
class ConversationSummary:
    """One line of the conversation list: who, about what, and what's waiting.

    Both numbers are counted off the messages every time they're asked for
    rather than kept on the conversation. They are the same answer either way
    until the day a write is missed, and then only one of them is still true.
    """

    conversation: Conversation
    last_message_at: datetime | None
    unread_count: int


async def get_contact(session: AsyncSession, address: str) -> Contact | None:
    result = await session.execute(select(Contact).where(Contact.address == address))
    return result.scalar_one_or_none()


async def add_contact(session: AsyncSession, *, address: str, display_name: str | None) -> Contact:
    """Store a contact and give it an id, without committing.

    The id is what a conversation is keyed by, so the row has to reach the
    database before one can be built on it — but whether the pair of them is
    kept is the caller's call, one commit for both.
    """
    contact = Contact(address=address, display_name=display_name)
    session.add(contact)
    await session.flush()
    return contact


async def get_conversation_about(
    session: AsyncSession, *, contact_id: int, normalized_subject: str
) -> Conversation | None:
    result = await session.execute(
        select(Conversation).where(
            Conversation.contact_id == contact_id,
            Conversation.normalized_subject == normalized_subject,
        )
    )
    return result.scalar_one_or_none()


async def add_conversation(
    session: AsyncSession, *, contact: Contact, normalized_subject: str
) -> Conversation:
    """Store a conversation, without committing — see `add_contact`."""
    conversation = Conversation(contact=contact, normalized_subject=normalized_subject)
    session.add(conversation)
    await session.flush()
    return conversation


async def get_conversation(session: AsyncSession, conversation_id: int) -> Conversation | None:
    result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
    return result.scalar_one_or_none()


async def list_conversations(session: AsyncSession) -> list[ConversationSummary]:
    """Every conversation, the most recently spoken in first.

    One query, however many conversations: the counts come back with the rows
    rather than a lookup per line.
    """
    last_message_at = func.max(Message.date)
    unread_count = func.count(Message.id).filter(
        Message.is_read.is_(False), Message.direction == INBOUND
    )

    result = await session.execute(
        select(Conversation, last_message_at, unread_count)
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .group_by(Conversation.id)
        # A conversation nothing has been dated yet sorts last, not first.
        .order_by(last_message_at.desc(), Conversation.id.desc())
    )

    return [
        ConversationSummary(
            conversation=conversation, last_message_at=last_message, unread_count=unread
        )
        for conversation, last_message, unread in result.all()
    ]


async def list_messages(session: AsyncSession, conversation_id: int) -> list[Message]:
    """A conversation's messages, oldest first — the order it was said in."""
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        # Mail carrying no date keeps the order it was fetched in; there is
        # nothing better to say about when it was sent.
        .order_by(Message.date, Message.id)
    )
    return list(result.scalars().all())
