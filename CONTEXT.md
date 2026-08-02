# Context

MailChat reads a person's mailboxes and shows the mail as chat. One context, one
glossary — use these words in code, tests, and issues.

## Glossary

**Account** — one mail service MailChat has been given credentials for: an
address, an IMAP host/port, an SMTP host/port, and an encrypted password.
Connecting an account proves the credentials on both protocols — IMAP by
listing folders, SMTP by logging in — before anything is stored.

**Credentials** — an account's stored login. Held encrypted; decrypted only to
hand to a mail server.

**Folder** — one place on the IMAP server that holds mail, named exactly as the
server names it (IMAP modified UTF-7 for non-ASCII), because that is the form
`SELECT` expects back. Never translated on the way through. IMAP itself calls
this a *mailbox*, which is why code close to the protocol — the stub connection,
the test fake's seed — says `mailboxes`; everywhere else, say folder.

**Sent folder** — the folder that holds an account's outgoing mail. The user
picks it from the server's own list; MailChat won't accept a name the server
didn't offer. Unset until they choose.

**Raw message** — one message as the server sent it, RFC 822 bytes, before
parsing. What the `mail` package deals in.

**Message** — a parsed, normalized, stored mail belonging to one account.

**Sync** — one pass over an account's folders, turning raw messages into
messages. The worker syncs every account on a poll interval; one account's
failure never stops the others.

## The mail package

`src/mailchat/mail/` is how the app talks to mail servers. It takes credentials
and returns domain values — folders, raw messages, a verdict on a login. Callers
never see a connection handle, never learn that the protocol libraries block,
and never reach for `imaplib` or `smtplib` themselves; the package owns
connection lifetime, the wire format, and the threads that keep blocking calls
off the event loop.

`mail.imap` is the whole IMAP interface:

- `folders(credentials)` — the folders the server offers. It doubles as the
  IMAP credential check: a successful call proves the login.
- `fetch(credentials, folders, limit=10)` — the most recent raw messages from
  each named folder. No default folder; callers say what they want.

`mail.smtp` is the whole SMTP interface:

- `verify(credentials)` — proof that the server accepts this login, and nothing
  else. SMTP's whole production job today.
- `send(credentials, sender, recipient, subject, body)` — one plain-text
  message. No production caller yet; its signature will grow In-Reply-To and
  References when replies become threaded.

`ImapCredentials` and `SmtpCredentials` stay separate types despite being
structurally identical — merging them would couple two modules that are
deliberately apart.

**Login error vs. operation error.** Both protocols split their failures the
same way. A `…LoginError` means there is no session — bad password, unreachable
host — and is always fatal. A `…OperationError` means the login worked but a
command afterwards didn't; whether that is survivable is the caller's call. An
account whose server refuses to `LIST` still connects, and the user picks their
Sent folder later — but connecting treats any SMTP failure as fatal, because an
account that can't send isn't one yet. Nothing else escapes the package: every
error out of it derives from `ImapError` or from `SmtpError`.

**Injecting it.** Callers type the dependency as the `Imap` or `Smtp` protocol
and default it to the module, so tests pass a fake in rather than patching.
Routes take them as FastAPI dependencies (`get_imap`, `get_smtp`) that tests
override.

Each module's own tests reach its internals through a stubbed `Transport` — the
seam that stands in for `imaplib.IMAP4_SSL` or `smtplib.SMTP_SSL` — so they
still exercise the public interface.
