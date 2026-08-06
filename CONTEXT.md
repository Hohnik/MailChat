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

**Synced folders** — the folders one pass of sync reads for an account: its
inbox always, plus its Sent folder once picked — one folder, not two, for an
account whose sent mail lands in the inbox. `accounts/folders.py` is the one
place that answers it, off the account's own row — no login needed to learn what
to fetch, and no second default hiding in a caller. Sync asks each pass, so a
folder picked between polls is read by the next one.

**Raw message** — one message as the server sent it, RFC 822 bytes, before
parsing. What the `mail` package deals in.

**Fetched message** — one raw message and what only the fetch knows about it:
the folder it was found in, its UID there, that folder's UIDVALIDITY, and
whether the server holds it flagged read. Folder, UID and UIDVALIDITY are one
address between them — a UID means nothing without the folder it was handed out
in, and nothing at all once that folder's UIDVALIDITY has moved on.

**Message** — one stored mail belonging to one account, parsed out of the raw
message a server sent, filed in one conversation. Its date is held in UTC,
whatever zone the sender wrote it in — SQLite keeps the clock and drops the
offset, so a conversation only reads in the order it was said if the offset is
spent on the way in.

**Direction** — which way a message was going: `inbound` for mail that reached
the user, `outbound` for mail they sent. Read from the folder it was fetched
from — the inbox, or the account's Sent folder — and never from its headers,
because the account that sent a message is the one whose Sent folder holds it,
and no amount of reading `From` proves that.

**Read state** — the server's, not MailChat's. `Message.is_read` is a cache of
the IMAP `\Seen` flag: seeded at ingest and overwritten by every poll that
reaches the message, in both directions, so there is no pending or dirty state
to reconcile — a local change that doesn't reach the server didn't happen.
Conversations have no read state of their own; a conversation is unread when its
messages are. Only inbound messages count towards that: a reply the user wrote
is waiting for nobody, whatever their server flagged it.

**Contact** — one person MailChat has mail from or to, known by one lowercased
address. Two addresses belonging to one human stay two contacts. The display
name is what the most recently sent message to name them called them — settled
across a whole fetch, not message by message, because a fetch reads the inbox
before the sent folder and would otherwise let old mail rename someone.

**Me** — the one contact at `me@mailchat.local`, which mail the user exchanged
with nobody but themselves groups under. Not a real address and never sent to:
it exists so that a note forwarded between two of the user's own accounts lands
somewhere instead of being dropped for having no other correspondent, and it
splits by subject like any other contact.

**Conversation** — one contact, one normalized subject: everything said between
you on that topic. No account component — the same contact reaching two of the
user's mailboxes is one conversation, because it is one conversation to them.

**Normalized subject** — a subject with every `Re`/`Aw`/`Fwd`/`Fw`/`Wg` marker
taken out of it, wherever in the string it sits, whitespace collapsed. A key to
group by, never something shown: the message keeps the subject it arrived under.

**Grouping** — deciding which conversation a message belongs in: who it is with,
from the header its direction names, and what it is about, from its normalized
subject. The correspondent is the first address in that header that isn't one of
the user's own connected accounts, or *Me* when none is left; `Cc` is never
consulted, so looping someone into a thread — or dropping them from it — never
moves the conversation.
`Message-ID`, `In-Reply-To` and `References` are stored on every message and
asked by none of this.

**Ingestion** — the one step from fetched messages to stored messages: parse
them, group them into conversations, store what isn't stored already, and take
the server's word again about the rest. A message is recognised by its
`Message-ID`, per account — so the same message fetched by two polls is stored
once, while one message id arriving at two accounts is two messages.

**Sync** — one pass over an account's synced folders, fetching their messages in
one login and ingesting them. The worker syncs every account on a poll interval;
one account's failure never stops the others. Reading mail never marks it read:
the fetch peeks at bodies and selects folders read-only, so a `\Seen` flag moves
because the user read the mail somewhere, never because MailChat looked at it.

## The accounts module

`accounts/service.py` is the only way to read or act on an account. Callers —
routes, the sync worker — ask it for accounts as well as act on them:
`list_accounts`, `get_account`, `connect`, `list_account_folders`,
`set_sent_folder`, `disconnect`, and `imap_credentials_for` for the login sync
fetches with. No production caller outside the package opens
`accounts/repository.py`; tests still seed rows through it, the way they reach a
module's internals elsewhere. `list_accounts` passes straight through to storage
and is worth its own line anyway: one door in is what keeps a caller from
growing a second answer behind the module's back.

Storage is what the door is in front of — not the whole package. What else is
public answers questions the service doesn't: `accounts/folders.py` for which
folders one sync pass reads, `accounts/models.py` for the `Account` type
everyone passes around, and `accounts/routes.py` for the HTTP surface `main.py`
mounts.

