from __future__ import annotations


class MailChatError(Exception):
    pass


class AccountConnectionError(MailChatError):
    pass
