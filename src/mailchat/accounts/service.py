from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.accounts import repository
from mailchat.accounts.models import Account
from mailchat.accounts.schemas import AccountConnect
from mailchat.shared.exceptions import AccountConnectionError
from mailchat.shared.security import encrypt
from mailchat.sync.imap_client import ImapCredentials
from mailchat.sync.imap_client import connect as imap_connect
from mailchat.sync.smtp_client import SmtpCredentials
from mailchat.sync.smtp_client import connect as smtp_connect


async def connect(session: AsyncSession, request: AccountConnect) -> Account:
    imap_credentials = ImapCredentials(
        host=request.imap_host, port=request.imap_port, username=request.address, password=request.password
    )
    smtp_credentials = SmtpCredentials(
        host=request.smtp_host, port=request.smtp_port, username=request.address, password=request.password
    )

    try:
        with imap_connect(imap_credentials):
            pass
        with smtp_connect(smtp_credentials):
            pass
    except Exception as error:
        raise AccountConnectionError(f"Could not connect to {request.address}: {error}") from error

    return await repository.create_account(
        session,
        provider=request.provider,
        address=request.address,
        imap_host=request.imap_host,
        imap_port=request.imap_port,
        smtp_host=request.smtp_host,
        smtp_port=request.smtp_port,
        encrypted_password=encrypt(request.password),
    )


async def disconnect(session: AsyncSession, account_id: int) -> None:
    await repository.delete_account(session, account_id)
