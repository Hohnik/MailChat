from __future__ import annotations

import email
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message as EmailMessage
from email.utils import parsedate_to_datetime

import nh3

# Drop <img> too: nh3's defaults stop script execution but still allow
# remote image loading, which email tracking pixels rely on.
_SANITIZE_TAGS = nh3.ALLOWED_TAGS - {"img"}


@dataclass(frozen=True)
class ParsedMessage:
    message_id: str | None
    in_reply_to: str | None
    references: str | None
    subject: str | None
    from_header: str | None
    to_header: str | None
    cc_header: str | None
    date: datetime | None
    body: str


def parse(raw_message: bytes) -> ParsedMessage:
    message = email.message_from_bytes(raw_message)
    return ParsedMessage(
        message_id=message.get("Message-ID"),
        in_reply_to=message.get("In-Reply-To"),
        references=message.get("References"),
        subject=_decode(message.get("Subject")),
        from_header=_decode(message.get("From")),
        to_header=_decode(message.get("To")),
        cc_header=_decode(message.get("Cc")),
        date=_parse_date(message.get("Date")),
        body=_extract_body(message),
    )


def _decode(header_value: str | None) -> str | None:
    if header_value is None:
        return None
    parts = decode_header(header_value)
    return "".join(
        part.decode(encoding or "utf-8", errors="replace") if isinstance(part, bytes) else part
        for part, encoding in parts
    )


def _parse_date(date_header: str | None) -> datetime | None:
    """When the message was sent, in UTC.

    Senders date their mail in their own zone, and what MailChat stores has to
    be comparable across them — a conversation is read in the order things were
    said, not in the order of the wall clocks they were said by. A header naming
    no zone (or `-0000`, which means the sender wouldn't say) is read as UTC:
    a guess, but the only one that keeps it comparable with the rest.
    """
    if date_header is None:
        return None
    try:
        sent_at = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return None

    if sent_at.tzinfo is None:
        return sent_at.replace(tzinfo=timezone.utc)
    return sent_at.astimezone(timezone.utc)


def _extract_body(message: EmailMessage) -> str:
    plain_part = _find_part(message, "text/plain")
    if plain_part is not None:
        return _decode_payload(plain_part)

    html_part = _find_part(message, "text/html")
    if html_part is not None:
        return nh3.clean(_decode_payload(html_part), tags=_SANITIZE_TAGS)

    return ""


def _find_part(message: EmailMessage, content_type: str) -> EmailMessage | None:
    for part in message.walk():
        if part.get_content_type() == content_type and part.get_content_disposition() != "attachment":
            return part
    return None


def _decode_payload(part: EmailMessage) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")
