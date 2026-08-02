from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from htpy import Node
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.accounts import repository
from mailchat.accounts.schemas import AccountConnect
from mailchat.accounts.service import (
    AccountFolders,
    connect,
    disconnect,
    list_account_folders,
    set_sent_folder,
)
from mailchat.accounts.templates import accounts_page, accounts_section, sent_folder_picker
from mailchat.mail import get_imap
from mailchat.mail.imap import Imap
from mailchat.shared.db import get_db
from mailchat.shared.exceptions import AccountConnectionError, MailChatError
from mailchat.shared.layout import page

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_class=HTMLResponse)
async def list_accounts_page(session: AsyncSession = Depends(get_db)) -> str:
    accounts = await repository.list_accounts(session)
    return str(page(page_title="MailChat — Accounts", content=accounts_page(accounts)))


@router.post("", response_class=HTMLResponse)
async def create_account(
    session: AsyncSession = Depends(get_db),
    imap: Imap = Depends(get_imap),
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
        password=SecretStr(password),
    )

    error = None
    picker = None
    try:
        connected = await connect(session, request, imap=imap)
        picker = _picker_for(connected)
    except AccountConnectionError as exc:
        error = str(exc)

    return await _render_section(session, error=error, picker=picker)


@router.get("/{account_id}/sent-folder", response_class=HTMLResponse)
async def choose_sent_folder(
    account_id: int, session: AsyncSession = Depends(get_db), imap: Imap = Depends(get_imap)
) -> str:
    error = None
    picker = None
    try:
        picker = _picker_for(await list_account_folders(session, account_id, imap=imap))
    except MailChatError as exc:
        error = str(exc)

    return await _render_section(session, error=error, picker=picker)


@router.post("/{account_id}/sent-folder", response_class=HTMLResponse)
async def save_sent_folder(
    account_id: int,
    session: AsyncSession = Depends(get_db),
    imap: Imap = Depends(get_imap),
    sent_folder: str = Form(...),
) -> str:
    error = None
    try:
        await set_sent_folder(session, account_id, sent_folder, imap=imap)
    except MailChatError as exc:
        error = str(exc)

    return await _render_section(session, error=error)


@router.post("/{account_id}/disconnect", response_class=HTMLResponse)
async def disconnect_account(account_id: int, session: AsyncSession = Depends(get_db)) -> str:
    await disconnect(session, account_id)
    return await _render_section(session)


def _picker_for(listed: AccountFolders) -> Node | None:
    """No folders means the server wouldn't list them — the account list then
    offers a `Choose sent folder` button to try again."""
    if not listed.folders:
        return None
    return sent_folder_picker(listed.account, listed.folders)


async def _render_section(
    session: AsyncSession, *, error: str | None = None, picker: Node | None = None
) -> str:
    accounts = await repository.list_accounts(session)
    return str(accounts_section(accounts, error=error, picker=picker))
