from __future__ import annotations

from datetime import datetime, timezone

from mailchat.accounts import repository as accounts_repository
from mailchat.conversations.models import Contact, Conversation
from mailchat.messages.models import INBOUND, OUTBOUND, Message
from mailchat.shared.security import encrypt


async def _account(session, address: str = "kunde@example.com"):
    return await accounts_repository.create_account(
        session,
        provider="generic",
        address=address,
        imap_host="imap.example.com",
        imap_port=993,
        smtp_host="smtp.example.com",
        smtp_port=465,
        encrypted_password=encrypt("app-specific-secret"),
    )


async def _conversation(session, *, address: str, display_name: str, subject: str) -> Conversation:
    contact = Contact(address=address, display_name=display_name)
    conversation = Conversation(contact=contact, normalized_subject=subject)
    session.add(conversation)
    await session.flush()
    return conversation


def _message(
    conversation: Conversation,
    account_id: int,
    *,
    subject: str = "Anfrage",
    body: str = "body",
    direction: str = INBOUND,
    is_read: bool = True,
    day: int = 1,
) -> Message:
    return Message(
        account_id=account_id,
        conversation_id=conversation.id,
        message_id=f"<{subject}-{day}-{direction}@example.com>",
        subject=subject,
        from_header="service@louis.de",
        to_header="kunde@example.com",
        body=body,
        date=datetime(2026, 7, day, 12, 0, tzinfo=timezone.utc),
        direction=direction,
        is_read=is_read,
        imap_uid=day,
        imap_folder="INBOX",
        imap_uidvalidity=1,
    )


async def _seed_louis_thread(session_factory) -> Conversation:
    async with session_factory() as session:
        account = await _account(session)
        conversation = await _conversation(
            session,
            address="service@louis.de",
            display_name="Louis Service",
            subject="[DL-4916597] Ihre Anfrage an Louis",
        )
        session.add_all(
            [
                _message(conversation, account.id, body="Ihre Anfrage ist eingegangen", day=1),
                _message(
                    conversation,
                    account.id,
                    body="Vielen Dank, bitte senden",
                    direction=OUTBOUND,
                    day=2,
                ),
                _message(conversation, account.id, body="Der Artikel ist unterwegs", day=3),
            ]
        )
        await session.commit()
        return conversation


async def test_the_conversation_list_says_who_each_conversation_is_with(session_factory, client):
    await _seed_louis_thread(session_factory)

    response = client.get("/conversations")

    assert response.status_code == 200
    assert "Louis Service" in response.text
    assert "[DL-4916597] Ihre Anfrage an Louis" in response.text


async def test_the_conversation_list_says_when_there_is_nothing_to_show(session_factory, client):
    response = client.get("/conversations")

    assert response.status_code == 200
    assert "No conversations yet." in response.text


async def test_the_conversation_list_counts_only_unread_mail_the_user_received(
    session_factory, client
):
    async with session_factory() as session:
        account = await _account(session)
        conversation = await _conversation(
            session, address="service@louis.de", display_name="Louis", subject="Anfrage"
        )
        session.add_all(
            [
                _message(conversation, account.id, is_read=False, day=1),
                _message(conversation, account.id, is_read=False, day=2),
                _message(conversation, account.id, is_read=True, day=3),
                # A reply the user wrote, which their server never flagged read.
                # It is waiting for nobody, and must not badge the conversation.
                _message(conversation, account.id, direction=OUTBOUND, is_read=False, day=4),
            ]
        )
        await session.commit()

    response = client.get("/conversations/list")

    assert '<span class="unread-count">2</span>' in response.text


async def test_a_conversation_with_nothing_waiting_carries_no_count(session_factory, client):
    async with session_factory() as session:
        account = await _account(session)
        conversation = await _conversation(
            session, address="service@louis.de", display_name="Louis", subject="Anfrage"
        )
        session.add(_message(conversation, account.id, is_read=True))
        await session.commit()

    response = client.get("/conversations/list")

    assert "unread-count" not in response.text


async def test_the_conversation_list_puts_the_latest_conversation_first(session_factory, client):
    async with session_factory() as session:
        account = await _account(session)
        older = await _conversation(
            session, address="service@louis.de", display_name="Louis", subject="Bestellung"
        )
        newer = await _conversation(
            session, address="j.horbach@horbach-beratung.de", display_name="Jens", subject="Vorsorge"
        )
        session.add_all(
            [
                _message(older, account.id, subject="Bestellung", day=1),
                _message(newer, account.id, subject="Vorsorge", day=9),
            ]
        )
        await session.commit()

    response = client.get("/conversations/list")

    assert response.text.index("Vorsorge") < response.text.index("Bestellung")


async def test_the_conversation_list_refreshes_itself(session_factory, client):
    await _seed_louis_thread(session_factory)

    page = client.get("/conversations")
    fragment = client.get("/conversations/list")

    assert 'hx-get="/conversations/list"' in page.text
    assert "<html" not in fragment.text
    assert "Louis Service" in fragment.text


async def test_a_thread_reads_in_the_order_it_was_said(session_factory, client):
    conversation = await _seed_louis_thread(session_factory)

    response = client.get(f"/conversations/{conversation.id}")

    assert response.status_code == 200
    assert (
        response.text.index("Ihre Anfrage ist eingegangen")
        < response.text.index("Vielen Dank, bitte senden")
        < response.text.index("Der Artikel ist unterwegs")
    )


async def test_a_thread_shows_which_side_said_what(session_factory, client):
    conversation = await _seed_louis_thread(session_factory)

    response = client.get(f"/conversations/{conversation.id}/thread")

    assert response.text.count('class="message inbound"') == 2
    assert response.text.count('class="message outbound"') == 1
    assert "<html" not in response.text


async def test_a_thread_refreshes_itself(session_factory, client):
    conversation = await _seed_louis_thread(session_factory)

    response = client.get(f"/conversations/{conversation.id}")

    assert f'hx-get="/conversations/{conversation.id}/thread"' in response.text


async def test_a_thread_page_404s_for_a_conversation_that_is_not_there(client):
    response = client.get("/conversations/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


async def test_a_thread_fragment_404s_for_a_conversation_that_is_not_there(client):
    response = client.get("/conversations/999/thread")

    assert response.status_code == 404


async def test_the_accounts_page_leads_to_the_conversations(client):
    response = client.get("/accounts")

    assert 'href="/conversations"' in response.text
