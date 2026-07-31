from __future__ import annotations

from htpy import Node, button, div, form, h1, input, label, li, p, ul

from mailchat.accounts.models import Account


def account_form() -> Node:
    return form(hx_post="/accounts", hx_target="#accounts-section", hx_swap="outerHTML")[
        label(for_="provider")["Provider"],
        input(type="text", name="provider", id="provider", required=True, value="generic"),
        label(for_="address")["Address"],
        input(type="email", name="address", id="address", required=True),
        label(for_="imap_host")["IMAP host"],
        input(type="text", name="imap_host", id="imap_host", required=True),
        label(for_="imap_port")["IMAP port"],
        input(type="number", name="imap_port", id="imap_port", required=True, value="993"),
        label(for_="smtp_host")["SMTP host"],
        input(type="text", name="smtp_host", id="smtp_host", required=True),
        label(for_="smtp_port")["SMTP port"],
        input(type="number", name="smtp_port", id="smtp_port", required=True, value="465"),
        label(for_="password")["App-specific password"],
        input(type="password", name="password", id="password", required=True),
        button(type="submit")["Connect"],
    ]


def account_list(accounts: list[Account]) -> Node:
    if not accounts:
        return ul(id="account-list")[p["No accounts connected yet."]]

    return ul(id="account-list")[
        [
            li(id=f"account-{account.id}")[
                f"{account.address} ({account.provider})",
                form(
                    hx_post=f"/accounts/{account.id}/disconnect",
                    hx_target="#accounts-section",
                    hx_swap="outerHTML",
                )[button(type="submit")["Disconnect"]],
            ]
            for account in accounts
        ]
    ]


def accounts_section(accounts: list[Account], *, error: str | None = None) -> Node:
    children: list[Node] = [account_form()]
    if error:
        children.append(p(class_="error")[error])
    children.append(account_list(accounts))
    return div(id="accounts-section")[children]


def accounts_page(accounts: list[Account]) -> Node:
    return div[h1["Connected accounts"], accounts_section(accounts)]
