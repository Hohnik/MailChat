from __future__ import annotations

from mailchat.mail import imap
from mailchat.mail.imap import Imap


def get_imap() -> Imap:
    """FastAPI dependency: the IMAP module the request handlers reach mail through.

    Production always gets the real module; route tests override it with a fake.
    """
    return imap
