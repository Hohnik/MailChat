from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from mailchat.sync.parser import parse

FIXTURES = Path(__file__).parent.parent / "fixtures" / "emails"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parses_headers_from_simple_plain_text_message():
    parsed = parse(_load("simple_text_plain.eml"))

    assert parsed.subject == "MailChat SMTP proof of concept"
    assert parsed.from_header == "niklas-hohn@t-online.de"
    assert parsed.to_header == "niklas-hohn@t-online.de"
    assert parsed.message_id == "<1wplXp-3LEpFI0@fwd78.t-online.de>"
    assert parsed.in_reply_to is None
    assert parsed.references is None
    assert parsed.date == datetime(2026, 7, 31, 13, 36, 53, tzinfo=timezone(timedelta(hours=2)))
    assert "This is a test email sent by MailChat SMTP proof of concept" in parsed.body


def test_parses_cc_in_reply_to_and_references():
    parsed = parse(_load("reply_with_cc.eml"))

    assert parsed.subject == "Re: Terminanfrage"
    assert parsed.cc_header == "Kollege <kollege@beispiel-service.de>"
    assert parsed.in_reply_to == "<original-1111@example.com>"
    assert parsed.references == "<original-1111@example.com>"
    assert "Vielen Dank" in parsed.body


def test_sanitizes_html_body_stripping_scripts_and_event_handlers():
    parsed = parse(_load("html_with_script.eml"))

    assert "<script>" not in parsed.body
    assert "alert(" not in parsed.body
    assert "onerror" not in parsed.body
    assert "javascript:" not in parsed.body
    assert "<img" not in parsed.body
    assert "tracker.example.com" not in parsed.body
    assert "versandt" in parsed.body
    assert "Sendung verfolgen" in parsed.body
