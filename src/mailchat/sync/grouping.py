"""Which conversation a message belongs in.

Two questions, answered here and nowhere else: who the message is with, and
what it is about. Headers go in, a `Grouping` comes out — no database, no
session, nothing stored — so the rule can be read and tested on its own.

`Message-ID`, `In-Reply-To` and `References` are stored on every message and
consulted by none of this. Mail clients disagree about them too often to hang a
conversation on, and what the user recognises is the person and the subject.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from email.utils import getaddresses

from mailchat.accounts.folders import is_inbox
from mailchat.accounts.models import Account
from mailchat.messages.models import INBOUND, OUTBOUND, Direction
from mailchat.sync.parser import ParsedMessage

ME = "me@mailchat.local"
"""The contact mail the user exchanged with nobody but themselves groups under.

Not a real address, and never sent to: it exists so that a note forwarded
between two of the user's own accounts has somewhere to land instead of being
dropped for having no other correspondent.
"""

ME_DISPLAY_NAME = "Me"

_MARKER = re.compile(r"\b(?:re|aw|fwd|fw|wg)\s*:", re.IGNORECASE)
"""A reply or forward marker, in the four languages of mail clients this app meets.

Unanchored on purpose: a ticketing system that prefixes its own id leaves the
marker in the middle of the subject, and a strip that only ran at the start
would file every one of those replies as a conversation of its own.
"""


@dataclass(frozen=True)
class Grouping:
    """Where one message belongs: who it is with, and what it is about."""

    address: str
    display_name: str | None
    normalized_subject: str


def direction_of(account: Account, folder: str) -> Direction:
    """Which way the mail in this folder was going, for this account.

    Read from where the server filed the message rather than from its headers:
    the account that sent a message is the one whose Sent folder holds it, and
    no amount of reading `From` proves that. An account whose sent mail lands in
    its inbox has no folder that means outbound, so its mail reads as inbound —
    the same folder can't answer both ways, and inbound is what the user sees.

    Which folders are worth reading is `accounts/folders.py`'s question; this is
    what a message found in one of them turns out to be, which is a fact about
    the message, so it lives here beside the rest of what grouping decides.
    """
    sent_folder = account.sent_folder
    if sent_folder is None or is_inbox(folder):
        return INBOUND
    return OUTBOUND if folder == sent_folder else INBOUND


def normalize_subject(subject: str | None) -> str:
    """The subject with every reply and forward marker taken out of it.

    What is left is a conversation key, not something to show anyone — the
    message keeps its subject exactly as it arrived. Running this on its own
    output changes nothing, which is what lets one thread's four spellings of
    the same subject meet in one place however many hands they passed through.
    """
    return " ".join(_MARKER.sub(" ", subject or "").split())


def group(
    parsed: ParsedMessage, *, direction: Direction, account_addresses: Collection[str]
) -> Grouping:
    """The conversation this message belongs in, by the header its direction names.

    Inbound mail is with whoever sent it, outbound mail with whoever it went to.
    `Cc` is never asked: someone looped into a thread halfway through — or
    dropped out of it — is on the message, and moving the conversation because
    of them would split it in two.
    """
    header = parsed.from_header if direction == INBOUND else parsed.to_header
    address, display_name = _correspondent(header, account_addresses)
    return Grouping(
        address=address,
        display_name=display_name,
        normalized_subject=normalize_subject(parsed.subject),
    )


def _correspondent(header: str | None, account_addresses: Collection[str]) -> tuple[str, str | None]:
    """The first address in the header that isn't one of the user's own.

    A header can carry several — a mail to two people, or one addressed to the
    user and a colleague. The first one left after their own accounts are taken
    out is the correspondent: the user is never their own conversation partner,
    and a second recipient is a fact about the message rather than a second
    conversation to file it under.
    """
    connected = {address.lower() for address in account_addresses}

    for display_name, address in getaddresses([header or ""]):
        lowered = address.lower()
        if lowered and lowered not in connected:
            return lowered, display_name or None

    return ME, ME_DISPLAY_NAME
