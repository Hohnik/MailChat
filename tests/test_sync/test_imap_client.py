from unittest.mock import MagicMock, patch

from mailchat.sync.imap_client import ImapCredentials, connect, fetch_recent_messages, list_folders

CREDENTIALS = ImapCredentials(
    host="secureimap.t-online.de", port=993, username="user@t-online.de", password="secret"
)


@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
def test_connect_logs_in_and_logs_out(mock_imap_ssl):
    mock_connection = mock_imap_ssl.return_value

    with connect(CREDENTIALS) as connection:
        assert connection is mock_connection

    mock_imap_ssl.assert_called_once_with("secureimap.t-online.de", 993)
    mock_connection.login.assert_called_once_with("user@t-online.de", "secret")
    mock_connection.logout.assert_called_once()


@patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL")
def test_connect_logs_out_even_if_body_raises(mock_imap_ssl):
    mock_connection = mock_imap_ssl.return_value

    with patch("mailchat.sync.imap_client.imaplib.IMAP4_SSL", mock_imap_ssl):
        try:
            with connect(CREDENTIALS):
                raise ValueError("boom")
        except ValueError:
            pass

    mock_connection.logout.assert_called_once()


def test_list_folders_decodes_bytes():
    connection = MagicMock()
    connection.list.return_value = ("OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Sent"'])

    folders = list_folders(connection)

    assert folders == ['(\\HasNoChildren) "/" "INBOX"', '(\\HasNoChildren) "/" "Sent"']


def test_list_folders_raises_on_non_ok_status():
    connection = MagicMock()
    connection.list.return_value = ("NO", [])

    try:
        list_folders(connection)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_fetch_recent_messages_selects_readonly_and_fetches_by_id():
    connection = MagicMock()
    connection.select.return_value = ("OK", [b"8"])
    connection.search.return_value = ("OK", [b"1 2 3 4 5"])
    connection.fetch.return_value = ("OK", [(b"1 (RFC822 {10}", b"raw message bytes")])

    messages = fetch_recent_messages(connection, folder="INBOX", limit=2)

    connection.select.assert_called_once_with("INBOX", readonly=True)
    connection.search.assert_called_once_with(None, "ALL")
    assert connection.fetch.call_count == 2
    connection.fetch.assert_any_call(b"4", "(RFC822)")
    connection.fetch.assert_any_call(b"5", "(RFC822)")
    assert messages == [b"raw message bytes", b"raw message bytes"]


def test_fetch_recent_messages_raises_on_select_failure():
    connection = MagicMock()
    connection.select.return_value = ("NO", [b"folder does not exist"])

    try:
        fetch_recent_messages(connection, folder="Missing")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
