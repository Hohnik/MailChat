from __future__ import annotations

from mailchat.mail import imap, smtp
from mailchat.mail.imap import Imap
from mailchat.mail.smtp import Smtp


def get_imap() -> Imap:
    """FastAPI dependency: the IMAP module the request handlers reach mail through.

    Production always gets the real module; route tests override it with a fake.
    """
    return imap


def get_smtp() -> Smtp:
    """FastAPI dependency: the SMTP module the request handlers reach mail through.

    Production always gets the real module; route tests override it with a fake.
    """
    return smtp
