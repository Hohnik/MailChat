from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from mailchat.mail.imap import ImapCredentials, ImapLoginError, ImapOperationError, fetch, folders

CREDENTIALS = ImapCredentials(
    host="secureimap.t-online.de", port=993, username="user@t-online.de", password="secret"
)

RAW_MESSAGE = b"Subject: hello\r\n\r\nbody\r\n"


class StubConnection:
    """A tiny IMAP server: mailboxes of raw messages, plus canned failures.

    Only the commands the module issues are answered. Tests that care about the
    wire format hand `list_response` the exact entries a server would send.
    """

    def __init__(
        self,
        mailboxes: dict[str, list[bytes]] | None = None,
        *,
        list_response: tuple[str, list[Any]] = ("OK", []),
        login_error: Exception | None = None,
        logout_error: Exception | None = None,
        select_status: str = "OK",
        search_status: str = "OK",
        fetch_status: str = "OK",
        fetch_delay_seconds: float = 0.0,
    ) -> None:
        self.mailboxes = mailboxes or {}
        self.list_response = list_response
        self.login_error = login_error
        self.logout_error = logout_error
        self.select_status = select_status
        self.search_status = search_status
        self.fetch_status = fetch_status
        self.fetch_delay_seconds = fetch_delay_seconds

        self.logins: list[tuple[str, str]] = []
        self.logouts = 0
        self.selections: list[tuple[str, bool]] = []
        self.fetched_ids: list[str] = []
        self._selected: list[bytes] = []

    def login(self, user: str, password: str) -> tuple[str, list[Any]]:
        if self.login_error is not None:
            raise self.login_error
        self.logins.append((user, password))
        return ("OK", [b"logged in"])

    def logout(self) -> tuple[str, list[Any]]:
        self.logouts += 1
        if self.logout_error is not None:
            raise self.logout_error
        return ("BYE", [b"bye"])

    def list(self) -> tuple[str, list[Any]]:
        return self.list_response

    def select(self, mailbox: str, readonly: bool) -> tuple[str, list[Any]]:
        self.selections.append((mailbox, readonly))
        if self.select_status != "OK":
            return (self.select_status, [b"no such mailbox"])
        self._selected = self.mailboxes.get(mailbox, [])
        return ("OK", [str(len(self._selected)).encode()])

    def search(self, charset: str | None, *criteria: str) -> tuple[str, list[Any]]:
        if self.search_status != "OK":
            return (self.search_status, [b""])
        ids = b" ".join(str(number).encode() for number in range(1, len(self._selected) + 1))
        return ("OK", [ids])

    def fetch(self, message_set: str, message_parts: str) -> tuple[str, list[Any]]:
        self.fetched_ids.append(message_set)
        if self.fetch_delay_seconds:
            time.sleep(self.fetch_delay_seconds)
        if self.fetch_status != "OK":
            return (self.fetch_status, [b""])
        raw = self._selected[int(message_set) - 1]
        return ("OK", [(f"{message_set} (RFC822 {{{len(raw)}}}".encode(), raw)])


class StubTransport:
    """A `Transport` handing out one connection, recording where it was pointed."""

    def __init__(self, connection: StubConnection, *, connect_error: Exception | None = None) -> None:
        self.connection = connection
        self.connect_error = connect_error
        self.opened: list[tuple[str, int]] = []

    def __call__(self, host: str, port: int) -> StubConnection:
        self.opened.append((host, port))
        if self.connect_error is not None:
            raise self.connect_error
        return self.connection


async def test_folders_returns_mailbox_names():
    connection = StubConnection(
        list_response=(
            "OK",
            [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren) "/" "Sent Items"',
                b'(\\HasNoChildren) "/" Drafts',
                b'(\\Noselect) NIL "Public"',
            ],
        )
    )

    listed = await folders(CREDENTIALS, transport=StubTransport(connection))

    assert listed == ["INBOX", "Sent Items", "Drafts", "Public"]


async def test_folders_reads_names_the_server_sent_as_literals():
    connection = StubConnection(list_response=("OK", [(b'(\\HasNoChildren) "/" {8}', b"Gesendet"), b""]))

    listed = await folders(CREDENTIALS, transport=StubTransport(connection))

    assert listed == ["Gesendet"]


async def test_folders_logs_in_at_the_credentials_address_and_logs_out():
    connection = StubConnection()
    transport = StubTransport(connection)

    await folders(CREDENTIALS, transport=transport)

    assert transport.opened == [("secureimap.t-online.de", 993)]
    assert connection.logins == [("user@t-online.de", "secret")]
    assert connection.logouts == 1


