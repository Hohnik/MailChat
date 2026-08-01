from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.accounts import repository
from mailchat.accounts.models import Account
from mailchat.accounts.schemas import AccountConnect
from mailchat.shared.exceptions import AccountConnectionError, AccountNotFoundError, UnknownFolderError
from mailchat.shared.security import decrypt, encrypt
from mailchat.sync.imap_client import ImapCredentials
from mailchat.sync.imap_client import connect as imap_connect
from mailchat.sync.imap_client import list_folders
from mailchat.sync.smtp_client import SmtpCredentials
from mailchat.sync.smtp_client import connect as smtp_connect

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountFolders:
    """An account, plus the folders its IMAP server offered.

    On connect the folders come from the same session that verified the
    credentials, so the caller can offer the Sent-folder picker without a
    second login. `folders` is empty when the server wouldn't list them.
    """

    account: Account
    folders: list[str]


def imap_credentials_for(account: Account) -> ImapCredentials:
    """Rebuild an account's IMAP login from its stored, encrypted password."""
    return ImapCredentials(
        host=account.imap_host,
        port=account.imap_port,
        username=account.address,
        password=decrypt(account.credentials.encrypted_password),
    )


async def connect(session: AsyncSession, request: AccountConnect) -> AccountFolders:
    password = request.password.get_secret_value()
    imap_credentials = ImapCredentials(
        host=request.imap_host, port=request.imap_port, username=request.address, password=password
    )
    smtp_credentials = SmtpCredentials(
        host=request.smtp_host, port=request.smtp_port, username=request.address, password=password
    )

    try:
        # imaplib/smtplib are blocking; keep a slow server off the event loop.
        folders = await asyncio.to_thread(_verify, imap_credentials, smtp_credentials)
    except Exception as error:
        raise AccountConnectionError(f"Could not connect to {request.address}: {error}") from error

    account = await repository.create_account(
        session,
        provider=request.provider,
        address=request.address,
        imap_host=request.imap_host,
        imap_port=request.imap_port,
        smtp_host=request.smtp_host,
        smtp_port=request.smtp_port,
        encrypted_password=encrypt(password),
    )
    return AccountFolders(account=account, folders=folders)


async def list_account_folders(session: AsyncSession, account_id: int) -> AccountFolders:
    """Re-list an existing account's folders, using its stored credentials."""
    account = await _get_account(session, account_id)
    return AccountFolders(account=account, folders=await _folders_of(account))


async def set_sent_folder(session: AsyncSession, account_id: int, folder: str) -> Account:
    """Record which folder holds this account's sent mail.

    The folder is checked against the server's own list rather than trusted from
    the form, so a stale or hand-made request can't point sync at a folder that
    isn't there.
    """
    account = await _get_account(session, account_id)
    if folder not in await _folders_of(account):
        raise UnknownFolderError(f"No folder named {repr(folder)} on the server")

    return await repository.set_sent_folder(session, account, folder)


async def disconnect(session: AsyncSession, account_id: int) -> None:
    await repository.delete_account(session, account_id)


def _list_folders(credentials: ImapCredentials) -> list[str]:
    with imap_connect(credentials) as connection:
        return list_folders(connection)


def _verify(imap_credentials: ImapCredentials, smtp_credentials: SmtpCredentials) -> list[str]:
    """Prove both sets of credentials, and list the IMAP folders while logged in.

    A listing that fails doesn't undo a successful login — the account is still
    connected, the user just picks their Sent folder later.
    """
    with imap_connect(imap_credentials) as connection:
        try:
            folders = list_folders(connection)
        except Exception:
            logger.exception("Could not list folders for %s", imap_credentials.username)
            folders = []

    with smtp_connect(smtp_credentials):
        pass

    return folders


async def _folders_of(account: Account) -> list[str]:
    try:
        # imaplib is blocking; keep a slow server off the event loop.
        return await asyncio.to_thread(_list_folders, imap_credentials_for(account))
    except Exception as error:
        raise AccountConnectionError(f"Could not list folders for {account.address}: {error}") from error


async def _get_account(session: AsyncSession, account_id: int) -> Account:
    account = await repository.get_account(session, account_id)
    if account is None:
        raise AccountNotFoundError(f"No account with id {account_id}")
    return account
