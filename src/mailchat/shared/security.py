from __future__ import annotations

from cryptography.fernet import Fernet

from mailchat.config import settings


def encrypt(plaintext: str) -> str:
    return Fernet(settings.credentials_master_key).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return Fernet(settings.credentials_master_key).decrypt(ciphertext.encode()).decode()
