from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from htpy import Node
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.accounts import service
from mailchat.accounts.schemas import AccountConnect
from mailchat.accounts.templates import accounts_page, accounts_section, sent_folder_picker
from mailchat.mail import get_imap, get_smtp
from mailchat.mail.imap import Imap
from mailchat.mail.smtp import Smtp
from mailchat.shared.db import get_db
from mailchat.shared.exceptions import AccountNotFoundError, MailChatError
from mailchat.shared.layout import page

router = APIRouter(prefix="/accounts", tags=["accounts"])

ACCOUNT_GONE = "That account is no longer connected."
"""What a missing account means to someone looking at the page.

Every button that reaches these routes was rendered from the account list, so an
id that isn't there means the page went stale — not that the user mistyped. The
domain's own wording names the id, which belongs in a log; above an account list
it reads like a stack trace, and the request carried the id anyway. `main.py`
renders the same error in its own words, for the same reason.
"""


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
    return await _section_after(session, lambda: service.connect(session, request, imap=imap, smtp=smtp))


@router.get("/{account_id}/sent-folder", response_class=HTMLResponse)
async def choose_sent_folder(
    account_id: int, session: AsyncSession = Depends(get_db), imap: Imap = Depends(get_imap)
) -> str:
    return await _section_after(
        session, lambda: service.list_account_folders(session, account_id, imap=imap)
    )


@router.post("/{account_id}/sent-folder", response_class=HTMLResponse)
async def save_sent_folder(
    account_id: int,
    session: AsyncSession = Depends(get_db),
    imap: Imap = Depends(get_imap),
    sent_folder: str = Form(...),
) -> str:
    return await _section_after(
        session, lambda: service.set_sent_folder(session, account_id, sent_folder, imap=imap)
    )


@router.post("/{account_id}/disconnect", response_class=HTMLResponse)
async def disconnect_account(account_id: int, session: AsyncSession = Depends(get_db)) -> str:
    return await _section_after(session, lambda: service.disconnect(session, account_id))


def _picker_for(listed: service.AccountFolders | None) -> Node | None:
    """The picker an action left behind, if it listed any folders.

    Nothing to pick from means either the action wasn't a listing at all, or the
    server wouldn't list them — the account list then offers a `Choose sent
    folder` button to try again.
    """
    if listed is None or not listed.folders:
        return None
    return sent_folder_picker(listed.account, listed.folders)


async def _section_after(
    session: AsyncSession, action: Callable[[], Awaitable[service.AccountFolders | None]]
) -> str:
    """Run one thing the accounts module does, then render the section around it.

    Every route here answers with the same section, so this is the one place a
    domain error — a refused login, a folder the server lacks, an account that
    isn't there — becomes the message above the account list.

    `action` is a callable rather than a coroutine so that building the work and
    running it can't come apart: a coroutine made at the call site is already
    live, and any path that returned before awaiting it would drop its database
    work with nothing but a warning. No path here does that today — the callable
    is what keeps it that way. Actions that listed folders hand them back for the
    picker; the rest hand back nothing.
    """
    error = None
    listed = None
    try:
        listed = await action()
    except AccountNotFoundError:
        error = ACCOUNT_GONE
    except MailChatError as exc:
        error = str(exc)

    return str(
        accounts_section(await service.list_accounts(session), error=error, picker=_picker_for(listed))
    )
