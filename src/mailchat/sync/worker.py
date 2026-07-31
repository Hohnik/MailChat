from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailchat.accounts import repository as accounts_repository
from mailchat.accounts.models import Account
from mailchat.messages.models import Message
from mailchat.shared.security import decrypt
from mailchat.sync.imap_client import ImapCredentials
from mailchat.sync.imap_client import connect as imap_connect
from mailchat.sync.imap_client import fetch_recent_messages
from mailchat.sync.normalize import normalize
from mailchat.sync.parser import parse

logger = logging.getLogger(__name__)


def _fetch_raw_messages(credentials: ImapCredentials) -> list[bytes]:
    with imap_connect(credentials) as connection:
        return fetch_recent_messages(connection)


async def sync_account(session: AsyncSession, account: Account) -> list[Message]:
    credentials = ImapCredentials(
        host=account.imap_host,
        port=account.imap_port,
        username=account.address,
        password=decrypt(account.credentials.encrypted_password),
    )

    # imaplib is blocking; offload to a thread so a slow/hanging server
    # doesn't stall the event loop (and every other account's sync with it).
    raw_messages = await asyncio.to_thread(_fetch_raw_messages, credentials)

    return [await normalize(session, account_id=account.id, parsed=parse(raw)) for raw in raw_messages]


async def sync_all_accounts(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        accounts = await accounts_repository.list_accounts(session)

    await asyncio.gather(*(_sync_account_safely(session_factory, account) for account in accounts))


async def _sync_account_safely(session_factory: async_sessionmaker[AsyncSession], account: Account) -> None:
    try:
        async with session_factory() as session:
            await sync_account(session, account)
    except Exception:
        logger.exception("Sync failed for account %s", account.address)


async def poll_forever(session_factory: async_sessionmaker[AsyncSession], *, interval_seconds: float) -> None:
    while True:
        await sync_all_accounts(session_factory)
        await asyncio.sleep(interval_seconds)
