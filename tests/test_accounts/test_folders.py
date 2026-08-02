from __future__ import annotations

from mailchat.accounts.folders import synced_folders
from mailchat.accounts.models import Account


def _account(sent_folder: str | None = None) -> Account:
    """An account holding nothing but the answer's inputs — no credentials, no
    row, no session. Anything that asked the server would need all three, so a
    test that passes this and gets an answer has proved the round-trip is gone.
    """
    return Account(address="user@t-online.de", sent_folder=sent_folder)


def test_an_account_without_a_sent_folder_syncs_the_inbox():
    assert synced_folders(_account()) == ("INBOX",)


def test_a_chosen_sent_folder_is_synced_alongside_the_inbox():
    assert synced_folders(_account("Gesendet")) == ("INBOX", "Gesendet")


def test_the_inbox_is_synced_once_when_the_sent_folder_is_the_inbox():
    # IMAP names the inbox case-insensitively, so a user who picked it as their
    # sent folder syncs one folder — not the same one twice, at twice the cost.
    assert synced_folders(_account("Inbox")) == ("INBOX",)
