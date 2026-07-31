# Does T-Online require an app-specific password for IMAP/SMTP when TOTP/2FA is enabled?

Research for: [GitHub issue #2](https://github.com/Hohnik/MailChat/issues/2)

## Direct answer

**Yes — a separate, app-specific password is required for IMAP/SMTP access — but not *because* of TOTP/2FA.**

T-Online / Telekom **never** accepts the regular Telekom account password (the "Kundencenter"/web-login password — the one TOTP/2FA protects) for third-party email programs. This is an unconditional, longstanding requirement, independent of whether Mehr-Faktor-Authentifizierung (MFA/TOTP) is enabled on the web login or not. Telekom calls this separate credential the **"Passwort für E-Mail-Programme"** ("password for email programs").

So the practical consequence for MailChat is the same as with Google/Microsoft's app-password model — the password currently in `src/mailchat/.env` (the regular account password) will not work for IMAP/SMTP and must be replaced with a generated "Passwort für E-Mail-Programme" — but the *mechanism* differs: it's not a special case triggered by turning on 2FA, it's how T-Online mail-client access has always worked, 2FA or not.

## Supporting detail

### 1. A separate "Passwort für E-Mail-Programme" is required for any third-party mail client

Official Telekom help page — purpose of the email-program password:

> "If you want to retrieve your Telekom emails not via Email Center or Telekom Mail App, but via an email program (e.g. Outlook, Thunderbird) or another app (e.g. Apple Mail, Gmail App), you need a password for email programs."

Source: [telekom.de/hilfe — Passwort für E-Mail-Programme einrichten](https://www.telekom.de/hilfe/festnetz-internet-tv/e-mail/e-mail-adresse-passwoerter-und-sicherheit/passwort-fuer-e-mail-programme-einrichten)

Official Telekom help page on setting up a program/app account:

> "Um Ihre E-Mail-Adresse @magenta.de/@t-online.de in einem E-Mail-Programm einzurichten, benötigen Sie neben Ihrem Namen und Ihrer E-Mail-Adresse, das **Passwort für E-Mail-Programme**"
> ("To set up your @magenta.de/@t-online.de address in an email program, besides your name and email address you need the **password for email programs**.")

Source: [telekom.de/hilfe — Einrichtung in Programm oder App](https://www.telekom.de/hilfe/apps-dienste/e-mail/app-programm-einrichten)

Official Telekom help page on IMAP/SMTP server settings:

> "Bei der Einrichtung in Ihrem E-Mail-Programm benötigen Sie ein Passwort für E-Mail-Programme"
> ("When setting up in your email program you need a password for email programs.")

with server settings:

- IMAP incoming: `secureimap.t-online.de`, port `993`, SSL
- SMTP outgoing: `securesmtp.t-online.de`, port `465` or `587`, SSL

— matching exactly what's already configured for MailChat in `src/mailchat/.env`.

Source: [telekom.de/hilfe — Posteingangsserver & Postausgangsserver](https://www.telekom.de/hilfe/apps-dienste/e-mail/einstellungen/posteingang-postausgang-server)

### 2. This password should (and by design does) differ from the regular Telekom login password

> "Das Passwort für E-Mail-Programme sollte sich aus Sicherheitsgründen von dem des Telekom Logins unterscheiden."
> ("For security reasons, the password for email programs should differ from your Telekom login password.")

Source: [telekom.de/hilfe — Passwort für E-Mail-Programme verwalten](https://www.telekom.de/hilfe/apps-dienste/e-mail/programme/passwort-verwalten)

This same page has no mention whatsoever of two-factor authentication, TOTP, or Mehr-Faktor-Authentifizierung — the email-program password is documented as a standalone feature, not something that only appears once 2FA is switched on.

### 3. Where to generate it

Per the official help page above, there are two equivalent paths:

**Via E-Mail Center** (`email.t-online.de`, log in with the Telekom login):
1. Click the gear icon ("Einstellungen") top right
2. "Alle Einstellungen anzeigen"
3. "Passwörter"
4. "Passwort für E-Mail-Programme" → create/change it here

**Via Kundencenter** (`telekom.de/pup` — password/profile management):
1. "Profil verwalten"
2. "Login-Daten"
3. "Weitere Passwörter" → the email-program password is listed here

Source: [telekom.de/hilfe — Passwort für E-Mail-Programme verwalten](https://www.telekom.de/hilfe/apps-dienste/e-mail/programme/passwort-verwalten)

### 4. TOTP/MFA (Mehr-Faktor-Authentifizierung) is a fully separate mechanism that does not touch IMAP/SMTP

Telekom's official MFA help page describes MFA purely in terms of protecting the Telekom Login / customer-portal / app access (password + SMS code or authenticator-app code for sign-in and "important actions"). It contains **no mention of email programs, IMAP, SMTP, POP3, or app-specific passwords** anywhere on the page — confirming MFA and the email-program password are independent systems.

Source: [telekom.de/hilfe — Mehr-Faktor-Authentifizierung](https://www.telekom.de/hilfe/vertrag-rechnung/telekom-login/mehr-faktor-authentifizierung)

This independence is also called out (as a security caveat, not a feature) in the Telekom hilft user community: IMAP/POP3/SMTP access via the separate mail-program password is described as bypassing MFA entirely, since mail clients authenticate with that separate password rather than going through the MFA-protected web login flow. The community guidance for a compromised account explicitly includes rotating **both** the regular login password **and** the separate "Passwort für E-Mail-Programme" (found under `telekom.de/pup` → Login-Daten → "weitere Passwörter"), and recommends disabling IMAP/POP access entirely if unused, or setting MFA to apply to "every login," since MFA alone does not cover mail-client access.

Source (community, cited for corroboration only — not the basis of the primary claim): [Telekom hilft Community — 2FA Telefonnummer wieder löschbar? Hacker fängt wohl SMS ab](https://telekomhilft.telekom.de/conversations/e-mail/2fa-telefonnummer-wieder-l%C3%B6schbar-hacker-f%C3%A4ngt-wohl-sms-ab/69287b463d94d928a59cb77d)

## Practical implication for MailChat

- The value currently in `src/mailchat/.env` is the regular T-Online account password. Per Telekom's own documentation this **will not authenticate** against `secureimap.t-online.de:993` / `securesmtp.t-online.de:465|587` regardless of the TOTP setting on the web login — it never has, for any T-Online account using third-party IMAP/SMTP clients.
- Action needed: log into the E-Mail Center or Kundencenter (`telekom.de/pup`) as niklaslhohn@gmail.com's T-Online account holder, generate/rotate a **"Passwort für E-Mail-Programme,"** and put that value in `.env` instead of the web-login password.
- No additional TOTP-specific step (e.g., scanning a QR code for an "app password" flow like Google/Microsoft) is documented by Telekom for mail-client access — the email-program password is a plain generated/settable password, not a TOTP-derived one.

## Sources

- [telekom.de/hilfe — Passwort für E-Mail-Programme einrichten](https://www.telekom.de/hilfe/festnetz-internet-tv/e-mail/e-mail-adresse-passwoerter-und-sicherheit/passwort-fuer-e-mail-programme-einrichten)
- [telekom.de/hilfe — Passwort für E-Mail-Programme verwalten](https://www.telekom.de/hilfe/apps-dienste/e-mail/programme/passwort-verwalten)
- [telekom.de/hilfe — Posteingangsserver & Postausgangsserver](https://www.telekom.de/hilfe/apps-dienste/e-mail/einstellungen/posteingang-postausgang-server)
- [telekom.de/hilfe — Einrichtung in Programm oder App](https://www.telekom.de/hilfe/apps-dienste/e-mail/app-programm-einrichten)
- [telekom.de/hilfe — Mehr-Faktor-Authentifizierung](https://www.telekom.de/hilfe/vertrag-rechnung/telekom-login/mehr-faktor-authentifizierung)
- [Telekom hilft Community — 2FA Telefonnummer wieder löschbar? Hacker fängt wohl SMS ab](https://telekomhilft.telekom.de/conversations/e-mail/2fa-telefonnummer-wieder-l%C3%B6schbar-hacker-f%C3%A4ngt-wohl-sms-ab/69287b463d94d928a59cb77d) (community corroboration only)

*Note: the `telekom.de/hilfe/...` pages above return a login-wall redirect when fetched directly by some automated tools; content was retrieved via a text-extraction proxy that renders the same public page. All quoted text is from Telekom's own official help pages, not third-party summaries.*
