from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.messages.models import Message


async def get_by_message_ids(
    session: AsyncSession, *, account_id: int, message_ids: Sequence[str]
) -> dict[str, Message]:
    """The account's stored messages for the ids given, keyed by id — one query
    however many ids, so recognising a whole fetch costs a single round trip."""
    if not message_ids:
        return {}

    result = await session.execute(
        select(Message).where(Message.account_id == account_id, Message.message_id.in_(message_ids))
    )
    # A matched row always has an id — the `in_` saw to that. The check is for
    # the type checker, and keeps an id the server left empty, which is falsy
    # but every bit as matchable as any other.
    return {
        message.message_id: message
        for message in result.scalars().all()
        if message.message_id is not None
    }


async def store_messages(session: AsyncSession, messages: Sequence[Message]) -> None:
    """Persist messages built elsewhere, and whatever else the session is
    holding — an already-stored message the caller has since taken the server's
    word for again rides out on the same commit. Nothing is named here: the
    fields arrived with them, and storage has no opinion on what a message
    holds."""
    session.add_all(messages)
    await session.commit()
