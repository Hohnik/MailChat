"""Everything the app knows about reading mail over IMAP.

Callers hand over credentials and get domain values back. This module owns the
connection's lifetime, the wire format, and the thread that keeps blocking
imaplib calls off the event loop — none of which is visible from outside.
"""

from __future__ import annotations

import asyncio
import imaplib
import logging
import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImapCredentials:
    host: str
    port: int
    username: str
    password: str


class ImapError(Exception):
    """Base for everything this module raises; nothing else escapes it."""


class ImapLoginError(ImapError):
    """The server couldn't be reached, or wouldn't accept these credentials.

    Fatal: there is no session, so nothing else will work either.
    """


class ImapOperationError(ImapError):
    """The login worked, but a command after it didn't.

    Survivable: an account whose server refuses to LIST is still a usable
    account, so callers may choose to carry on.
    """


class ImapConnection(Protocol):
    """The slice of `imaplib.IMAP4_SSL` this module uses."""

    def login(self, user: str, password: str) -> Any: ...
    def logout(self) -> Any: ...
    def list(self) -> tuple[str, list[Any]]: ...
    def select(self, mailbox: str, readonly: bool) -> tuple[str, list[Any]]: ...
    def search(self, charset: str | None, *criteria: str) -> tuple[str, list[Any]]: ...
    def fetch(self, message_set: str, message_parts: str) -> tuple[str, list[Any]]: ...


Transport = Callable[[str, int], ImapConnection]
"""Opens a connection to a host and port — `imaplib.IMAP4_SSL`, or a stub in this module's tests."""


class Imap(Protocol):
    """What this module looks like to its callers.

    Callers type their dependency as this protocol and default it to the module
    itself, so their tests pass a fake in rather than patching.
    """

    async def folders(self, credentials: ImapCredentials) -> list[str]: ...

    async def fetch(
        self, credentials: ImapCredentials, folders: Sequence[str], limit: int = 10
    ) -> list[bytes]: ...


async def folders(credentials: ImapCredentials, *, transport: Transport = imaplib.IMAP4_SSL) -> list[str]:
    """The mailboxes the server offers — and, in passing, proof that the login works.

    Names come back exactly as the server sends them (IMAP modified UTF-7 for
    non-ASCII), which is the form SELECT expects to get back.
    """
    return await asyncio.to_thread(_list_folders, credentials, transport)


async def fetch(
    credentials: ImapCredentials,
    folders: Sequence[str],
    limit: int = 10,
    *,
    transport: Transport = imaplib.IMAP4_SSL,
) -> list[bytes]:
    """The `limit` most recent raw messages from each of `folders`, in that order."""
    return await asyncio.to_thread(_fetch_recent, credentials, folders, limit, transport)


@contextmanager
def _session(credentials: ImapCredentials, transport: Transport) -> Iterator[ImapConnection]:
    """A logged-in connection that always logs out again, however it ends.

    Once the connection is open it is logged out even if the login itself is
    refused, so a rejected password doesn't leave a socket behind.
    """
    try:
        connection = transport(credentials.host, credentials.port)
    except Exception as error:
        raise ImapLoginError(f"Could not reach {credentials.host}: {error}") from error

    try:
        try:
            connection.login(credentials.username, credentials.password)
        except Exception as error:
            raise ImapLoginError(
                f"Could not log in to {credentials.host} as {credentials.username}: {error}"
            ) from error

        yield connection
    finally:
        try:
            connection.logout()
        except Exception:
            # A logout that fails must not replace the error we're carrying out.
            logger.warning("IMAP logout failed for %s", credentials.username, exc_info=True)


def _list_folders(credentials: ImapCredentials, transport: Transport) -> list[str]:
    with _session(credentials, transport) as connection:
        status, entries = connection.list()
        if status != "OK":
            raise ImapOperationError(f"LIST failed: {status}")

        names = (_folder_name(entry) for entry in entries if entry is not None)
        return [name for name in names if name is not None]


_LIST_ENTRY = re.compile(r'^\([^)]*\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$')


def _folder_name(entry: bytes | tuple[bytes, bytes]) -> str | None:
    """Pull the mailbox name out of one `(flags) delimiter name` LIST entry."""
    if isinstance(entry, tuple):
        # The server sent the name as a literal: (b'(\\HasNoChildren) "/" {8}', b'Gesendet').
        return entry[1].decode()

    line = entry.decode()
    if not line.strip():
        # Leftover from a literal entry; the name was already read above.
        return None

    match = _LIST_ENTRY.match(line)
    if match is None:
        raise ImapOperationError(f"Could not parse LIST response entry: {repr(line)}")
    return match["name"].strip().strip('"')


def _fetch_recent(
    credentials: ImapCredentials, folders: Sequence[str], limit: int, transport: Transport
) -> list[bytes]:
    with _session(credentials, transport) as connection:
        return [message for folder in folders for message in _recent_in(connection, folder, limit)]


def _recent_in(connection: ImapConnection, folder: str, limit: int) -> list[bytes]:
    status, _ = connection.select(folder, readonly=True)
    if status != "OK":
        raise ImapOperationError(f"SELECT {repr(folder)} failed: {status}")

    status, data = connection.search(None, "ALL")
    if status != "OK":
        raise ImapOperationError(f"SEARCH in {repr(folder)} failed: {status}")

    message_ids = data[0].split()[-limit:]
    return [_raw_message(connection, message_id.decode()) for message_id in message_ids]


def _raw_message(connection: ImapConnection, message_id: str) -> bytes:
    status, response = connection.fetch(message_id, "(RFC822)")
    if status != "OK":
        raise ImapOperationError(f"FETCH {repr(message_id)} failed: {status}")

    message = response[0]
    if not isinstance(message, tuple):
        raise ImapOperationError(f"Unexpected FETCH response for {repr(message_id)}: {repr(response)}")
    return message[1]
