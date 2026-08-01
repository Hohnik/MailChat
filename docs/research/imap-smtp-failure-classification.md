# Which IMAP and SMTP auth failures are permanent, and which are transient?

Research for: [GitHub issue #21](https://github.com/Hohnik/MailChat/issues/21) (part of [#18](https://github.com/Hohnik/MailChat/issues/18))

## Direct answer

**The protocols give you a two-way split; the Python stdlib gives you a three-way one, and the third bucket is not small.**

1. **SMTP is well specified.** The first digit of the reply code carries the answer: `4yz` means retry, `5yz` means do not repeat the request. RFC 4954 adds the auth-specific codes on top: `454` is "temporary authentication failure", `535` is "authentication credentials invalid". Read literally, MailChat's two observed T-Online failures classify cleanly and oppositely: `421` transient, `535` permanent.

2. **IMAP has no numeric codes at all.** The equivalent is `NO` vs `BAD`, plus the *optional* RFC 5530 response codes `[AUTHENTICATIONFAILED]` (permanent — "there's no point in trying the same login/password again later") and `[UNAVAILABLE]` (transient). `NO` = the credentials were rejected; `BAD` = MailChat sent a malformed command (a client bug, not a credential fact). Because the response codes are optional, a bare `NO` tells you nothing about permanence.

3. **The stdlib loses information in three specific, reproducible ways** (all verified locally against scripted fake servers on CPython 3.13.3 — see [Appendix](#appendix-how-the-stdlib-behaviour-was-verified)):
   - `smtplib.SMTP.login()` tries every advertised mechanism and re-raises only the **last** failure, so a `454` can be masked by a later `535` and vice versa.
   - A `421` returned *during* AUTH (rather than in the greeting) usually arrives with the server closing the socket, which surfaces as `SMTPServerDisconnected` — **the code 421 is gone entirely**.
   - `imaplib` collapses `NO` and `BAD` into the same exception type, `IMAP4.error`, with no structured field at all.

4. **`5xx` does not mean "these credentials will never work."** It means "do not repeat this request unchanged." RFC 5321 says so explicitly, and MailChat's own T-Online case is the proof: the *same password* authenticated successfully over IMAP throughout while SMTP returned `535`. Nothing was wrong with the credentials. Treating `535` as "bad password" would have told the user a falsehood.

So the re-check policy needs **three** states, not two: `permanent` (stop, require user action), `transient` (auto-retry with backoff), and `indeterminate` (retry, but never render it as a credential problem and never overwrite a previously-good state). The classification tables below are the concrete mapping.

---

## The classification

### SMTP

`Code` is what the server sent. `Python surface` is what MailChat's code actually catches today, given that `sync/smtp_client.py:21` calls `smtplib.SMTP.login()`.

| Observed failure | Python surface | Class | Why | Recommended MailChat behaviour |
| --- | --- | --- | --- | --- |
| `421` in the **greeting**<br>(`421 IP=… No more parallel connections from your address allowed` — observed on T-Online) | `SMTPConnectError`, `smtp_code=421` | **Transient** | RFC 5321 §4.2.3: "Service not available, closing transmission channel". 4yz = "the error condition is temporary". | Do not record an SMTP failure. Auto-retry with backoff. Leave prior capability state untouched. |
| `421` **during AUTH**, server closes socket<br>(e.g. Gmail's `421 4.7.0 Too many login attempts, please try again later.`) | `SMTPServerDisconnected` — **no code** | **Indeterminate**, treat as transient | The code is destroyed by `login()`'s mechanism loop. Cannot be distinguished from a network drop. | Auto-retry with backoff. Never surface as "wrong password". |
| `421` during AUTH, server keeps socket open, single mechanism advertised | `SMTPAuthenticationError`, `smtp_code=421` | **Transient** | 4yz. | Auto-retry with backoff. |
| `454 4.7.0 Temporary authentication failure` | `SMTPAuthenticationError`, `smtp_code=454` | **Transient** | RFC 4954 §6: "authentication failed due to a temporary server failure. The client SHOULD NOT prompt the user for another password". | Auto-retry. Show as "server unavailable", explicitly **not** a credential prompt. |
| `432 4.7.12 A password transition is needed` | `SMTPAuthenticationError`, `smtp_code=432` | **Transient** | 4yz; RFC 4954 §6 says the mechanism "SHOULD then work for authentications in subsequent sessions". | Auto-retry. Rare in practice; folding it into the generic 4xx bucket is fine. |
| `450` / `451` / `452` / `455` | `SMTPResponseException` subclasses with code | **Transient** | 4yz. Not auth-stage codes — they show up in submission, not verification. | Auto-retry. Out of scope for a capability check. |
| `535 …` (any text)<br>(`535 5.7.0 Authentication rejected / Authentication failed.` — observed on T-Online) | `SMTPAuthenticationError`, `smtp_code=535` | **Permanent** *(in the "stop auto-retrying" sense only)* | RFC 4954 §6: "authentication failed due to invalid or insufficient authentication credentials". But see [the 535 caveat](#1-5xx-means-stop-auto-retrying-not-the-credentials-are-wrong). | Record the SMTP failure. Stop auto-retrying. Offer a manual re-check button and show the server's raw text. Do **not** assert "wrong password". |
| `534 5.7.9 Authentication mechanism is too weak` | `SMTPAuthenticationError`, `smtp_code=534` | **Permanent for this attempt**, fixable by config | RFC 4954 §6: "The client SHOULD retry with a new authentication mechanism." | Record as a failure. Retrying identically will not help; the fix is a different mechanism/TLS, not a new password. |
| `538 5.7.11 Encryption required` | `SMTPAuthenticationError`, `smtp_code=538` | **Permanent**, fixable by config | RFC 4954 §6 — and it flags this code as "documented here for historical purposes only". | Same as 534. MailChat uses `SMTP_SSL`, so this should never appear. |
| `530 5.7.0 Authentication required` | `SMTPAuthenticationError`, `smtp_code=530` | **Client/config bug** | RFC 4954 §6 says 530 is for commands *other than* AUTH. Seeing it in response to AUTH means the server is non-conformant. | Record as a failure. Log loudly — it indicates a misconfiguration or an odd server. |
| `501` / `500` (syntax, exchange line too long) | `SMTPAuthenticationError`, `smtp_code=501`/`500` | **Client bug** | RFC 4954 §4: 501 is what a server returns when the client cancels the exchange. | Do not blame the credentials. Log as a MailChat bug. |
| `504` (mechanism not supported) | `SMTPAuthenticationError`, `smtp_code=504` | **Config** | RFC 4954 §4. | Same as 534. |
| Server advertises no `AUTH` in EHLO | `SMTPNotSupportedError` — **no code** | **Permanent config error** | `smtplib.SMTP.login()` raises before sending anything. | Record. The host/port is wrong, or STARTTLS is needed. |
| Socket closed mid-AUTH with no reply | `SMTPServerDisconnected` — **no code** | **Indeterminate** | Indistinguishable from a rate-limit drop. RFC 4954 §7: "Servers MAY implement a policy whereby the connection is dropped after a number of failed authentication attempts." | Auto-retry with backoff. Never surface as a credential problem. |
| DNS failure, refused connection, TLS handshake failure, timeout | `socket.gaierror` / `ConnectionRefusedError` / `ssl.SSLError` / `TimeoutError` — **never an `SMTPException`** | **Indeterminate** (network) | These bypass the smtplib hierarchy entirely. | Auto-retry. Not a capability signal at all. |

### IMAP

`Python surface` is what `sync/imap_client.py:22` (`imaplib.IMAP4_SSL.login()`) produces.

| Observed failure | Python surface | Class | Why | Recommended MailChat behaviour |
| --- | --- | --- | --- | --- |
| `NO [AUTHENTICATIONFAILED] …` | `IMAP4.error`, args = **bytes** `b'[AUTHENTICATIONFAILED] Authentication failed'` | **Permanent** | RFC 5530: "when a client sees AUTHENTICATIONFAILED, it knows that the problem wasn't, e.g., UNAVAILABLE, so there's no point in trying the same login/password again later." | Stop auto-retrying. This is the one case where "your credentials were rejected" is a defensible message. |
| `NO [EXPIRED] …` | `IMAP4.error`, bytes | **Permanent** | RFC 5530: "access is no longer permitted using that passphrase. The client or user should get a new passphrase." | Stop. Prompt for new credentials. |
| `NO [AUTHORIZATIONFAILED] …` | `IMAP4.error`, bytes | **Permanent** | RFC 5530 — authn succeeded, authz denied. | Stop. Not a password problem. |
| `NO [UNAVAILABLE] …` | `IMAP4.error`, bytes | **Transient** | RFC 5530: "Temporary failure because a subsystem is down." | Auto-retry with backoff. Do not prompt for a password. |
| `NO [PRIVACYREQUIRED] …` | `IMAP4.error`, bytes | **Permanent config error** | RFC 5530 — needs TLS. MailChat always uses `IMAP4_SSL`, so this should not appear. | Record; log as misconfiguration. |
| `NO` with **no response code** | `IMAP4.error`, bytes | **Indeterminate**, lean permanent | RFC 3501 §6.2.3: "NO — login failure: user name or password rejected". RFC 5530 explicitly allows omitting the code, so absence proves nothing. | Stop auto-retrying (a repeated identical LOGIN is what triggers server-side lockouts), but show the raw server text rather than asserting the password is wrong. |
| `BAD …` | `IMAP4.error`, args = **str** `"LOGIN command error: BAD [b'…']"` | **Client bug** | RFC 3501 §7.1.3: "it reports a protocol-level error in the client's command". | Never a credential fact. Log as a MailChat bug (e.g. a quoting failure). Do not mark the account. |
| Untagged `* BYE` then a tagged reply, server closes | `IMAP4.abort` (a **subclass of `IMAP4.error`**), str `"command: LOGIN => …"` | **Transient** | RFC 3501 §7.1.5: BYE is "a panic shutdown announcement" or "an inactivity autologout". Python docs: "closing the instance and instantiating a new one will usually allow recovery". | Auto-retry on a fresh connection. Commonly a rate limit ("too many invalid login attempts"). |
| Socket EOF mid-LOGIN | `IMAP4.abort`, str `"command: LOGIN => socket error: EOF"` | **Indeterminate** | Same exception shape as the BYE case. | Auto-retry with backoff. |
| Greeting is `* BYE …` (server refuses the connection outright) | `IMAP4.error` — **not `abort`** — args = bytes, the whole greeting line | **Transient** | RFC 3501 §7.1.5 case 4: "the server is not willing to accept a connection from this client." Typically an IP-level block or connection cap. | Auto-retry with backoff. Note the asymmetry: this is `error`, not `abort`. |
| DNS failure, refused connection, TLS failure, timeout | `socket.gaierror` / `ConnectionRefusedError` / `ssl.SSLError` / `TimeoutError` — **never an `IMAP4.error`** | **Indeterminate** (network) | These come from `IMAP4.open()` before any IMAP framing exists. | Auto-retry. Not a capability signal. |
| `IMAP4.readonly` | subclass of `IMAP4.abort` | **N/A** | Raised only from `_command()` / `select()` on a mailbox whose write status changed. It cannot occur during LOGIN. | Irrelevant to a capability check; ignore. |

---

## Supporting detail

### 1. `5xx` means "stop auto-retrying", not "the credentials are wrong"

This is the single most consequential finding, and the RFC says it outright. RFC 5321 §4.2.1:

> **5yz  Permanent Negative Completion reply**
> The command was not accepted and the requested action did not occur.  The SMTP client SHOULD NOT repeat the exact request (in the same sequence).  **Even some "permanent" error conditions can be corrected**, so the human user may want to direct the SMTP client to reinitiate the command sequence by direct action at some point in the future (e.g., after the spelling has been changed, or the user has altered the account status).

And the `4yz` counterpart, with the rule of thumb that decides the boundary:

> **4yz  Transient Negative Completion reply**
> The command was not accepted, and the requested action did not occur.  However, the error condition is temporary, and the action may be requested again. […] A rule of thumb to determine whether a reply fits into the 4yz or the 5yz category (see below) is that **replies are 4yz if they can be successful if repeated without any change in command form or in properties of the sender or receiver** (that is, the command is repeated identically and the receiver does not put up a new implementation).

Source: [RFC 5321 §4.2.1](https://www.rfc-editor.org/rfc/rfc5321#section-4.2.1)

That rule of thumb is exactly why MailChat's T-Online `535` is a `5yz`: a mailbox flagged for outbound spam is a "property of the sender", and clearing the flag is a change. The reply is correctly permanent *by the spec's definition* — and simultaneously **not** a statement that the password is wrong. The empirical proof is in the ticket itself: the same password authenticated over IMAP throughout.

### 2. The RFC 4954 auth codes — and the fact that RFC 5321 does not contain them

Grepping the RFC 5321 text for `454`, `530`, `534`, `535`, `538` and `432` returns **zero hits**. None of the SMTP AUTH codes are in RFC 5321; they live only in RFC 4954 §6. Anything that classifies auth codes "per RFC 5321" is classifying by first digit alone.

RFC 4954 §6, verbatim, on the pair the ticket asks about:

> `454 4.7.0  Temporary authentication failure`
>
> This response to the AUTH command indicates that the authentication failed due to a temporary server failure.  **The client SHOULD NOT prompt the user for another password in this case, and should instead notify the user of server failure.**

> `535 5.7.8  Authentication credentials invalid`
>
> This response to the AUTH command indicates that the authentication failed due to invalid or insufficient authentication credentials.  In this case, the client SHOULD ask the user to supply new credentials (such as by presenting a password dialog box).

The rest:

> `432 4.7.12  A password transition is needed` — "the user needs to transition to the selected authentication mechanism.  This is typically done by authenticating once using the [PLAIN] authentication mechanism.  The selected mechanism SHOULD then work for authentications in subsequent sessions."

> `534 5.7.9  Authentication mechanism is too weak` — "the selected authentication mechanism is weaker than server policy permits for that user.  The client SHOULD retry with a new authentication mechanism."

> `530 5.7.0  Authentication required` — "This response SHOULD be returned by **any command other than AUTH**, EHLO, HELO, NOOP, RSET, or QUIT when server policy requires authentication in order to perform the requested action and authentication is not currently in force."

> `538 5.7.11  Encryption required for requested authentication mechanism` — "Note that this response code is documented here for historical purposes only."

`501` at the AUTH stage is a client-side cancel, per RFC 4954 §4:

> If the client wishes to cancel the authentication exchange, it issues a line with a single "*".  If the server receives such a response, it MUST reject the AUTH command by sending a 501 reply.

And RFC 4954 §7 documents the behaviour that produces the code-less disconnects:

> Servers MAY implement a policy whereby the connection is dropped after a number of failed authentication attempts.  If they do so, they SHOULD NOT drop the connection until at least 3 attempts to authenticate have failed.

Sources: [RFC 4954 §4](https://www.rfc-editor.org/rfc/rfc4954#section-4), [RFC 4954 §6](https://www.rfc-editor.org/rfc/rfc4954#section-6), [RFC 4954 §7](https://www.rfc-editor.org/rfc/rfc4954#section-7)

### 3. `421` is a connection-level event, not an auth verdict

RFC 5321 §4.2.3 lists it under the connection group:

> `421  <domain> Service not available, closing transmission channel` (This may be a reply to any command if the service knows it must shut down)

§3.8 makes the "closing" part normative — a server MUST NOT close the connection except after QUIT, after a timeout, or:

> After detecting the need to shut down the SMTP service and returning a 421 response code.  This response code can be issued after the server receives any command or, if necessary, asynchronously from command receipt

and, crucially for the indeterminate bucket:

> SMTP clients that experience a connection close, reset, or other communications failure due to circumstances not under their control […] SHOULD, to maintain the robustness of the mail system, **treat the mail transaction as if a 451 response had been received** and act accordingly.

That is a direct spec mandate to treat an unexplained disconnect as *transient*, which is what the `SMTPServerDisconnected` row of the table does.

Source: [RFC 5321 §3.8](https://www.rfc-editor.org/rfc/rfc5321#section-3.8)

The observed T-Online message, `421 IP=<redacted> No more parallel connections from your address allowed`, is a connection-cap refusal — it is about the *IP address*, not the account. It says nothing whatsoever about SMTP capability for those credentials.

### 4. IMAP: `NO` vs `BAD` vs connection-level

RFC 3501 defines the three outcomes per command. For LOGIN (§6.2.3):

> Result:     OK - login completed, now in authenticated state
>             NO - login failure: user name or password rejected
>             BAD - command unknown or arguments invalid

For AUTHENTICATE (§6.2.2):

> Result:     OK - authenticate completed, now in authenticated state
>             NO - authenticate failure: unsupported authentication mechanism, credentials rejected
>             BAD - command unknown or arguments invalid, authentication exchange cancelled

The generic definitions (§7.1.2, §7.1.3) put the split in one sentence each:

> The **NO** response indicates an **operational error** message from the server.  When tagged, it indicates unsuccessful completion of the associated command.

> The **BAD** response indicates an error message from the server.  When tagged, it reports a **protocol-level error in the client's command**; the tag indicates the command that caused the error.

RFC 9051 (IMAP4rev2) carries both definitions across **unchanged**, so there is no version skew to worry about.

The connection-level case is BYE (§7.1.5), which is sent under one of four conditions — normal logout, "a panic shutdown announcement", "an announcement of an inactivity autologout", or as a greeting "indicating that the server is not willing to accept a connection from this client".

Sources: [RFC 3501 §6.2.2–6.2.3](https://www.rfc-editor.org/rfc/rfc3501#section-6.2.2), [RFC 3501 §7.1](https://www.rfc-editor.org/rfc/rfc3501#section-7.1), [RFC 9051 §6.2.3](https://www.rfc-editor.org/rfc/rfc9051#section-6.2.3), [RFC 9051 §7.1](https://www.rfc-editor.org/rfc/rfc9051#section-7.1)

### 5. IMAP's real permanent/transient signal is RFC 5530, and it is optional

RFC 3501 gives no way to tell "wrong password" from "auth backend is down" — both are a tagged `NO`. RFC 5530 fixes that with response codes, and its wording is the closest thing in either protocol to a plain statement of the permanence question:

> **UNAVAILABLE**
> Temporary failure because a subsystem is down.  For example, an IMAP server that uses a Lightweight Directory Access Protocol (LDAP) or Radius server for authentication might use this response code when the LDAP/Radius server is down.
>
> `C: a LOGIN "fred" "foo"`
> `S: a NO [UNAVAILABLE] User's backend down for maintenance`

> **AUTHENTICATIONFAILED**
> Authentication failed for some reason on which the server is unwilling to elaborate.  Typically, this includes "unknown user" and "bad password".
>
> **This is the same as not sending any response code**, except that when a client sees AUTHENTICATIONFAILED, it knows that the problem wasn't, e.g., UNAVAILABLE, so there's **no point in trying the same login/password again later**.

> **EXPIRED**
> Either authentication succeeded or the server no longer had the necessary data; either way, access is no longer permitted using that passphrase.  The client or user should get a new passphrase.

The italicised sentence matters both ways: `[AUTHENTICATIONFAILED]` is a positive permanence signal, but its **absence is not a transience signal** — the RFC says it is "the same as not sending any response code". A bare `NO` is genuinely ambiguous.

RFC 9051 §7.1 folds all of these into IMAP4rev2 with identical wording.

Sources: [RFC 5530 §3](https://www.rfc-editor.org/rfc/rfc5530#section-3), [RFC 9051 §7.1](https://www.rfc-editor.org/rfc/rfc9051#section-7.1)

### 6. What `smtplib` preserves — and the three places it does not

`smtplib.SMTPResponseException.__init__` stores the code and the raw server bytes:

```python
class SMTPResponseException(SMTPException):
    def __init__(self, code, msg):
        self.smtp_code = code
        self.smtp_error = msg
        self.args = (code, msg)
```

`SMTPAuthenticationError`, `SMTPConnectError`, `SMTPHeloError`, `SMTPDataError` and `SMTPSenderRefused` all inherit that, so `smtp_code` and `smtp_error` are available on every one of them. `smtp_error` is `bytes`, not `str`.

Source: [CPython `Lib/smtplib.py` lines 90–144](https://github.com/python/cpython/blob/3.13/Lib/smtplib.py#L90-L144); [`smtplib` docs](https://docs.python.org/3/library/smtplib.html#smtplib.SMTPResponseException)

**Loss #1 — `SMTPAuthenticationError` is not specific to bad credentials.** `SMTP.auth()` raises it for *every* reply that is not 235 or 503:

```python
if code in (235, 503):
    return (code, resp)
raise SMTPAuthenticationError(code, resp)
```

So `454`, `530`, `534`, `538`, `501` and (sometimes) `421` all arrive as `SMTPAuthenticationError`. The exception type carries no classification at all — **the code must be read off `smtp_code`**. Catching `SMTPAuthenticationError` and reporting "wrong password" is wrong for the majority of the codes that can produce it.

Source: [CPython `Lib/smtplib.py` line 662](https://github.com/python/cpython/blob/3.13/Lib/smtplib.py#L660-L662)

**Loss #2 — `login()` reports the *last* mechanism's failure, not the most informative one.** `login()` iterates every advertised mechanism in a fixed preference order and re-raises whatever the final attempt produced:

```python
preferred_auths = ['CRAM-MD5', 'PLAIN', 'LOGIN']
...
for authmethod in authlist:
    try:
        (code, resp) = self.auth(...)
        if code in (235, 503):
            return (code, resp)
    except SMTPAuthenticationError as e:
        last_exception = e

# We could not login successfully.  Return result of last attempt.
raise last_exception
```

Verified behaviour (server advertises `PLAIN LOGIN`):

| Server replies | What `login()` raises |
| --- | --- |
| `454` to PLAIN, then `535` to LOGIN | `SMTPAuthenticationError` **535** — a transient condition reported as permanent |
| `535` to PLAIN, then `454` to LOGIN | `SMTPAuthenticationError` **454** — a permanent condition reported as transient |
| `534` to PLAIN, then `535` to LOGIN | `SMTPAuthenticationError` **535** |

Both misclassification directions are reachable. Whichever code you read may not be the one that describes the account.

Source: [CPython `Lib/smtplib.py` lines 686–750](https://github.com/python/cpython/blob/3.13/Lib/smtplib.py#L686-L750)

**Loss #3 — a `421` during AUTH is usually erased.** Because servers that send `421` normally close the socket, and because `login()` then tries the *next* mechanism on the dead socket, `getreply()` hits EOF and raises:

```python
if not line:
    self.close()
    raise SMTPServerDisconnected("Connection unexpectedly closed")
```

Verified: with `PLAIN LOGIN` advertised and the server replying `421 4.7.0 Too many connections` then closing, `login()` raises **`SMTPServerDisconnected`** with no `smtp_code` and the message `'Connection unexpectedly closed'`. With only `PLAIN` advertised and the socket left open, the same reply yields `SMTPAuthenticationError` with `smtp_code=421`. **The same server condition produces two different exception types with different information content**, depending on how many mechanisms the server advertised.

This is not hypothetical for MailChat: Google documents `421 4.7.0 Too many login attempts, please try again later.` as a live Gmail auth-stage response, and the observed T-Online `421` is the same family.

Source: [CPython `Lib/smtplib.py` lines 396–405](https://github.com/python/cpython/blob/3.13/Lib/smtplib.py#L396-L405); [Gmail SMTP errors and codes](https://knowledge.workspace.google.com/admin/support/troubleshooting/gmail-smtp-errors-and-codes)

**Also note:** `smtplib.SMTPException` subclasses `OSError` (since Python 3.4), so `except OSError` catches protocol errors *and* `ConnectionRefusedError` / `socket.gaierror` / `ssl.SSLError` indiscriminately. Network failures are never `SMTPException` subclasses — verified: `SMTP_SSL` to a closed port raises `ConnectionRefusedError`, to a bad hostname `socket.gaierror`, to a non-TLS port `ssl.SSLError`.

### 7. What `imaplib` does NOT give you

There is no code, no numeric field, and no separation between the two protocol outcomes. `login()` is four lines:

```python
def login(self, user, password):
    typ, dat = self._simple_command('LOGIN', user, self._quote(password))
    if typ != 'OK':
        raise self.error(dat[-1])
    self.state = 'AUTH'
    return typ, dat
```

`BAD` never reaches that check, because `_command_complete()` intercepts it first:

```python
if typ == 'BAD':
    raise self.error('%s command error: %s %s' % (name, typ, data))
```

So **`NO` and `BAD` raise the identical exception type**, `imaplib.IMAP4.error`. The only discriminator is the shape of the argument, which is an undocumented implementation detail:

| Server sends | `type(e)` | `e.args[0]` | Discriminator |
| --- | --- | --- | --- |
| `NO [AUTHENTICATIONFAILED] Authentication failed` | `IMAP4.error` | `b'[AUTHENTICATIONFAILED] Authentication failed'` | `bytes`, raw server text |
| `NO Invalid credentials` | `IMAP4.error` | `b'Invalid credentials'` | `bytes`, raw server text |
| `BAD Command argument error` | `IMAP4.error` | `"LOGIN command error: BAD [b'Command argument error']"` | `str`, imaplib-formatted prefix |

To classify, MailChat must (a) check whether `args[0]` is `bytes` (⇒ `NO`) or `str` starting with `"LOGIN command error: BAD "` (⇒ `BAD`), and then (b) regex the RFC 5530 response code out of the bytes. There is no supported API for either.

`IMAP4.abort` is more useful because it *is* semantically loaded — the docs say so:

> **imaplib.IMAP4.abort** — IMAP4 server errors cause this exception to be raised. This is a sub-class of `IMAP4.error`. Note that **closing the instance and instantiating a new one will usually allow recovery from this exception.**

That is an explicit "transient, retry on a fresh connection" marker. Two traps, both verified:

- `abort` is a **subclass of `error`**, so `except IMAP4.error` swallows it. The `abort` check must come first.
- A `* BYE` **greeting** (server refusing the connection) raises plain `IMAP4.error`, *not* `abort` — it comes from `_connect()`'s `raise self.error(self.welcome)`, before any command exists. A `* BYE` *mid-command* raises `abort`. Same protocol event, two exception types depending on timing.

`IMAP4.readonly` is a subclass of `abort` raised only from `_command()`/`select()`; it cannot occur during LOGIN and is irrelevant here.

The `imaplib` docs never mention `'BAD'` as a possible `typ` value, and document no exception attributes at all.

Sources: [CPython `Lib/imaplib.py` lines 187–189, 612–623, 1050–1065](https://github.com/python/cpython/blob/3.13/Lib/imaplib.py#L187-L189); [`imaplib` docs](https://docs.python.org/3/library/imaplib.html#imaplib.IMAP4.abort)

### 8. Is there a documented convention for a 4xx during *credential verification*?

**Not in the RFCs directly — but yes in practice, and the convention is unambiguous: 4xx auto-retry belongs to message submission, not to credential verification.**

RFC 5321 §4.5.4.1 defines the retry regime, and it is explicitly about a *mail queue*:

> The sender MUST delay retrying a particular destination after one attempt has failed.  In general, the retry interval SHOULD be at least 30 minutes […] Retries continue until the message is transmitted or the sender gives up; the give-up time generally needs to be at least 4-5 days.

Nothing there applies to "is this password good". But the *next* paragraph is directly on point for MailChat's sticky-state question:

> At the same time, **SMTP clients SHOULD use great care in caching negative responses from servers**.  In an extreme case, if EHLO is issued multiple times during the same SMTP connection, different answers may be returned by the server.  More significantly, 5yz responses to the MAIL command MUST NOT be cached.

A stored `smtp_ok = False` flag *is* a cached negative response. The RFC's warning applies.

Source: [RFC 5321 §4.5.4.1](https://www.rfc-editor.org/rfc/rfc5321#section-4.5.4.1)

**Thunderbird is the best available primary implementation**, and it draws the line in exactly this place. Its `SmtpClient` auto-retries a 4xx on a fresh connection — but only for `MAIL` and `RCPT`:

```js
_onNsError(error, errorParam, extra, statusCode) {
  // First check if handling an error response that might need a retry.
  if ([this._actionMAIL, this._actionRCPT].includes(this._currentAction)) {
    if (statusCode >= 400 && statusCode < 500) {
      // Possibly too many recipients, too many messages, to much data
      // or too much time has elapsed on this connection.
      if (!this.isRetry) {
        // ... We close the connection and try again to send on a new
        // connection using this same client instance.
```

The AUTH stage has no such branch. `_actionAUTHComplete` treats *any* non-2xx reply identically:

```js
_actionAUTHComplete(command) {
  this._authenticating = false;
  if (!command.success) {     // success === statusCode >= 200 && < 300
    this._onAuthFailed(command);
```

…and `_onAuthFailed` tries the remaining mechanisms, then prompts the user with a retry / new-password / cancel dialog **regardless of the reply code**. A socket close during auth is folded into the same path: `if (this._authenticating) { this._onAuthFailed({ data: "Socket closed." }); }`.

Sources: [`mailnews/compose/src/SmtpClient.sys.mjs`](https://hg.mozilla.org/comm-central/file/tip/mailnews/compose/src/SmtpClient.sys.mjs)

Thunderbird's account-setup verifier is even more directly analogous to MailChat's `_verify`, and its policy is: **one shot, no auto-retry, surface the server's own text, and refuse to claim "wrong password" unless certain**. The comment is worth quoting in full:

```js
// *Only* for known (!) username/password errors, show our message.
// But there are 1000 other reasons why it could have failed, e.g.
// server not reachable, bad auth method, server hiccups, or even
// custom server messages that tell the user to do something,
// so show the backend error message, unless we are certain
// that it's a wrong username or password.
```

Source: [`mail/components/accountcreation/modules/ConfigVerifier.sys.mjs`](https://github.com/mozilla/releases-comm-central/blob/HEAD/mail/components/accountcreation/modules/ConfigVerifier.sys.mjs)

On the IMAP side Thunderbird **does** honour RFC 5530, and only that one code. `nsImapProtocol::TryToLogon`:

```cpp
if (!loginSucceeded) {
  // If server gave reason for authentication failure as [UNAVAILABLE]
  // then we skip authentication retries, etc. The user will be notified by
  // pop-up with the reason, provided by the server, as to why it's
  // unavailable, e.g., too many connection to the server.
  if (GetServerStateParser().fServerUnavailable) break;
```

with the flag set by string-matching the response code, exactly as MailChat would have to:

```cpp
if (!PL_strcasecmp(fNextToken, "ALERT]") ||
    !PL_strcasecmp(fNextToken, "UNAVAILABLE]")) {
  // Treat ALERT and UNAVAILABLE response codes similarly. Show response
  // code string in pop-up. See RFC 5530 "IMAP Response Codes".
  ...
  // If UNAVAILABLE, flag this to prevent a possible password prompt
  fServerUnavailable = (NS_ToUpper(fNextToken[0]) == 'U');
```

Notably it does **not** special-case `[AUTHENTICATIONFAILED]` — everything that is not `[UNAVAILABLE]` falls through to "might be a wrong password, ask the user".

Sources: [`mailnews/imap/src/nsImapProtocol.cpp`](https://github.com/mozilla/releases-comm-central/blob/HEAD/mailnews/imap/src/nsImapProtocol.cpp), [`mailnews/imap/src/nsImapServerResponseParser.cpp`](https://github.com/mozilla/releases-comm-central/blob/HEAD/mailnews/imap/src/nsImapServerResponseParser.cpp)

---

## Where the spec is ambiguous or reality diverges

These are findings in their own right — the decision ticket should treat them as constraints, not footnotes.

**A. "Permanent" is defined relative to *repeating the request*, not to the credentials.** RFC 5321's own 5yz text ("Even some 'permanent' error conditions can be corrected") concedes this. There is **no** reply code anywhere in SMTP or IMAP that means "this password is wrong and always will be". The closest is IMAP's `[AUTHENTICATIONFAILED]`, and even that is described as covering "unknown user" as well as "bad password". Any MailChat copy that says "incorrect password" is an inference the protocol does not support.

**B. Enhanced status codes do not agree with reply codes in the wild.** RFC 4954 §6 registers `535` ↔ `5.7.8`. T-Online sent **`535 5.7.0`** — and `5.7.0` is RFC 4954's registered pairing for `530`, meaning per RFC 3463 only "Other or undefined security status". Gmail pairs it differently again: `535 5.7.80` per Google's own docs, against `5.7.8` in the RFC. **Do not classify on the enhanced code.** Classify on the three-digit reply code; treat the enhanced code as display text.

**C. Servers use 5xx for transient conditions and 4xx for durable ones.** Google documents `550 5.7.1 This email has been rate limited` — a rate limit (transient by nature) delivered as a permanent code — alongside `421 4.7.28 Gmail has detected an unusual rate of email` for the same class of problem. Conversely a spam-flagged mailbox (T-Online's case) can sit in a `535` state for days. **The code tells you what to do next; it does not tell you how long the condition will last.**

**D. A 5xx auth failure is frequently a server-side policy state, not a credential state.** Microsoft documents SMTP AUTH being disabled tenant-wide (`Set-TransportConfig -SmtpClientAuthenticationDisabled $true`), per-mailbox (`Set-CASMailbox`), and implicitly by Entra security defaults — "If *security defaults* is enabled in your organization, SMTP AUTH is already disabled in Exchange Online." A correct password against such a mailbox fails at AUTH. This is precisely MailChat's T-Online situation in a different costume, and it is the strongest argument for the per-protocol capability model in #18.

**E. RFC 5530 codes are optional, and even servers that implement them fully will sometimes send something else.** "This is the same as not sending any response code" — so a bare `NO` cannot be read as either permanent or transient. Dovecot implements the whole set (`UNAVAILABLE` for a temp-fail, `AUTHENTICATIONFAILED` for a plain auth failure, `EXPIRED`, `AUTHORIZATIONFAILED`, `PRIVACYREQUIRED`, `CONTACTADMIN`) — but when it is configured to give a *reason* for the failure it sends `NO [ALERT] <reason>` instead:

```c
case CLIENT_AUTH_RESULT_AUTHFAILED_REASON:
case CLIENT_AUTH_RESULT_MECH_INVALID:
    if (text[0] == '[')
        client_send_reply(client, IMAP_CMD_REPLY_NO, text);
    else {
        client_send_reply_code(client, IMAP_CMD_REPLY_NO,
                               "ALERT", text);
    }
```

So on the most widely deployed open-source IMAP server, the *more informative* configuration is the one that drops the machine-readable permanence signal. A classifier must treat "no recognised RFC 5530 code" as the common case, not the exception.

Source: [`dovecot/core src/imap-login/client-authenticate.c`](https://github.com/dovecot/core/blob/main/src/imap-login/client-authenticate.c), [`src/lib-imap/imap-resp-code.h`](https://github.com/dovecot/core/blob/main/src/lib-imap/imap-resp-code.h)

**F. IMAP has no `421` analogue.** Rate limits and connection caps surface as an untagged `* BYE`, a `NO` with vendor-specific text, or a bare TCP close — three different `imaplib` exception shapes for one condition (`abort`, `error`, `abort` respectively). The greeting-BYE / mid-command-BYE asymmetry described in §7 is a pure `imaplib` artefact with no basis in RFC 3501.

**G. Thunderbird ignores RFC 4954's `454` guidance.** The RFC says a client "SHOULD NOT prompt the user for another password" on `454`; Thunderbird prompts on any non-2xx AUTH reply. If MailChat *does* honour `454`, it will be more correct than the reference implementation — but it should not expect servers to be careful about emitting `454` versus `535`, precisely because no major client distinguishes them.

**H. `smtplib` behaviour depends on what the server advertises.** As shown in §7, the same server condition (`421` at AUTH) yields `SMTPAuthenticationError(421, …)` or a code-less `SMTPServerDisconnected` depending purely on how many AUTH mechanisms were advertised. Classification must therefore be defensive: `SMTPServerDisconnected` during a capability check is *never* evidence of bad credentials.

---

## Practical implication for MailChat

**1. Three capability states, not two.** `unknown` / `ok` / `failed` is not enough. The check outcome needs `permanent` (sticky until the user acts), `transient` (auto-retry, capability state unchanged), and `indeterminate` (auto-retry, capability state unchanged, never rendered as a credential problem). The indeterminate bucket is not a hedge — it is where `SMTPServerDisconnected`, bare IMAP `NO`, and every network/TLS error land, and those are common.

**2. Only a `permanent` result should be sticky.** Per RFC 5321 §4.5.4.1's warning about caching negative responses, transient and indeterminate outcomes must not overwrite a previously-good capability. A `421` connection cap during a background re-check should not flip a working account to "SMTP broken".

**3. Capture the code at the point of failure, because the current code throws it away.** `accounts/service.py:58-59` does:

```python
except Exception as error:
    raise AccountConnectionError(f"Could not connect to {request.address}: {error}") from error
```

f-stringing the exception discards the type and `smtp_code` and keeps only `str(error)` — which for `SMTPAuthenticationError` is the repr of a tuple, `"(535, b'5.7.0 Authentication rejected …')"`. Classification has to happen in `sync/smtp_client.py` and `sync/imap_client.py`, where the live exception object still exists, and the result must be carried through as structured data (protocol, reply code, raw server text, classification) rather than a formatted string.

**4. Consider bypassing `smtplib.SMTP.login()` for the capability check.** `login()`'s mechanism loop is what masks codes and erases `421`s. Calling `smtplib.SMTP.auth()` directly with one chosen mechanism gives a 1:1 mapping from server reply to `smtp_code`. If that is too invasive, the fallback rule is: **treat `SMTPServerDisconnected` during a check as transient, never as an auth failure** — which is also what RFC 5321 §3.8 mandates ("treat the mail transaction as if a 451 response had been received").

**5. Classification helpers, concretely.**
   - SMTP: `isinstance(e, SMTPResponseException)` → read `e.smtp_code`; `400 <= code < 500` ⇒ transient, `code == 535/534/538/530/504/501` ⇒ permanent-or-config, anything else 5xx ⇒ permanent. `SMTPServerDisconnected` / `SMTPNotSupportedError` / `OSError` that is not an `SMTPException` ⇒ indeterminate (except `SMTPNotSupportedError`, which is a permanent config error).
   - IMAP: check `IMAP4.abort` **before** `IMAP4.error` (it is a subclass) ⇒ transient. Then for `IMAP4.error`, branch on `isinstance(e.args[0], bytes)`: `str` ⇒ `BAD` ⇒ client bug, not a capability fact; `bytes` ⇒ `NO` ⇒ regex `^\[([A-Z-]+)\]` and map `UNAVAILABLE` ⇒ transient, `AUTHENTICATIONFAILED`/`EXPIRED`/`AUTHORIZATIONFAILED`/`PRIVACYREQUIRED` ⇒ permanent, no code ⇒ indeterminate-lean-permanent.

**6. Always store and display the server's raw text.** Both Thunderbird call sites converge on this, and #18's open question "whether provider-specific diagnosis belongs in the error surface at all" has an answer from prior art: show the server's own words, and add MailChat's interpretation only where the protocol licenses it. For T-Online's `535 5.7.0 Authentication rejected / Authentication failed.` the honest surface is "the server rejected SMTP authentication for this account — IMAP is working", not "wrong password".

**7. Retry cadence.** RFC 5321 §4.5.4.1's "at least 30 minutes" is written for a message queue, not a credential check, so it is not binding here — but it is the only number the specs offer, and it is a reasonable floor for *automatic* re-checks. A user-initiated re-check button (mirroring the existing `Choose sent folder` control) should bypass any backoff, and should be offered for `permanent` outcomes too, since RFC 5321 §4.2.1 explicitly anticipates the human correcting a "permanent" condition out of band.

---

## Appendix: how the stdlib behaviour was verified

Every "Python surface" claim in the tables was produced by running CPython 3.13.3's `smtplib`/`imaplib` against scripted fake servers on `127.0.0.1` that emit a chosen reply and optionally close the socket, then recording `type(e)`, `e.args`, and `e.smtp_code`/`e.smtp_error` where present. The probes covered every SMTP reply code in the table, both mechanism-masking orders, greeting vs mid-AUTH `421`, mid-AUTH socket close, absent `AUTH` advertisement, all six RFC 5530 IMAP response codes, bare `NO`, `BAD`, untagged `* BYE`, `* BYE` greeting, mid-LOGIN EOF, and DNS/refused/TLS failures for both protocols. The probe scripts were throwaway and are not committed; the behaviours are reproducible from the source line references cited above.

---

## Sources

Primary specs:

- [RFC 5321 — Simple Mail Transfer Protocol](https://www.rfc-editor.org/rfc/rfc5321.txt) — §3.8 (session termination, 421), §4.2.1 (reply code severities), §4.2.3 (reply codes in numeric order), §4.5.4.1 (sending strategy, caching negative responses)
- [RFC 4954 — SMTP Service Extension for Authentication](https://www.rfc-editor.org/rfc/rfc4954.txt) — §4 (the AUTH command), §6 (status codes 235/432/454/500/530/534/535/538), §7 (dropping connections after failed attempts)
- [RFC 3501 — IMAP4rev1](https://www.rfc-editor.org/rfc/rfc3501.txt) — §6.2.2 (AUTHENTICATE), §6.2.3 (LOGIN), §7.1.1–7.1.5 (OK/NO/BAD/PREAUTH/BYE)
- [RFC 9051 — IMAP4rev2](https://www.rfc-editor.org/rfc/rfc9051.txt) — §6.2.3, §7.1 (response definitions and response codes; wording unchanged from 3501/5530)
- [RFC 5530 — IMAP Response Codes](https://www.rfc-editor.org/rfc/rfc5530.txt) — §3 (UNAVAILABLE, AUTHENTICATIONFAILED, AUTHORIZATIONFAILED, EXPIRED, PRIVACYREQUIRED)
- [RFC 3463 — Enhanced Mail System Status Codes](https://www.rfc-editor.org/rfc/rfc3463.txt) — class sub-codes 2/4/5, X.7.0

Python standard library (source and docs):

- [CPython `Lib/smtplib.py` (3.13)](https://github.com/python/cpython/blob/3.13/Lib/smtplib.py) — exception classes L90–144, `getreply` L380–427, `connect`/`__init__` L228–346, `auth` L616–662, `login` L686–750
- [CPython `Lib/imaplib.py` (3.13)](https://github.com/python/cpython/blob/3.13/Lib/imaplib.py) — `error`/`abort`/`readonly` L187–189, `_connect` L230–256, `authenticate` L429–455, `login` L612–623, `_check_bye` L967–970, `_command_complete` L1050–1065, `_get_line` L1190–1206
- [`smtplib` — Python documentation](https://docs.python.org/3/library/smtplib.html)
- [`imaplib` — Python documentation](https://docs.python.org/3/library/imaplib.html)

Reference client implementation (Mozilla Thunderbird / comm-central):

- [`mailnews/compose/src/SmtpClient.sys.mjs`](https://hg.mozilla.org/comm-central/file/tip/mailnews/compose/src/SmtpClient.sys.mjs) — `_onNsError` 4xx retry scoped to MAIL/RCPT, `_actionAUTHComplete`, `_onAuthFailed`, `_onClose`
- [`mail/components/accountcreation/modules/ConfigVerifier.sys.mjs`](https://github.com/mozilla/releases-comm-central/blob/HEAD/mail/components/accountcreation/modules/ConfigVerifier.sys.mjs) — `_failed`, credential-verification policy
- [`mailnews/imap/src/nsImapProtocol.cpp`](https://github.com/mozilla/releases-comm-central/blob/HEAD/mailnews/imap/src/nsImapProtocol.cpp) — `TryToLogon`, `[UNAVAILABLE]` short-circuit
- [`mailnews/imap/src/nsImapServerResponseParser.cpp`](https://github.com/mozilla/releases-comm-central/blob/HEAD/mailnews/imap/src/nsImapServerResponseParser.cpp) — `resp_text_code`, `fServerUnavailable`

Reference server implementation (Dovecot):

- [`src/imap-login/client-authenticate.c`](https://github.com/dovecot/core/blob/main/src/imap-login/client-authenticate.c) — mapping from auth result to IMAP response code
- [`src/lib-imap/imap-resp-code.h`](https://github.com/dovecot/core/blob/main/src/lib-imap/imap-resp-code.h) — RFC 5530 response code constants

Provider documentation (cited for real-world divergence from the specs):

- [Gmail SMTP errors and codes — Google Workspace Admin Help](https://knowledge.workspace.google.com/admin/support/troubleshooting/gmail-smtp-errors-and-codes) — `421 4.7.0 Too many login attempts`, `421 4.7.28`, `535 5.7.80`, `550 5.7.1 This email has been rate limited`
- [Enable or disable SMTP AUTH in Exchange Online — Microsoft Learn](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/authenticated-client-smtp-submission) — tenant-wide and per-mailbox SMTP AUTH disablement; security defaults
- [How to set up a multifunction device or application to send email using Microsoft 365 — Microsoft Learn](https://learn.microsoft.com/en-us/exchange/mail-flow-best-practices/how-to-set-up-a-multifunction-device-or-application-to-send-email-using-microsoft-365-or-office-365) — "SMTP AUTH is disabled for organizations created after January 2020"

Related MailChat research:

- [`docs/research/t-online-imap-smtp-totp.md`](./t-online-imap-smtp-totp.md) — why T-Online requires a separate "Passwort für E-Mail-Programme"
