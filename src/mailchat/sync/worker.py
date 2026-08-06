from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailchat.accounts import service as accounts_service
from mailchat.accounts.folders import synced_folders
from mailchat.accounts.models import Account
from mailchat.accounts.service import imap_credentials_for
from mailchat.mail import imap as imap_module
from mailchat.mail.imap import Imap
from mailchat.messages.models import Message
from mailchat.sync.ingest import ingest

logger = logging.getLogger(__name__)


class SyncWorker(Protocol):
    """A loop that keeps one database's accounts in sync for as long as it runs
    — `poll_forever` with an interval bound to it, or a test's stand-in."""

    async def __call__(self, session_factory: async_sessionmaker[AsyncSession]) -> None: ...


async def sync_account(session: AsyncSession, account: Account, *, imap: Imap = imap_module) -> list[Message]:
    """One pass over one account's synced folders, which the account itself
    answers for — asked again every pass, so nothing has to be restarted for a
    newly picked folder to be read."""
    raw_messages = await imap.fetch(imap_credentials_for(account), synced_folders(account))

    return await ingest(session, account_id=account.id, raw_messages=raw_messages)


async def sync_all_accounts(
    session_factory: async_sessionmaker[AsyncSession], *, imap: Imap = imap_module
) -> None:
    async with session_factory() as session:
        accounts = await accounts_service.list_accounts(session)

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
