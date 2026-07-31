from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.accounts import repository
from mailchat.accounts.schemas import AccountConnect
from mailchat.accounts.service import connect, disconnect
from mailchat.accounts.templates import accounts_page, accounts_section
from mailchat.shared.db import get_db
from mailchat.shared.exceptions import AccountConnectionError
from mailchat.shared.layout import page

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_class=HTMLResponse)
async def list_accounts_page(session: AsyncSession = Depends(get_db)) -> str:
    accounts = await repository.list_accounts(session)
    return str(page(page_title="MailChat — Accounts", content=accounts_page(accounts)))


@router.post("", response_class=HTMLResponse)
async def create_account(
    session: AsyncSession = Depends(get_db),
    provider: str = Form(...),
    address: str = Form(...),
    imap_host: str = Form(...),
    imap_port: int = Form(...),
    smtp_host: str = Form(...),
    smtp_port: int = Form(...),
    password: str = Form(...),
) -> str:
    request = AccountConnect(
        provider=provider,
        address=address,
        imap_host=imap_host,
        imap_port=imap_port,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        password=password,
    )

    error = None
    try:
        await connect(session, request)
    except AccountConnectionError as exc:
        error = str(exc)

    accounts = await repository.list_accounts(session)
    return str(accounts_section(accounts, error=error))


@router.post("/{account_id}/disconnect", response_class=HTMLResponse)
async def disconnect_account(account_id: int, session: AsyncSession = Depends(get_db)) -> str:
    await disconnect(session, account_id)
    accounts = await repository.list_accounts(session)
    return str(accounts_section(accounts))
