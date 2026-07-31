from unittest.mock import MagicMock, patch

from mailchat.sync.smtp_client import SmtpCredentials, connect, send_message

CREDENTIALS = SmtpCredentials(
    host="securesmtp.t-online.de", port=465, username="user@t-online.de", password="secret"
)


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_connect_logs_in_and_quits(mock_smtp_ssl):
    mock_connection = mock_smtp_ssl.return_value

    with connect(CREDENTIALS) as connection:
        assert connection is mock_connection

    mock_smtp_ssl.assert_called_once_with("securesmtp.t-online.de", 465)
    mock_connection.login.assert_called_once_with("user@t-online.de", "secret")
    mock_connection.quit.assert_called_once()


@patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL")
def test_connect_quits_even_if_body_raises(mock_smtp_ssl):
    mock_connection = mock_smtp_ssl.return_value

    with patch("mailchat.sync.smtp_client.smtplib.SMTP_SSL", mock_smtp_ssl):
        try:
            with connect(CREDENTIALS):
                raise ValueError("boom")
        except ValueError:
            pass

    mock_connection.quit.assert_called_once()


def test_send_message_builds_and_sends_email():
    connection = MagicMock()

    send_message(
        connection,
        sender="user@t-online.de",
        recipient="user@t-online.de",
        subject="Test subject",
        body="Test body",
    )

    connection.send_message.assert_called_once()
    (sent_message,), _ = connection.send_message.call_args
    assert sent_message["Subject"] == "Test subject"
    assert sent_message["From"] == "user@t-online.de"
    assert sent_message["To"] == "user@t-online.de"
    assert sent_message.get_content().strip() == "Test body"
