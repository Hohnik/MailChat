# Context

MailChat reads a person's mailboxes and shows the mail as chat. One context, one
glossary — use these words in code, tests, and issues.

## Glossary

**Account** — one mail service MailChat has been given credentials for: an
address, an IMAP host/port, an SMTP host/port, and an encrypted password.
Connecting an account proves the credentials before anything is stored.

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
and returns domain values — folders, raw messages. Callers never see a
connection handle, never learn that the protocol libraries block, and never
reach for `imaplib` themselves; the package owns connection lifetime, the wire
format, and the threads that keep blocking calls off the event loop.

`mail.imap` is the whole IMAP interface:

- `folders(credentials)` — the folders the server offers. It doubles as the
  IMAP credential check: a successful call proves the login.
- `fetch(credentials, folders, limit=10)` — the most recent raw messages from
  each named folder. No default folder; callers say what they want.

**Login error vs. operation error.** `ImapLoginError` means there is no
session — bad password, unreachable host — and is fatal. `ImapOperationError`
means the login worked but a command afterwards didn't, and is survivable: an
account whose server refuses to `LIST` still connects, and the user picks their
Sent folder later. Nothing else escapes the package; both derive from
`ImapError`.

**Injecting it.** Callers type the dependency as the `Imap` protocol and default
it to the module, so tests pass a fake in rather than patching. Routes take it
as a FastAPI dependency (`get_imap`) that tests override.

`mail.imap`'s own tests reach its internals through a stubbed `Transport` — the
seam that stands in for `imaplib.IMAP4_SSL` — so they still exercise the public
interface. `sync.smtp_client` has not moved into the package yet.
