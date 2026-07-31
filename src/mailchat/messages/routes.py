from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.accounts import repository as accounts_repository
from mailchat.accounts.models import Account
from mailchat.messages import repository as messages_repository
from mailchat.messages.templates import message_list, messages_page
from mailchat.shared.db import get_db
from mailchat.shared.layout import page

router = APIRouter(prefix="/accounts/{account_id}/messages", tags=["messages"])


async def _get_account_or_404(session: AsyncSession, account_id: int) -> Account:
    account = await accounts_repository.get_account(session, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get("", response_class=HTMLResponse)
async def list_messages_page(account_id: int, session: AsyncSession = Depends(get_db)) -> str:
    account = await _get_account_or_404(session, account_id)
    messages = await messages_repository.list_messages_for_account(session, account_id)
    return str(page(page_title=f"MailChat — {account.address}", content=messages_page(account, messages)))


@router.get("/list", response_class=HTMLResponse)
async def messages_list_fragment(account_id: int, session: AsyncSession = Depends(get_db)) -> str:
    await _get_account_or_404(session, account_id)
    messages = await messages_repository.list_messages_for_account(session, account_id)
    return str(message_list(messages))
