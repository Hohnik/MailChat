from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mailchat.accounts.models import Account, Credentials


async def create_account(
    session: AsyncSession,
    *,
    provider: str,
    address: str,
    imap_host: str,
    imap_port: int,
    smtp_host: str,
    smtp_port: int,
    encrypted_password: str,
) -> Account:
    account = Account(
        provider=provider,
        address=address,
        imap_host=imap_host,
        imap_port=imap_port,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        credentials=Credentials(encrypted_password=encrypted_password),
    )
    session.add(account)
    await session.commit()
    return account


async def list_accounts(session: AsyncSession) -> list[Account]:
    result = await session.execute(
        select(Account).options(selectinload(Account.credentials)).order_by(Account.connected_at)
    )
    return list(result.scalars().all())


async def get_account(session: AsyncSession, account_id: int) -> Account | None:
    result = await session.execute(
        select(Account).options(selectinload(Account.credentials)).where(Account.id == account_id)
    )
    return result.scalar_one_or_none()


async def set_sent_folder(session: AsyncSession, account: Account, folder: str) -> None:
    account.sent_folder = folder
    await session.commit()


async def delete_account(session: AsyncSession, account: Account) -> None:
    await session.delete(account)
    await session.commit()
