from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mailchat.shared.db import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String)
    address: Mapped[str] = mapped_column(String, unique=True)
    imap_host: Mapped[str] = mapped_column(String)
    imap_port: Mapped[int] = mapped_column()
    smtp_host: Mapped[str] = mapped_column(String)
    smtp_port: Mapped[int] = mapped_column()
    # Which IMAP folder holds this account's sent mail. Only the user can say —
    # server folder names vary — so it stays unset until they pick one.
    sent_folder: Mapped[str | None] = mapped_column(String, default=None)
    connected_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    credentials: Mapped[Credentials] = relationship(
        back_populates="account", uselist=False, cascade="all, delete-orphan"
    )


class Credentials(Base):
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True)
    encrypted_password: Mapped[str] = mapped_column(String)

    account: Mapped[Account] = relationship(back_populates="credentials")
