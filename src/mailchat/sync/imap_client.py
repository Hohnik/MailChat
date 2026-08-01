from __future__ import annotations

import imaplib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class ImapCredentials:
    host: str
    port: int
    username: str
    password: str


@contextmanager
def connect(credentials: ImapCredentials) -> Iterator[imaplib.IMAP4_SSL]:
    connection = imaplib.IMAP4_SSL(credentials.host, credentials.port)
    connection.login(credentials.username, credentials.password)
    try:
        yield connection
    finally:
        connection.logout()


_LIST_ENTRY = re.compile(r'^\([^)]*\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$')


def list_folders(connection: imaplib.IMAP4_SSL) -> list[str]:
    status, folders = connection.list()
    if status != "OK":
        raise RuntimeError(f"LIST failed: {status}")
    names = (_folder_name(folder) for folder in folders if folder is not None)
    return [name for name in names if name is not None]


def _folder_name(entry: bytes | tuple[bytes, bytes]) -> str | None:
    """Pull the mailbox name out of one `(flags) delimiter name` LIST entry.

    Names come back exactly as the server sends them (IMAP modified UTF-7 for
    non-ASCII), which is the form SELECT expects to get back.
    """
    if isinstance(entry, tuple):
        # The server sent the name as a literal: (b'(\\HasNoChildren) "/" {8}', b'Gesendet').
        return entry[1].decode()

    line = entry.decode()
    if not line.strip():
        # Leftover from a literal entry; the name was already read above.
        return None

    match = _LIST_ENTRY.match(line)
    if match is None:
        raise RuntimeError(f"Could not parse LIST response entry: {repr(line)}")
    return match["name"].strip().strip('"')


def fetch_recent_messages(connection: imaplib.IMAP4_SSL, folder: str = "INBOX", limit: int = 10) -> list[bytes]:
    status, _ = connection.select(folder, readonly=True)
    if status != "OK":
        raise RuntimeError(f"SELECT {repr(folder)} failed: {status}")

    status, data = connection.search(None, "ALL")
    if status != "OK":
        raise RuntimeError(f"SEARCH failed: {status}")

    message_ids = data[0].split()[-limit:]
    return [_fetch_raw_message(connection, message_id) for message_id in message_ids]


def _fetch_raw_message(connection: imaplib.IMAP4_SSL, message_id: bytes) -> bytes:
    status, message_data = connection.fetch(cast(str, message_id), "(RFC822)")
    if status != "OK":
        raise RuntimeError(f"FETCH {repr(message_id)} failed: {status}")
    message = message_data[0]
    if not isinstance(message, tuple):
        raise RuntimeError(f"Unexpected FETCH response for {repr(message_id)}: {repr(message_data)}")
    return message[1]
