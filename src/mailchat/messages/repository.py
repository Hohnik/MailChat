from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.messages.models import Message


async def get_by_message_id(session: AsyncSession, *, account_id: int, message_id: str) -> Message | None:
    result = await session.execute(
        select(Message).where(Message.account_id == account_id, Message.message_id == message_id)
    )
    return result.scalar_one_or_none()


async def create_message(
    session: AsyncSession,
    *,
    account_id: int,
    message_id: str | None,
    in_reply_to: str | None,
    references: str | None,
    subject: str | None,
    from_header: str | None,
    to_header: str | None,
    cc_header: str | None,
    date: datetime | None,
    body: str,
) -> Message:
    message = Message(
        account_id=account_id,
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        subject=subject,
        from_header=from_header,
        to_header=to_header,
        cc_header=cc_header,
        date=date,
        body=body,
    )
    session.add(message)
    await session.commit()
    return message


async def list_messages_for_account(session: AsyncSession, account_id: int) -> list[Message]:
    result = await session.execute(
        select(Message).where(Message.account_id == account_id).order_by(Message.date)
    )
    return list(result.scalars().all())
