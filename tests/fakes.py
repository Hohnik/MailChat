from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

from mailchat.mail.imap import ImapCredentials, ImapError


@dataclass
class FakeImap:
    """Stands in for `mailchat.mail.imap` wherever a caller takes an `Imap`.

    Seed `mailboxes` with the folders the server offers and the raw messages in
    each. `errors` maps an address to the error every call for that account
    raises — enough to make one account fail while the others keep working.
    `folders_error` refuses the listing for every account, the way a server that
    accepts the login but won't LIST does.
    """

    mailboxes: dict[str, list[bytes]] = field(default_factory=dict)
    errors: dict[str, ImapError] = field(default_factory=dict)
    folders_error: ImapError | None = None
    delay_seconds: float = 0.0
    seen: list[ImapCredentials] = field(default_factory=list)
    """The credentials of every call so far, in order."""

    def offer(self, *folders: str) -> FakeImap:
        """Seed empty folders, for callers that only care about the listing."""
        self.mailboxes = {folder: [] for folder in folders}
        return self

    async def folders(self, credentials: ImapCredentials) -> list[str]:
        await self._connect(credentials)
        if self.folders_error is not None:
            raise self.folders_error
        return list(self.mailboxes)

    async def fetch(
        self, credentials: ImapCredentials, folders: Sequence[str], limit: int = 10
    ) -> list[bytes]:
        await self._connect(credentials)
        return [message for folder in folders for message in self.mailboxes.get(folder, [])[-limit:]]

    async def _connect(self, credentials: ImapCredentials) -> None:
        self.seen.append(credentials)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        error = self.errors.get(credentials.username)
        if error is not None:
            raise error
