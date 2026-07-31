from __future__ import annotations

from htpy import Node, a, div, h1, li, p, span, ul

from mailchat.accounts.models import Account
from mailchat.messages.models import Message


def message_row(message: Message) -> Node:
    return li[
        span(class_="from")[message.from_header or "(unknown sender)"],
        span(class_="subject")[message.subject or "(no subject)"],
        span(class_="date")[message.date.isoformat() if message.date else ""],
    ]


def message_list(messages: list[Message]) -> Node:
    if not messages:
        return ul(id="message-list")[p["No messages synced yet."]]

    return ul(id="message-list")[[message_row(message) for message in messages]]


def messages_section(account: Account, messages: list[Message]) -> Node:
    return div(
        id="message-list-container",
        hx_get=f"/accounts/{account.id}/messages/list",
        hx_trigger="every 10s",
        hx_swap="innerHTML",
    )[message_list(messages)]


def messages_page(account: Account, messages: list[Message]) -> Node:
    return div[
        a(href="/accounts")["← Back to accounts"],
        h1[f"Messages — {account.address}"],
        messages_section(account, messages),
    ]
