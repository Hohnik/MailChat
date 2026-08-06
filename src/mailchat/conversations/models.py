from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mailchat.shared.db import Base


class Contact(Base):
    """One person MailChat has mail from or to, known by one address.

    The address is the identity, lowercased so a server that shouts it and a
    server that whispers it are the same person. Two addresses belonging to one
    human stay two contacts: merging them would need a judgement MailChat has no
    way to make, and a wrong merge is a conversation with the wrong person in
    it. The display name is whatever the last message to name them called them.
    """

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    address: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str | None] = mapped_column(String, default=None)


class Conversation(Base):
    """One contact, one subject: everything said between you on that topic.

    No account column, deliberately — the same contact reaching two of the
    user's mailboxes is one conversation, because it is one conversation to
    them. No read column either: a conversation is unread when its messages are,
    and asking the messages is the only way that answer can't drift from them.

    Contact and subject are spelled out as a key here, as the address is on
    `Contact`. What keeps two concurrent syncs from racing to create the same
    conversation is the lock in `conversations/service.py`, not this; the key is
    here so that a lapse in that shows up as a refused write to fix rather than
    a second half-conversation nobody notices.
    """

    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("contact_id", "normalized_subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    normalized_subject: Mapped[str] = mapped_column(String)

    contact: Mapped[Contact] = relationship(lazy="joined")
