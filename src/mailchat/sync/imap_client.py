from __future__ import annotations

import imaplib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


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


def list_folders(connection: imaplib.IMAP4_SSL) -> list[str]:
    status, folders = connection.list()
    if status != "OK":
        raise RuntimeError(f"LIST failed: {status}")
    return [folder.decode() if isinstance(folder, bytes) else folder for folder in folders]


def fetch_recent_messages(connection: imaplib.IMAP4_SSL, folder: str = "INBOX", limit: int = 10) -> list[bytes]:
    status, _ = connection.select(folder, readonly=True)
    if status != "OK":
        raise RuntimeError(f"SELECT {folder!r} failed: {status}")

    status, data = connection.search(None, "ALL")
    if status != "OK":
        raise RuntimeError(f"SEARCH failed: {status}")

    message_ids = data[0].split()[-limit:]
    return [_fetch_raw_message(connection, message_id) for message_id in message_ids]


def _fetch_raw_message(connection: imaplib.IMAP4_SSL, message_id: bytes) -> bytes:
    status, message_data = connection.fetch(message_id, "(RFC822)")
    if status != "OK":
        raise RuntimeError(f"FETCH {message_id!r} failed: {status}")
    return message_data[0][1]
