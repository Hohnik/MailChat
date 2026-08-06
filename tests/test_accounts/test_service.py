from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from mailchat.accounts.models import Account
from mailchat.accounts.schemas import AccountConnect
from mailchat.accounts.service import (
    connect,
    disconnect,
    get_account,
    list_account_folders,
    list_accounts,
    set_sent_folder,
)
from mailchat.mail.imap import ImapCredentials, ImapLoginError, ImapOperationError
from mailchat.mail.smtp import SmtpCredentials, SmtpLoginError
from mailchat.shared.exceptions import (
    AccountConnectionError,
    AccountNotFoundError,
    UnknownFolderError,
)
from mailchat.shared.security import decrypt
from tests.fakes import FakeImap, FakeSmtp

REQUEST = AccountConnect(
    provider="t-online",
    address="user@t-online.de",
    imap_host="secureimap.t-online.de",
    imap_port=993,
    smtp_host="securesmtp.t-online.de",
    smtp_port=465,
    password=SecretStr("app-specific-secret"),
)


async def test_connect_persists_account_on_successful_validation(session):
    connected = await connect(session, REQUEST, imap=FakeImap().offer("INBOX", "Sent"), smtp=FakeSmtp())

    assert connected.account.address == REQUEST.address
    assert decrypt(connected.account.credentials.encrypted_password) == REQUEST.password.get_secret_value()


async def test_connect_verifies_the_smtp_login_too(session):
    smtp = FakeSmtp()

    await connect(session, REQUEST, imap=FakeImap().offer("INBOX", "Sent"), smtp=smtp)

    assert smtp.seen == [
        SmtpCredentials(
            host=REQUEST.smtp_host,
            port=REQUEST.smtp_port,
            username=REQUEST.address,
            password=REQUEST.password.get_secret_value(),
        )
    ]


async def test_connect_returns_the_folders_the_server_listed(session):
    imap = FakeImap().offer("INBOX", "Gesendet", "Entwürfe")

    connected = await connect(session, REQUEST, imap=imap, smtp=FakeSmtp())

    assert connected.folders == ["INBOX", "Gesendet", "Entwürfe"]


async def test_connect_leaves_sent_folder_unset_until_the_user_picks(session):
    connected = await connect(session, REQUEST, imap=FakeImap().offer("INBOX", "Sent"), smtp=FakeSmtp())

    assert connected.account.sent_folder is None


async def test_connect_still_succeeds_when_the_server_refuses_to_list_folders(session):
    imap = FakeImap(folders_error=ImapOperationError("LIST failed: NO"))

    connected = await connect(session, REQUEST, imap=imap, smtp=FakeSmtp())

    assert connected.account.address == REQUEST.address
    assert connected.folders == []


async def test_get_account_returns_the_connected_account(session):
    connected = await connect(session, REQUEST, imap=FakeImap().offer("INBOX", "Sent"), smtp=FakeSmtp())

    assert (await get_account(session, connected.account.id)).address == REQUEST.address


async def test_get_account_raises_for_an_account_that_is_not_there(session):
    with pytest.raises(AccountNotFoundError):
        await get_account(session, 999)


async def test_list_accounts_returns_every_connected_account(session):
    imap = FakeImap().offer("INBOX", "Sent")
    for address in ("first@t-online.de", "second@t-online.de"):
        await connect(session, REQUEST.model_copy(update={"address": address}), imap=imap, smtp=FakeSmtp())

    assert [account.address for account in await list_accounts(session)] == [
        "first@t-online.de",
        "second@t-online.de",
    ]


async def test_list_accounts_is_empty_before_anything_is_connected(session):
    assert await list_accounts(session) == []


async def test_list_account_folders_reconnects_with_the_stored_credentials(session):
    imap = FakeImap().offer("INBOX", "Sent")
    connected = await connect(session, REQUEST, imap=imap, smtp=FakeSmtp())

    listed = await list_account_folders(session, connected.account.id, imap=imap)

    assert listed.folders == ["INBOX", "Sent"]
    assert imap.seen[-1] == ImapCredentials(
        host=REQUEST.imap_host,
        port=REQUEST.imap_port,
        username=REQUEST.address,
        password=REQUEST.password.get_secret_value(),
    )


async def test_list_account_folders_fails_when_the_stored_password_stops_working(session):
    imap = FakeImap().offer("INBOX", "Sent")
    connected = await connect(session, REQUEST, imap=imap, smtp=FakeSmtp())
    imap.errors = {REQUEST.address: ImapLoginError("bad credentials")}

    with pytest.raises(AccountConnectionError):
        await list_account_folders(session, connected.account.id, imap=imap)


async def test_set_sent_folder_persists_the_selection(session):
    imap = FakeImap().offer("INBOX", "Gesendet")
    connected = await connect(session, REQUEST, imap=imap, smtp=FakeSmtp())

    await set_sent_folder(session, connected.account.id, "Gesendet", imap=imap)

    result = await session.execute(select(Account))
    assert result.scalars().one().sent_folder == "Gesendet"


async def test_set_sent_folder_rejects_a_folder_the_account_does_not_have(session):
    imap = FakeImap().offer("INBOX", "Gesendet")
    connected = await connect(session, REQUEST, imap=imap, smtp=FakeSmtp())

    with pytest.raises(UnknownFolderError):
        await set_sent_folder(session, connected.account.id, "Sent", imap=imap)

    result = await session.execute(select(Account))
    assert result.scalars().one().sent_folder is None


async def test_connect_raises_and_does_not_persist_on_imap_failure(session):
    imap = FakeImap(errors={REQUEST.address: ImapLoginError("bad credentials")})

    with pytest.raises(AccountConnectionError):
        await connect(session, REQUEST, imap=imap, smtp=FakeSmtp())

    result = await session.execute(select(Account))
    assert result.scalars().first() is None


async def test_connect_raises_and_does_not_persist_on_smtp_failure(session):
    smtp = FakeSmtp(errors={REQUEST.address: SmtpLoginError("bad credentials")})

    with pytest.raises(AccountConnectionError):
        await connect(session, REQUEST, imap=FakeImap().offer("INBOX", "Sent"), smtp=smtp)

    result = await session.execute(select(Account))
    assert result.scalars().first() is None


async def test_disconnect_raises_for_an_account_that_is_not_there(session):
    with pytest.raises(AccountNotFoundError):
        await disconnect(session, 999)


async def test_disconnect_removes_account(session):
    connected = await connect(session, REQUEST, imap=FakeImap().offer("INBOX", "Sent"), smtp=FakeSmtp())

    await disconnect(session, connected.account.id)

    result = await session.execute(select(Account))
    assert result.scalars().first() is None
