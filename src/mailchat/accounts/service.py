from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from mailchat.accounts import repository
from mailchat.accounts.models import Account
from mailchat.accounts.schemas import AccountConnect
from mailchat.mail import imap as imap_module
from mailchat.mail import smtp as smtp_module
from mailchat.mail.imap import Imap, ImapCredentials, ImapError, ImapLoginError
from mailchat.mail.smtp import Smtp, SmtpCredentials, SmtpError
from mailchat.shared.exceptions import AccountConnectionError, AccountNotFoundError, UnknownFolderError
from mailchat.shared.security import decrypt, encrypt

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountFolders:
    """An account, plus the folders its IMAP server offered.

    On connect the folders come from the same call that verified the
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


async def list_accounts(session: AsyncSession) -> list[Account]:
    """Every connected account, oldest first.

    A pass-through to storage, and deliberately so: it is what makes this module
    the only way in. A caller that reads accounts here reads them the same way it
    acts on them, and hears about a missing one in the same vocabulary.
    """
    return await repository.list_accounts(session)


async def get_account(session: AsyncSession, account_id: int) -> Account:
    """The one answer to "is there an account with this id?".

    Raises `AccountNotFoundError` rather than returning `None`, so that every
    caller — routes included — deals with a missing account the same way instead
    of inventing its own.
    """
    account = await repository.get_account(session, account_id)
    if account is None:
        raise AccountNotFoundError(f"No account with id {account_id}")
    return account


async def connect(
    session: AsyncSession,
    request: AccountConnect,
    *,
    imap: Imap = imap_module,
    smtp: Smtp = smtp_module,
) -> AccountFolders:
    password = request.password.get_secret_value()
    imap_credentials = ImapCredentials(
        host=request.imap_host, port=request.imap_port, username=request.address, password=password
    )
    smtp_credentials = SmtpCredentials(
        host=request.smtp_host, port=request.smtp_port, username=request.address, password=password
    )

    folders = await _verified_folders(imap, imap_credentials)
    await _verify_smtp(smtp, smtp_credentials)

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


async def list_account_folders(
    session: AsyncSession, account_id: int, *, imap: Imap = imap_module
) -> AccountFolders:
    """Re-list an existing account's folders, using its stored credentials."""
    account = await get_account(session, account_id)
    return AccountFolders(account=account, folders=await _folders_of(imap, account))


async def set_sent_folder(
    session: AsyncSession, account_id: int, folder: str, *, imap: Imap = imap_module
) -> None:
    """Record which folder holds this account's sent mail.

    The folder is checked against the server's own list rather than trusted from
    the form, so a stale or hand-made request can't point sync at a folder that
    isn't there.
    """
    account = await get_account(session, account_id)
    if folder not in await _folders_of(imap, account):
        raise UnknownFolderError(f"No folder named {repr(folder)} on the server")

    await repository.set_sent_folder(session, account, folder)


async def disconnect(session: AsyncSession, account_id: int) -> None:
    """Forget an account and the credentials it was connected with.

    An id that isn't there raises like it does anywhere else in this module,
    rather than passing for a disconnection that happened.
    """
    await repository.delete_account(session, await get_account(session, account_id))


async def _verified_folders(imap: Imap, credentials: ImapCredentials) -> list[str]:
    """Prove the IMAP credentials by listing folders, and keep the list.

    A listing the server refuses doesn't undo a successful login — the account
    still connects, the user just picks their Sent folder later.
    """
    try:
        return await imap.folders(credentials)
    except ImapLoginError as error:
        raise AccountConnectionError(f"Could not connect to {credentials.username}: {error}") from error
    except ImapError:
        logger.exception("Could not list folders for %s", credentials.username)
        return []


async def _verify_smtp(smtp: Smtp, credentials: SmtpCredentials) -> None:
    try:
        await smtp.verify(credentials)
    except SmtpError as error:
        raise AccountConnectionError(f"Could not connect to {credentials.username}: {error}") from error


async def _folders_of(imap: Imap, account: Account) -> list[str]:
    try:
        return await imap.folders(imap_credentials_for(account))
    except ImapError as error:
        raise AccountConnectionError(f"Could not list folders for {account.address}: {error}") from error
