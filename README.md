```
mailchat/
├── src/
│   └── mailchat/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py              # Settings (env vars, pydantic-settings)
│       ├── main.py                # App factory, router registration
│       │
│       ├── accounts/              # Connected mailboxes (Gmail, IMAP, ...)
│       │   ├── __init__.py
│       │   ├── models.py          # Account, Credentials
│       │   ├── service.py         # Connect/disconnect, OAuth flow
│       │   ├── repository.py      # DB access
│       │   ├── schemas.py         # API input/output
│       │   └── routes.py
│       │
│       ├── conversations/         # The "chat" view
│       │   ├── __init__.py
│       │   ├── models.py          # Conversation, Participant
│       │   ├── service.py         # Threading logic, grouping by person/subject
│       │   ├── repository.py
│       │   ├── schemas.py
│       │   └── routes.py
│       │
│       ├── mail/                  # Talking to mail servers
│       │   ├── __init__.py        # get_imap, get_smtp (FastAPI dependencies)
│       │   ├── imap.py            # Folders and raw messages, from credentials
│       │   └── smtp.py            # Verifying a login and sending, from credentials
│       │
│       ├── messages/              # Individual mails/chat bubbles
│       │   ├── __init__.py
│       │   ├── models.py          # Message, Attachment
│       │   ├── service.py         # Send, reply, mark read
│       │   ├── repository.py
│       │   ├── schemas.py
│       │   └── routes.py
│       │
│       ├── sync/                  # The heart of the app: mail ingestion
│       │   ├── __init__.py
│       │   ├── gmail_client.py    # Provider-specific APIs (optional)
│       │   ├── parser.py          # RFC 822 parsing, MIME, HTML→text
│       │   ├── threading.py       # Message-ID/In-Reply-To/References matching
│       │   ├── normalizer.py      # Raw mail → Message model
│       │   └── worker.py          # Background sync loop
│       │
│       ├── realtime/              # Push updates to the app
│       │   ├── __init__.py
│       │   ├── websocket.py       # WS endpoint, connection manager
│       │   └── events.py          # Event types (new_message, sync_done, ...)
│       │
│       ├── contacts/              # People you're "chatting" with
│       │   ├── __init__.py
│       │   ├── models.py
│       │   ├── service.py         # Build from message history, avatars
│       │   └── routes.py
│       │
│       └── shared/
│           ├── __init__.py
│           ├── db.py              # Engine, session, base model
│           ├── security.py        # Token encryption (app passwords, OAuth)
│           ├── exceptions.py
│           └── logging.py
│
├── tests/
│   ├── fakes.py                   # FakeImap and friends, injected by callers' tests
│   ├── test_mail/
│   │   ├── test_imap.py
│   │   └── test_smtp.py
│   ├── test_sync/
│   │   ├── test_parser.py
│   │   └── test_threading.py
│   ├── test_conversations/
│   └── fixtures/
│       └── emails/                # Sample .eml files for tests
│
├── CONTEXT.md                     # Domain glossary
├── pyproject.toml
├── README.md
└── LICENSE
```
