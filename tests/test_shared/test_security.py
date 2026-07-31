from __future__ import annotations

from mailchat.shared.security import decrypt, encrypt


def test_encrypt_decrypt_round_trip():
    plaintext = "hunter2-app-specific-password"

    ciphertext = encrypt(plaintext)

    assert ciphertext != plaintext
    assert decrypt(ciphertext) == plaintext
