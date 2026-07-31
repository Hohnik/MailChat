from __future__ import annotations

import smtplib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass(frozen=True)
class SmtpCredentials:
    host: str
    port: int
    username: str
    password: str


@contextmanager
def connect(credentials: SmtpCredentials) -> Iterator[smtplib.SMTP]:
    connection = smtplib.SMTP_SSL(credentials.host, credentials.port)
    connection.login(credentials.username, credentials.password)
    try:
        yield connection
    finally:
        connection.quit()


def send_message(connection: smtplib.SMTP, sender: str, recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)
    connection.send_message(message)
