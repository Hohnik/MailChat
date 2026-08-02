from __future__ import annotations

from cryptography.fernet import Fernet

from mailchat.config import get_settings


def encrypt(plaintext: str) -> str:
    return Fernet(get_settings().credentials_master_key).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return Fernet(get_settings().credentials_master_key).decrypt(ciphertext.encode()).decode()
