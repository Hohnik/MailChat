"""Everything the app knows about sending mail over SMTP.

Callers hand over credentials and get a verdict back. This module owns the
connection's lifetime, the message format, and the thread that keeps blocking
smtplib calls off the event loop — none of which is visible from outside.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpCredentials:
    host: str
    port: int
    username: str
    password: str


class SmtpError(Exception):
    """Base for everything this module raises; nothing else escapes it."""


class SmtpLoginError(SmtpError):
    """The server couldn't be reached, or wouldn't accept these credentials.

    Fatal: there is no session, so nothing else will work either.
    """


class SmtpOperationError(SmtpError):
    """The login worked, but the message after it wasn't accepted.

    Survivable: the account's login is still good, so callers may choose to
    carry on and try the message again later.
    """


class SmtpConnection(Protocol):
    """The slice of `smtplib.SMTP_SSL` this module uses."""

    def login(self, user: str, password: str) -> Any: ...
    # Positional-only: smtplib calls this parameter `msg`.
    def send_message(self, message: EmailMessage, /) -> Any: ...
    def quit(self) -> Any: ...


Transport = Callable[[str, int], SmtpConnection]
"""Opens a connection to a host and port — `smtplib.SMTP_SSL`, or a stub in this module's tests."""


class Smtp(Protocol):
    """What this module looks like to its callers.

    Callers type their dependency as this protocol and default it to the module
    itself, so their tests pass a fake in rather than patching.
    """

    async def verify(self, credentials: SmtpCredentials) -> None: ...

    async def send(
        self, credentials: SmtpCredentials, sender: str, recipient: str, subject: str, body: str
    ) -> None: ...


async def verify(credentials: SmtpCredentials, *, transport: Transport = smtplib.SMTP_SSL) -> None:
    """Prove that the server accepts this login. Raises if it doesn't."""
    await asyncio.to_thread(_log_in_and_out, credentials, transport)


async def send(
    credentials: SmtpCredentials,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    *,
    transport: Transport = smtplib.SMTP_SSL,
) -> None:
    """Send one plain-text message from `sender` to `recipient`."""
    await asyncio.to_thread(_send_message, credentials, sender, recipient, subject, body, transport)


@contextmanager
def _session(credentials: SmtpCredentials, transport: Transport) -> Iterator[SmtpConnection]:
    """A logged-in connection that always quits again, however it ends.

    Once the connection is open it is quit even if the login itself is refused,
    so a rejected password doesn't leave a socket behind.
    """
    try:
        connection = transport(credentials.host, credentials.port)
    except Exception as error:
        raise SmtpLoginError(f"Could not reach {credentials.host}: {error}") from error

    try:
        try:
            connection.login(credentials.username, credentials.password)
        except Exception as error:
            raise SmtpLoginError(
                f"Could not log in to {credentials.host} as {credentials.username}: {error}"
            ) from error

        yield connection
    finally:
        try:
            connection.quit()
        except Exception:
            # A quit that fails must not replace the error we're carrying out,
            # nor undo a message the server already accepted.
            logger.warning("SMTP quit failed for %s", credentials.username, exc_info=True)


def _log_in_and_out(credentials: SmtpCredentials, transport: Transport) -> None:
    with _session(credentials, transport):
        pass


def _send_message(
    credentials: SmtpCredentials,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    transport: Transport,
) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    with _session(credentials, transport) as connection:
        try:
            connection.send_message(message)
        except Exception as error:
            raise SmtpOperationError(f"Could not send to {recipient}: {error}") from error
