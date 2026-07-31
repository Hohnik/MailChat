from __future__ import annotations

from pydantic import BaseModel


class AccountConnect(BaseModel):
    provider: str
    address: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    password: str
