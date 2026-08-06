from __future__ import annotations

from collections.abc import Awaitable

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from htpy import Node
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.accounts import service
from mailchat.accounts.schemas import AccountConnect
from mailchat.accounts.service import AccountFolders
from mailchat.accounts.templates import accounts_page, accounts_section, sent_folder_picker
from mailchat.mail import get_imap, get_smtp
from mailchat.mail.imap import Imap
from mailchat.mail.smtp import Smtp
from mailchat.shared.db import get_db
from mailchat.shared.exceptions import MailChatError
from mailchat.shared.layout import page

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_class=HTMLResponse)
async def list_accounts_page(session: AsyncSession = Depends(get_db)) -> str:
    return str(
        page(page_title="MailChat — Accounts", content=accounts_page(await service.list_accounts(session)))
    )


@router.post("", response_class=HTMLResponse)
async def create_account(
    session: AsyncSession = Depends(get_db),
    imap: Imap = Depends(get_imap),
    smtp: Smtp = Depends(get_smtp),
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
    return await _section(session, _picker_for(service.connect(session, request, imap=imap, smtp=smtp)))


@router.get("/{account_id}/sent-folder", response_class=HTMLResponse)
async def choose_sent_folder(
    account_id: int, session: AsyncSession = Depends(get_db), imap: Imap = Depends(get_imap)
) -> str:
    return await _section(session, _picker_for(service.list_account_folders(session, account_id, imap=imap)))


@router.post("/{account_id}/sent-folder", response_class=HTMLResponse)
async def save_sent_folder(
    account_id: int,
    session: AsyncSession = Depends(get_db),
    imap: Imap = Depends(get_imap),
    sent_folder: str = Form(...),
) -> str:
    return await _section(session, service.set_sent_folder(session, account_id, sent_folder, imap=imap))


@router.post("/{account_id}/disconnect", response_class=HTMLResponse)
async def disconnect_account(account_id: int, session: AsyncSession = Depends(get_db)) -> str:
    return await _section(session, service.disconnect(session, account_id))


async def _picker_for(listing: Awaitable[AccountFolders]) -> Node | None:
    """Wait on a listing of an account's folders and offer them to the user.

    No folders means the server wouldn't list them — the account list then
    offers a `Choose sent folder` button to try again.
    """
    listed = await listing
    if not listed.folders:
        return None
    return sent_folder_picker(listed.account, listed.folders)


async def _section(session: AsyncSession, action: Awaitable[Node | None]) -> str:
    """Run one thing the accounts module does, and render the section around it.

    Every route here answers with the same section, so this is the one place a
    domain error — a refused login, a folder the server lacks, an account that
    isn't there — becomes the message above the account list. Actions that
    listed folders leave a picker behind; the rest leave none.
    """
    error = None
    picker = None
    try:
        picker = await action
    except MailChatError as exc:
        error = str(exc)

    return str(accounts_section(await service.list_accounts(session), error=error, picker=picker))
