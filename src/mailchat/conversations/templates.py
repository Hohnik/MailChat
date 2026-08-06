from __future__ import annotations

from datetime import datetime

from htpy import Node, a, div, h1, li, p, span, ul

from mailchat.conversations.models import Contact, Conversation
from mailchat.conversations.service import ConversationSummary
from mailchat.messages.models import OUTBOUND, Message

NO_SUBJECT = "(no subject)"
"""What a conversation with nothing in the subject line is called on the page."""


def name_of(contact: Contact) -> str:
    """What to call someone: their name if a message ever gave one, else their address."""
    return contact.display_name or contact.address


def _subject_of(conversation: Conversation) -> str:
    return conversation.normalized_subject or NO_SUBJECT


def _when(moment: datetime | None) -> str:
    return moment.isoformat() if moment else ""


def conversation_row(summary: ConversationSummary) -> Node:
    conversation = summary.conversation
    return li(class_="conversation")[
        a(href=f"/conversations/{conversation.id}")[
            span(class_="contact")[name_of(conversation.contact)],
            span(class_="subject")[_subject_of(conversation)],
            span(class_="date")[_when(summary.last_message_at)],
            # Only mail that came in can be waiting for the user, so a
            # conversation they have caught up on shows nothing at all.
            span(class_="unread-count")[str(summary.unread_count)]
            if summary.unread_count
            else None,
        ]
    ]


def conversation_list(summaries: list[ConversationSummary]) -> Node:
    if not summaries:
        return ul(id="conversation-list")[p["No conversations yet."]]

    return ul(id="conversation-list")[[conversation_row(summary) for summary in summaries]]


def conversations_section(summaries: list[ConversationSummary]) -> Node:
    return div(
        id="conversation-list-container",
        hx_get="/conversations/list",
        hx_trigger="every 10s",
        hx_swap="innerHTML",
    )[conversation_list(summaries)]


def conversations_page(summaries: list[ConversationSummary]) -> Node:
    return div[
        a(href="/accounts")["← Back to accounts"],
        h1["Conversations"],
        conversations_section(summaries),
    ]


def message_row(conversation: Conversation, message: Message) -> Node:
    """One thing said, on the side of the thread that said it."""
    outbound = message.direction == OUTBOUND
    return li(class_=f"message {message.direction}")[
        span(class_="author")["You" if outbound else name_of(conversation.contact)],
        span(class_="date")[_when(message.date)],
        span(class_="subject")[message.subject or NO_SUBJECT],
        p(class_="body")[message.body],
    ]


def thread(conversation: Conversation, messages: list[Message]) -> Node:
    if not messages:
        return ul(id="thread")[p["Nothing in this conversation yet."]]

    return ul(id="thread")[[message_row(conversation, message) for message in messages]]


def thread_section(conversation: Conversation, messages: list[Message]) -> Node:
    return div(
        id="thread-container",
        hx_get=f"/conversations/{conversation.id}/thread",
        hx_trigger="every 10s",
        hx_swap="innerHTML",
    )[thread(conversation, messages)]


def conversation_page(conversation: Conversation, messages: list[Message]) -> Node:
    return div[
        a(href="/conversations")["← Back to conversations"],
        h1[name_of(conversation.contact)],
        p(class_="subject")[_subject_of(conversation)],
        thread_section(conversation, messages),
    ]
