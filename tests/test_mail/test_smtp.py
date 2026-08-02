from __future__ import annotations

import asyncio
import time
from email.message import EmailMessage

import pytest

from mailchat.mail.smtp import SmtpCredentials, SmtpLoginError, SmtpOperationError, send, verify

CREDENTIALS = SmtpCredentials(
    host="securesmtp.t-online.de", port=465, username="user@t-online.de", password="secret"
)


class StubConnection:
    """A tiny SMTP server: it accepts logins and messages, or refuses on cue."""

    def __init__(
        self,
        *,
        login_error: Exception | None = None,
        send_error: Exception | None = None,
        quit_error: Exception | None = None,
        login_delay_seconds: float = 0.0,
    ) -> None:
        self.login_error = login_error
        self.send_error = send_error
        self.quit_error = quit_error
        self.login_delay_seconds = login_delay_seconds

        self.logins: list[tuple[str, str]] = []
        self.quits = 0
        self.sent: list[EmailMessage] = []

    def login(self, user: str, password: str) -> None:
        if self.login_delay_seconds:
            time.sleep(self.login_delay_seconds)
        if self.login_error is not None:
            raise self.login_error
        self.logins.append((user, password))

    def send_message(self, message: EmailMessage) -> dict[str, tuple[int, bytes]]:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(message)
        return {}

    def quit(self) -> None:
        self.quits += 1
        if self.quit_error is not None:
            raise self.quit_error


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


async def test_verify_logs_in_at_the_credentials_address_and_quits():
    connection = StubConnection()
    transport = StubTransport(connection)

    await verify(CREDENTIALS, transport=transport)

    assert transport.opened == [("securesmtp.t-online.de", 465)]
    assert connection.logins == [("user@t-online.de", "secret")]
    assert connection.quits == 1


async def test_verify_raises_a_login_error_when_the_server_cannot_be_reached():
    connection = StubConnection()

    with pytest.raises(SmtpLoginError):
        await verify(CREDENTIALS, transport=StubTransport(connection, connect_error=OSError("no route to host")))


async def test_verify_raises_a_login_error_when_the_server_refuses_the_password():
    connection = StubConnection(login_error=OSError("authentication failed"))

    with pytest.raises(SmtpLoginError):
        await verify(CREDENTIALS, transport=StubTransport(connection))


async def test_a_refused_login_does_not_leave_the_connection_open():
    connection = StubConnection(login_error=OSError("authentication failed"))

    with pytest.raises(SmtpLoginError):
        await verify(CREDENTIALS, transport=StubTransport(connection))

    assert connection.quits == 1


async def test_send_hands_the_server_a_message_addressed_as_asked():
    connection = StubConnection()

    await send(
        CREDENTIALS,
        sender="user@t-online.de",
        recipient="friend@example.com",
        subject="Test subject",
        body="Test body",
        transport=StubTransport(connection),
    )

    (sent,) = connection.sent
    assert sent["Subject"] == "Test subject"
    assert sent["From"] == "user@t-online.de"
    assert sent["To"] == "friend@example.com"
    assert sent.get_content().strip() == "Test body"


async def test_send_raises_an_operation_error_when_the_server_refuses_the_message():
    connection = StubConnection(send_error=OSError("550 recipient refused"))

    with pytest.raises(SmtpOperationError):
        await _send_test_message(StubTransport(connection))


async def test_send_quits_when_the_operation_fails():
    connection = StubConnection(send_error=OSError("550 recipient refused"))

    with pytest.raises(SmtpOperationError):
        await _send_test_message(StubTransport(connection))

    assert connection.quits == 1


async def test_a_failing_quit_does_not_hide_the_operation_that_failed():
    connection = StubConnection(
        send_error=OSError("550 recipient refused"),
        quit_error=OSError("connection reset"),
    )

    with pytest.raises(SmtpOperationError):
        await _send_test_message(StubTransport(connection))


async def test_a_failing_quit_does_not_fail_a_send_the_server_accepted():
    connection = StubConnection(quit_error=OSError("connection reset"))

    await _send_test_message(StubTransport(connection))

    assert len(connection.sent) == 1


async def test_verify_leaves_the_event_loop_free_while_the_server_is_slow():
    delay_seconds = 0.3
    connections = [StubConnection(login_delay_seconds=delay_seconds) for _ in range(2)]

    start = time.monotonic()
    await asyncio.gather(
        *(verify(CREDENTIALS, transport=StubTransport(connection)) for connection in connections)
    )
    elapsed = time.monotonic() - start

    # Blocking smtplib calls run in threads; on the event loop these would queue
    # up and take ~2x delay_seconds instead.
    assert elapsed < delay_seconds * 1.5


async def _send_test_message(transport: StubTransport) -> None:
    await send(
        CREDENTIALS,
        sender="user@t-online.de",
        recipient="friend@example.com",
        subject="Test subject",
        body="Test body",
        transport=transport,
    )
