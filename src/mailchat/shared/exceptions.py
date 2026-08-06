from __future__ import annotations


class MailChatError(Exception):
    pass


class AccountConnectionError(MailChatError):
    pass


class AccountNotFoundError(MailChatError):
    pass


class ConversationNotFoundError(MailChatError):
    pass


class UnknownFolderError(MailChatError):
    pass
