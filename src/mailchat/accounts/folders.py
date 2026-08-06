"""Which folders an account syncs.

The one place that question is answered. It reads the account's own row and
nothing else — no server, no session — so a caller deciding what to fetch never
pays for a login to find out what to ask for.
"""

from __future__ import annotations

from mailchat.accounts.models import Account

INBOX = "INBOX"
"""Every account syncs its inbox; IMAP guarantees the name and the folder."""


def is_inbox(folder: str) -> bool:
    """Whether this is the inbox, however loudly the server spells it.

    IMAP matches INBOX case-insensitively and nothing else, so this is the one
    folder name that can arrive in a case a caller didn't store — and the only
    one that may be compared any way but exactly.
    """
    return folder.upper() == INBOX


def synced_folders(account: Account) -> tuple[str, ...]:
    """The folders one pass of sync reads for this account, in fetch order.

    The inbox always, and the account's sent folder once the user has picked
    one — that choice reaches sync from here, so a stored folder can't sit
    unread and a fetch can't quietly default to somewhere else. An account whose
    sent mail lands in the inbox syncs one folder rather than the same one twice.
    """
    sent_folder = account.sent_folder
    if sent_folder is None or is_inbox(sent_folder):
        return (INBOX,)
    return (INBOX, sent_folder)
