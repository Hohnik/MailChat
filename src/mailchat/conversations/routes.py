from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.conversations import service
from mailchat.conversations.templates import (
    conversation_list,
    conversation_page,
    conversations_page,
    name_of,
    thread,
)
from mailchat.shared.db import get_db
from mailchat.shared.layout import page

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_class=HTMLResponse)
async def list_conversations_page(session: AsyncSession = Depends(get_db)) -> str:
    return str(
        page(
            page_title="MailChat — Conversations",
            content=conversations_page(await service.list_conversations(session)),
        )
    )


# Declared above `/{conversation_id}`, which would otherwise catch it: a route
# with a literal path has to be offered to the router before the pattern that
# would swallow it.
@router.get("/list", response_class=HTMLResponse)
async def conversation_list_fragment(session: AsyncSession = Depends(get_db)) -> str:
    return str(conversation_list(await service.list_conversations(session)))


@router.get("/{conversation_id}", response_class=HTMLResponse)
async def read_conversation_page(
    conversation_id: int, session: AsyncSession = Depends(get_db)
) -> str:
    conversation = await service.get_conversation(session, conversation_id)
    messages = await service.messages_in(session, conversation_id)
    return str(
        page(
            page_title=f"MailChat — {name_of(conversation.contact)}",
            content=conversation_page(conversation, messages),
        )
    )


@router.get("/{conversation_id}/thread", response_class=HTMLResponse)
async def thread_fragment(conversation_id: int, session: AsyncSession = Depends(get_db)) -> str:
    conversation = await service.get_conversation(session, conversation_id)
    return str(thread(conversation, await service.messages_in(session, conversation_id)))
