from __future__ import annotations

from htpy import Node, a, button, div, form, fragment, h1, input, label, li, option, p, select, ul

from mailchat.accounts.models import Account

DEFAULT_SENT_FOLDER = "Sent"


def _field(label_text: str, name: str, *, type: str = "text", value: str | None = None) -> Node:
    return fragment[
        label(for_=name)[label_text],
        input(type=type, name=name, id=name, required=True, value=value),
    ]


def account_form() -> Node:
    return form(hx_post="/accounts", hx_target="#accounts-section", hx_swap="outerHTML")[
        _field("Provider", "provider", value="generic"),
        _field("Address", "address", type="email"),
        _field("IMAP host", "imap_host"),
        _field("IMAP port", "imap_port", type="number", value="993"),
        _field("SMTP host", "smtp_host"),
        _field("SMTP port", "smtp_port", type="number", value="465"),
        _field("App-specific password", "password", type="password"),
        button(type="submit")["Connect"],
    ]


def sent_folder_picker(account: Account, folders: list[str]) -> Node:
    """Let the user say which of the server's folders holds their sent mail.

    Nothing is guessed: `Sent` is pre-selected only when the server actually has
    a folder by that name, and otherwise the form starts on a placeholder that
    can't be submitted.
    """
    selected = account.sent_folder
    if selected is None and DEFAULT_SENT_FOLDER in folders:
        selected = DEFAULT_SENT_FOLDER

    options: list[Node] = []
    if selected is None:
        options.append(option(value="", disabled=True, selected=True)["Choose a folder…"])
    options.extend(option(value=folder, selected=folder == selected)[folder] for folder in folders)

    return form(
        id="sent-folder-picker",
        hx_post=f"/accounts/{account.id}/sent-folder",
        hx_target="#accounts-section",
        hx_swap="outerHTML",
    )[
        p[f"Which folder holds sent mail for {account.address}?"],
        label(for_="sent_folder")["Sent folder"],
        select(name="sent_folder", id="sent_folder", required=True)[options],
        button(type="submit")["Save sent folder"],
    ]


def _sent_folder_status(account: Account) -> Node:
    pick = button(
        type="button",
        hx_get=f"/accounts/{account.id}/sent-folder",
        hx_target="#accounts-section",
        hx_swap="outerHTML",
    )

    if account.sent_folder is None:
        return pick["Choose sent folder"]

    return fragment[f"Sent folder: {account.sent_folder}", pick["Change"]]


def account_list(accounts: list[Account]) -> Node:
    if not accounts:
        return ul(id="account-list")[p["No accounts connected yet."]]

    return ul(id="account-list")[
        [
            li(id=f"account-{account.id}")[
                f"{account.address} ({account.provider})",
                _sent_folder_status(account),
                a(href=f"/accounts/{account.id}/messages")["View messages"],
                form(
                    hx_post=f"/accounts/{account.id}/disconnect",
                    hx_target="#accounts-section",
                    hx_swap="outerHTML",
                )[button(type="submit")["Disconnect"]],
            ]
            for account in accounts
        ]
    ]


def accounts_section(
    accounts: list[Account], *, error: str | None = None, picker: Node | None = None
) -> Node:
    children: list[Node] = [account_form()]
    if error:
        children.append(p(class_="error")[error])
    if picker is not None:
        children.append(picker)
    children.append(account_list(accounts))
    return div(id="accounts-section")[children]


def accounts_page(accounts: list[Account]) -> Node:
    return div[h1["Connected accounts"], accounts_section(accounts)]
