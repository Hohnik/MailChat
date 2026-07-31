from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mailchat.accounts.models import Account
from mailchat.shared.db import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    message_id: Mapped[str | None] = mapped_column(String)
    in_reply_to: Mapped[str | None] = mapped_column(String)
    references: Mapped[str | None] = mapped_column(String)
    subject: Mapped[str | None] = mapped_column(String)
    from_header: Mapped[str | None] = mapped_column(String)
    to_header: Mapped[str | None] = mapped_column(String)
    cc_header: Mapped[str | None] = mapped_column(String)
    date: Mapped[datetime | None] = mapped_column()
    body: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    account: Mapped[Account] = relationship()