async def test_folders_raises_a_login_error_when_the_server_refuses_the_password():
    connection = StubConnection(login_error=OSError("authentication failed"))

    with pytest.raises(ImapLoginError):
        await folders(CREDENTIALS, transport=StubTransport(connection))


async def test_a_refused_login_does_not_leave_the_connection_open():
    connection = StubConnection(login_error=OSError("authentication failed"))

    with pytest.raises(ImapLoginError):
        await folders(CREDENTIALS, transport=StubTransport(connection))

    assert connection.logouts == 1


async def test_folders_raises_a_login_error_when_the_server_cannot_be_reached():
    connection = StubConnection()

    with pytest.raises(ImapLoginError):
        await folders(CREDENTIALS, transport=StubTransport(connection, connect_error=OSError("no route to host")))


async def test_folders_raises_an_operation_error_on_non_ok_status():
    connection = StubConnection(list_response=("NO", []))

    with pytest.raises(ImapOperationError):
        await folders(CREDENTIALS, transport=StubTransport(connection))


async def test_folders_raises_an_operation_error_on_an_unparsable_entry():
    connection = StubConnection(list_response=("OK", [b"nonsense"]))

    with pytest.raises(ImapOperationError):
        await folders(CREDENTIALS, transport=StubTransport(connection))


async def test_folders_logs_out_when_the_operation_fails():
    connection = StubConnection(list_response=("NO", []))

    with pytest.raises(ImapOperationError):
        await folders(CREDENTIALS, transport=StubTransport(connection))

    assert connection.logouts == 1


async def test_a_failing_logout_does_not_hide_the_operation_that_failed():
    connection = StubConnection(list_response=("NO", []), logout_error=OSError("connection reset"))

    with pytest.raises(ImapOperationError):
        await folders(CREDENTIALS, transport=StubTransport(connection))


async def test_fetch_selects_readonly_and_returns_the_most_recent_messages():
    mailbox = [b"one", b"two", b"three", b"four", b"five"]
    connection = StubConnection({"INBOX": mailbox})

    messages = await fetch(CREDENTIALS, ["INBOX"], limit=2, transport=StubTransport(connection))

    assert messages == [b"four", b"five"]
    assert connection.selections == [("INBOX", True)]
    assert connection.fetched_ids == ["4", "5"]


async def test_fetch_returns_every_message_when_the_mailbox_is_smaller_than_the_limit():
    connection = StubConnection({"INBOX": [RAW_MESSAGE]})

    messages = await fetch(CREDENTIALS, ["INBOX"], transport=StubTransport(connection))

    assert messages == [RAW_MESSAGE]


async def test_fetch_reads_each_folder_it_is_given():
    connection = StubConnection({"INBOX": [b"inbox mail"], "Gesendet": [b"sent mail"]})

    messages = await fetch(CREDENTIALS, ["INBOX", "Gesendet"], transport=StubTransport(connection))

    assert messages == [b"inbox mail", b"sent mail"]


async def test_fetch_raises_an_operation_error_when_the_folder_cannot_be_selected():
    connection = StubConnection(select_status="NO")

    with pytest.raises(ImapOperationError):
        await fetch(CREDENTIALS, ["Missing"], transport=StubTransport(connection))


async def test_fetch_raises_an_operation_error_when_the_search_fails():
    connection = StubConnection({"INBOX": [RAW_MESSAGE]}, search_status="NO")

    with pytest.raises(ImapOperationError):
        await fetch(CREDENTIALS, ["INBOX"], transport=StubTransport(connection))


async def test_fetch_raises_an_operation_error_when_a_message_cannot_be_read():
    connection = StubConnection({"INBOX": [RAW_MESSAGE]}, fetch_status="NO")

    with pytest.raises(ImapOperationError):
        await fetch(CREDENTIALS, ["INBOX"], transport=StubTransport(connection))


async def test_fetch_leaves_the_event_loop_free_while_the_server_is_slow():
    delay_seconds = 0.3
    connections = [StubConnection({"INBOX": [RAW_MESSAGE]}, fetch_delay_seconds=delay_seconds) for _ in range(2)]

    start = time.monotonic()
    await asyncio.gather(
        *(fetch(CREDENTIALS, ["INBOX"], transport=StubTransport(connection)) for connection in connections)
    )
    elapsed = time.monotonic() - start

    # Blocking imaplib calls run in threads; on the event loop these would queue
    # up and take ~2x delay_seconds instead.
    assert elapsed < delay_seconds * 1.5
