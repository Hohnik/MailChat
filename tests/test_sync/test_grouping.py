from __future__ import annotations

from mailchat.accounts.models import Account
from mailchat.messages.models import INBOUND, OUTBOUND
from mailchat.sync.grouping import ME, direction_of, group, normalize_subject
from mailchat.sync.parser import ParsedMessage

ACCOUNT_ADDRESSES = {"kunde@example.com"}

# The subject a German ticketing system mangles four ways on the way through a
# thread. Every variant is the same conversation to the person reading it.
LOUIS_SUBJECTS = [
    "[DL-4916597] Ihre Anfrage an Louis",
    "AW: [DL-4916597] Ihre Anfrage an Louis",
    "WG: AW: [DL-4916597] Ihre Anfrage an Louis",
    "[DL-4916597] Re: Ihre Anfrage an Louis",
]


def _parsed(**overrides) -> ParsedMessage:
    fields = {
        "message_id": "<one@example.com>",
        "in_reply_to": None,
        "references": None,
        "subject": "Anfrage",
        "from_header": "Absender <absender@example.com>",
        "to_header": "kunde@example.com",
        "cc_header": None,
        "date": None,
        "body": "body",
    }
    return ParsedMessage(**{**fields, **overrides})


def _account(*, address="kunde@example.com", sent_folder=None) -> Account:
    return Account(address=address, sent_folder=sent_folder)


async def test_a_folder_says_which_way_its_mail_was_going():
    account = _account(sent_folder="Gesendet")

    assert direction_of(account, "INBOX") == INBOUND
    assert direction_of(account, "Gesendet") == OUTBOUND


async def test_mail_in_an_inbox_that_is_also_the_sent_folder_reads_as_inbound():
    # Some accounts keep sent mail in the inbox. Guessing outbound there would
    # make every message the user received look like one they wrote.
    account = _account(sent_folder="inbox")

    assert direction_of(account, "INBOX") == INBOUND


async def test_a_subject_keeps_its_meaning_and_loses_its_markers():
    assert normalize_subject("Re: Terminanfrage") == "Terminanfrage"


async def test_reply_and_forward_markers_are_stripped_wherever_they_sit():
    # A ticketing system puts its own id first, so the marker lands mid-string
    # — anchoring the strip to the start would fracture one thread into four.
    assert {normalize_subject(subject) for subject in LOUIS_SUBJECTS} == {
        "[DL-4916597] Ihre Anfrage an Louis"
    }


async def test_stripping_a_subject_twice_changes_nothing_the_first_pass_left():
    once = normalize_subject("AW: WG: Fwd: Terminanfrage")

    assert once == "Terminanfrage"
    assert normalize_subject(once) == once


async def test_a_word_that_merely_starts_like_a_marker_stays():
    assert normalize_subject("Reise: Angebot") == "Reise: Angebot"
    assert normalize_subject("Fahrpreise: Übersicht") == "Fahrpreise: Übersicht"


async def test_a_subject_the_server_left_out_groups_with_the_other_untitled_mail():
    assert normalize_subject(None) == ""
    assert normalize_subject("   ") == ""


async def test_an_inbound_message_is_grouped_under_its_sender():
    grouping = group(
        _parsed(from_header="Louis Service <Service@Louis.de>", subject="AW: Anfrage"),
        direction=INBOUND,
        account_addresses=ACCOUNT_ADDRESSES,
    )

    assert grouping.address == "service@louis.de"
    assert grouping.display_name == "Louis Service"
    assert grouping.normalized_subject == "Anfrage"


async def test_an_outbound_message_is_grouped_under_who_it_was_sent_to():
    grouping = group(
        _parsed(from_header="kunde@example.com", to_header="Louis Service <service@louis.de>"),
        direction=OUTBOUND,
        account_addresses=ACCOUNT_ADDRESSES,
    )

    assert grouping.address == "service@louis.de"


async def test_grouping_never_lands_on_an_address_the_user_connected():
    grouping = group(
        _parsed(to_header="Kunde <kunde@example.com>, Louis Service <service@louis.de>"),
        direction=OUTBOUND,
        account_addresses=ACCOUNT_ADDRESSES,
    )

    assert grouping.address == "service@louis.de"


async def test_a_message_to_two_other_people_groups_under_the_first_of_them():
    # One conversation, not two: no fan-out, and no group chat.
    grouping = group(
        _parsed(to_header="erste@example.org, zweite@example.org"),
        direction=OUTBOUND,
        account_addresses=ACCOUNT_ADDRESSES,
    )

    assert grouping.address == "erste@example.org"


async def test_a_cc_never_decides_who_a_conversation_is_with():
    grouping = group(
        _parsed(
            from_header="Berater <berater@horbach.de>",
            cc_header="Assistenz <assistenz@horbach.de>",
        ),
        direction=INBOUND,
        account_addresses=ACCOUNT_ADDRESSES,
    )

    assert grouping.address == "berater@horbach.de"


async def test_mail_between_the_users_own_accounts_groups_under_one_sentinel_contact():
    grouping = group(
        _parsed(from_header="kunde@example.com", to_header="zweitkonto@example.com"),
        direction=INBOUND,
        account_addresses={"kunde@example.com", "zweitkonto@example.com"},
    )

    assert grouping.address == ME
    assert grouping.display_name == "Me"


async def test_mail_the_sentinel_holds_still_splits_by_subject():
    notes = [
        group(_parsed(subject=subject), direction=INBOUND, account_addresses={"absender@example.com"})
        for subject in ("Steuern 2026", "Umzug")
    ]

    assert [grouping.address for grouping in notes] == [ME, ME]
    assert notes[0].normalized_subject != notes[1].normalized_subject
