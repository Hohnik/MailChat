from __future__ import annotations

import os

from cryptography.fernet import Fernet

os.environ.setdefault("MAILCHAT_CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MAILCHAT_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
