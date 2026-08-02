_default:
    -just --list --unsorted

# Start the app on http://127.0.0.1:8000/accounts
run:
    .venv/bin/python -m mailchat

# Same, but reload on code changes
dev:
    .venv/bin/python -m uvicorn --factory mailchat.main:production_app --reload

# Generate a Fernet key for MAILCHAT_CREDENTIALS_MASTER_KEY
key:
    @.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

test:
    .venv/bin/python -m pytest -q
