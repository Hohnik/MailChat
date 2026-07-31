from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.messages import repository as messages_repository
from mailchat.messages.models import Message
from mailchat.sync.parser import ParsedMessage


async def normalize(session: AsyncSession, *, account_id: int, parsed: ParsedMessage) -> Message:
    if parsed.message_id is not None:
        existing = await messages_repository.get_by_message_id(
            session, account_id=account_id, message_id=parsed.message_id
        )
        if existing is not None:
            return existing

    return await messages_repository.create_message(
        session,
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