**One vocabulary for a missing account.** `get_account` raises
`AccountNotFoundError` rather than handing back `None`, so "is there an account
with this id?" has one answer everywhere — `disconnect` included, where an id
that was never there used to pass for a disconnection that happened. Losing that
quieter second answer is the point, and it is a real change in what the user
sees: disconnecting an account twice now says so.

What it means for a request is decided once per medium: `main.py` renders it as a
404, and the accounts routes catch it first only because their answer is the
accounts section with the message above the list — the same place a refused login
or an unknown folder lands. Both keep the domain's own wording inside, because it
names the id: that belongs in a log, not in front of someone who just clicked a
button on a page that has gone stale. A refused login and an unknown folder do
still reach the page as the domain phrased them. Each at least names something
the user chose — the address they typed, the folder they picked — but each also
carries the server's own words, and the unknown-folder message quotes with a
Python `repr`. Holding those two to the same standard is a loose end, not a
decision.

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
- `fetch(credentials, folders, limit=10)` — the most recent fetched messages
  from each named folder. No default folder; callers say what they want.

**Reading mail leaves it unread.** The fetch asks for `(UID FLAGS BODY.PEEK[])`
against a folder selected `readonly=True`, and both halves are load-bearing. A
non-PEEK body item (`RFC822`, `BODY[…]`) makes the server set `\Seen` on exactly
the messages fetched, which is the newest few per folder every poll interval —
so every new message would be marked read within a minute of arriving, before
the user ever opened it, and since the server is authoritative, syncing would be
quietly erasing MailChat's own unread state. `readonly=True` alone stops that;
`BODY.PEEK[]` makes it a property of the fetch rather than of a `SELECT`
argument someone could flip for an unrelated reason. The response comes back
keyed `BODY[]` rather than `RFC822`, and the bytes are identical.

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

## The ingestion module

`src/mailchat/sync/ingest.py` is the whole way mail becomes rows.
`ingest(session, account=…, fetched=…)` takes what a fetch returned and hands
back a stored message per fetched message, in the order they were fetched. The
worker calls nothing else on the way to the table.

Two internals answer to it. `sync/parser.py` reads RFC 822 bytes into a
`ParsedMessage` — decoding headers, picking a body part, sanitising HTML, and
putting the date into UTC. `sync/grouping.py` reads a parsed message and says
which conversation it belongs in: `direction_of` for which way it was going,
then `group` for who it is with and what it is about. Between them they make an
`Arrival` — one message read as far as it can be before the database is
involved — and everything after that is rows. Neither is called by production
code outside ingestion.
Their own tests call them directly, the way the mail package's tests reach a
`Transport` — grouping especially, because a rule about headers is worth reading
on its own, with no database anywhere near it.

**One field list on the way.** A parsed message becomes a row in `_message_for`,
the only place between the parsed form and the table where a message's fields
are named — including the four that arrive with the fetch rather than in the
mail itself: `is_read` and the folder, UID and UIDVALIDITY that address it.

**A message already stored is not left alone.** Read state and the address are
the server's, so every poll that reaches a message takes its word for both again
— `is_read` overwritten in whichever direction the flag moved, and the folder,
UID and UIDVALIDITY rewritten together, so an address left stale by a UIDVALIDITY
change heals on the next poll rather than pointing at whatever else took that
number. Which conversation the message is filed under is not touched: that is
MailChat's own reading of mail that hasn't changed. The refresh only reaches what
each poll fetches — the newest ten per folder — so a message read elsewhere after
it falls out of that window stays unread here.

**What ingestion can't recognise.** Mail carrying no `Message-ID` is stored
again every time it is fetched: matching it on anything else would risk merging
unrelated mail, and a poll re-reads the same window, so copies accumulate. Mail
that can't be parsed at all — an encoding Python doesn't know, say — is logged
and left out, so one bad message costs its own row rather than the whole fetch.

## The conversations module

`conversations/service.py` is the door: `conversation_for` for ingestion,
`list_conversations`, `get_conversation` and `messages_in` for the routes. It
holds both models — a contact exists to key a conversation, and nothing else
asks for one on its own. `get_conversation` raises `ConversationNotFoundError`
rather than handing back `None`, the way `get_account` does, so a link to a
conversation that has gone means one thing everywhere.

**One lock, both rows, one commit.** Accounts sync side by side and a
conversation belongs to no account, so two accounts meeting the same person for
the first time in one poll are two tasks about to create the same contact and
the same conversation. `conversation_for` holds one lock across both lookups and
both creates and doesn't release it until the pair is committed, so the second
task finds what the first one wrote. The keys are spelled out in the schema too
— unique on a contact's address, unique on a conversation's contact and subject
— not as the mechanism, but so that a lapse in it is a refused write to fix
rather than a second half-conversation nobody notices.

**Nothing about a conversation is stored twice.** Its unread count and the time
it was last spoken in are counted off its messages whenever the list is drawn,
in the same query that fetches the rows. Keeping either on the conversation
would be the same answer until the day a write is missed, and then only one of
them would still be true.
