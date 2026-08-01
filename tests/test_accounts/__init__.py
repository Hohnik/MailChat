from __future__ import annotations


def stub_folders(mock_imap_ssl, *folders: str) -> None:
    """Make a patched IMAP4_SSL answer LIST with the given mailbox names."""
    mock_imap_ssl.return_value.list.return_value = (
        "OK",
        [f'(\\HasNoChildren) "/" "{folder}"'.encode() for folder in folders],
    )
