from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailchat.accounts import repository as accounts_repository
from mailchat.accounts.models import Account
from mailchat.accounts.service import imap_credentials_for
from mailchat.mail import imap as imap_module
from mailchat.mail.imap import Imap
from mailchat.messages.models import Message
from mailchat.sync.normalize import normalize
from mailchat.sync.parser import parse

logger = logging.getLogger(__name__)

# The only folder the worker syncs so far; the Sent folder follows once
# outgoing mail lands in the same list.
SYNCED_FOLDERS = ("INBOX",)


async def sync_account(session: AsyncSession, account: Account, *, imap: Imap = imap_module) -> list[Message]:
    raw_messages = await imap.fetch(imap_credentials_for(account), SYNCED_FOLDERS)

    return [await normalize(session, account_id=account.id, parsed=parse(raw)) for raw in raw_messages]


async def sync_all_accounts(
    session_factory: async_sessionmaker[AsyncSession], *, imap: Imap = imap_module
) -> None:
    async with session_factory() as session:
        accounts = await accounts_repository.list_accounts(session)

    await asyncio.gather(*(_sync_account_safely(session_factory, account, imap) for account in accounts))


async def _sync_account_safely(
    session_factory: async_sessionmaker[AsyncSession], account: Account, imap: Imap
) -> None:
    try:
        async with session_factory() as session:
            await sync_account(session, account, imap=imap)
    except Exception:
        logger.exception("Sync failed for account %s", account.address)


async def poll_forever(
    session_factory: async_sessionmaker[AsyncSession], *, interval_seconds: float, imap: Imap = imap_module
) -> None:
    while True:
        await sync_all_accounts(session_factory, imap=imap)
        await asyncio.sleep(interval_seconds)
