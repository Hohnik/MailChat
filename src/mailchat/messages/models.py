from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mailchat.accounts.models import Account
from mailchat.conversations.models import Conversation
from mailchat.shared.db import Base

Direction = Literal["inbound", "outbound"]
"""Which way a message was going: mail that reached the user, or mail they sent."""

INBOUND: Direction = "inbound"
OUTBOUND: Direction = "outbound"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    message_id: Mapped[str | None] = mapped_column(String)
    in_reply_to: Mapped[str | None] = mapped_column(String)
    references: Mapped[str | None] = mapped_column(String)
    subject: Mapped[str | None] = mapped_column(String)
    from_header: Mapped[str | None] = mapped_column(String)
    to_header: Mapped[str | None] = mapped_column(String)
    cc_header: Mapped[str | None] = mapped_column(String)
    date: Mapped[datetime | None] = mapped_column()
    body: Mapped[str] = mapped_column(Text)
    # Read from the folder the message was fetched from rather than from its
    # headers, so a message the user sent is one the server filed as sent.
    direction: Mapped[str] = mapped_column(String)
    # A cache of the server's `\Seen` flag, refreshed by every poll that reaches
    # this message. The three columns under it are what a flag written back has
    # to be addressed to: a UID means nothing without its folder, and nothing at
    # all if the folder's UIDVALIDITY has moved on since.
    is_read: Mapped[bool] = mapped_column(default=False)
    imap_uid: Mapped[int] = mapped_column()
    imap_folder: Mapped[str] = mapped_column(String)
    imap_uidvalidity: Mapped[int] = mapped_column()
    fetched_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    account: Mapped[Account] = relationship()
    conversation: Mapped[Conversation] = relationship()
