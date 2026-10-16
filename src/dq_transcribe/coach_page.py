"""The coach page's HTML: the posted DQ list by event, and the password form.

Coaches open it on their phones over the meet Wi-Fi (see ``coach_server``). It
shows only what a coach would get on paper: each DQ's event, heat, lane,
swimmer, club, infractions and status, and (tapping a DQ) the slip itself. It
never shows audio, transcripts, notes or DQs the coach has not been told about.

DQs can be grouped by event (latest first, the default) or by swimmer (A to Z
by last name), for every club or one club, so a coach can see every DQ of one
swimmer together.

Which DQs: those of the active meet whose state is one of
``constants.DQ_STATES_AFTER_NOTIFICATION`` (notified, protested, upheld,
overturned), not in the trash. Overturned DQs stay on the list, struck through,
so a coach sees the ruling.

The page is plain HTML that reloads itself every
``constants.COACH_PAGE_REFRESH_SECONDS``: no script, so any phone browser works.
"""

from __future__ import annotations

import html
import json
import re
import string
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from dq_transcribe import constants

COACH_TEMPLATE_PATH = Path(__file__).parent / constants.WEB_DIRECTORY_NAME / constants.COACH_PAGE_FILENAME
PAGE_TITLE = "DQs"
LOGIN_TITLE = "DQs: sign in"
NO_MEET_TEXT = "No meet is running right now."
NO_DQS_TEXT = "No DQs posted yet. This page refreshes by itself."
NO_CLUB_DQS_TEXT = "No DQs posted for {club}."
ALL_CLUBS_LABEL = "All clubs"
UPDATED_FORMAT = "Updated {time} · refreshes every {seconds} s · tap a DQ for its slip"
EVENT_HEADING_FORMAT = "Event {number}"
UNKNOWN_EVENT_LABEL = "Event ?"
WHERE_FORMAT = "Heat {heat} · Lane {lane}"
RELAY_LEG_FORMAT = "{swimmer} (swimmer {leg})"
INFRACTION_SEPARATOR = "; "
STATUS_SEPARATOR = " \u00b7 "
PROTEST_OPEN_FORMAT = "Protest window open until {time}"
BACK_TO_LIST_LABEL = "All DQs"
PRINT_REQUEST_BUTTON_LABEL = "Request a printout"
PRINT_REQUEST_HINT = "Only if you need paper: the admin table prints it and you pick it up there."
PRINT_REQUEST_TITLE = "Printout requested"
PRINTOUT_QUEUED_LABEL = "\U0001F5A8 printout requested"
SORT_LABELS = {constants.COACH_SORT_BY_EVENT: "By event", constants.COACH_SORT_BY_NAME: "By swimmer"}
SORT_PROMPT = "Sort:"
DQ_COUNT_FORMAT = "{count} DQ"
DQ_COUNT_PLURAL_FORMAT = "{count} DQs"
EVENT_WITH_LABEL_FORMAT = "Event {number} {label}"
# A relay's name as the meet file gives it: club code and relay letter ("PASA-A").
RELAY_NAME_PATTERN = re.compile(r"^\S+-[A-Z]$")
WRONG_PASSWORD_TEXT = "That password didn't work. Check the sign at the admin table."

# What a coach sees for each DQ state: (label, CSS class).
COACH_STATUS = {
    constants.DQ_STATE_NOTIFIED: ("DQ", "dq-label"),
    constants.DQ_STATE_PROTESTED: ("Protested: the referee is reviewing", "review"),
    constants.DQ_STATE_UPHELD: ("DQ upheld after protest", "dq-label"),
    constants.DQ_STATE_OVERTURNED: ("Overturned: not a DQ", "clear"),
}
OVERTURNED_CSS_CLASS = "overturned"


def _escape(value: Any) -> str:
    """Text made safe for HTML."""
    return html.escape("" if value is None else str(value))


def _clock(moment: datetime) -> str:
    """"5:42 PM" in the tablet's time zone (owner preference: 12-hour clock)."""
    local = moment.astimezone() if moment.tzinfo else moment
    return local.strftime(constants.CLOCK_FORMAT_12_HOUR).lstrip("0")


def _parse_moment(text: str | None) -> datetime | None:
    """An ISO time from the database, or None."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _now_like(moment: datetime, now: datetime) -> datetime:
    """``now`` made comparable with ``moment`` (both aware, or both naive local times)."""
    if moment.tzinfo and not now.tzinfo:
        return now.astimezone()
    if not moment.tzinfo and now.tzinfo:
        return now.astimezone().replace(tzinfo=None)
    return now


def coach_visible_dqs(dqs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The DQs a coach may see: the coach has been told (or a protest followed)."""
    return [dq for dq in dqs if dq["state"] in constants.DQ_STATES_AFTER_NOTIFICATION and not dq.get("trashed_at")]


def infraction_text(dq: dict[str, Any]) -> str:
    """"3J One hand touch; 3E Alternating kick" (codes first, as on the slip)."""
    parts = []
    for infraction in dq.get("infractions") or []:
        code = infraction.get("code")
        parts.append(f"{code} {infraction['description']}" if code else infraction["description"])
    return INFRACTION_SEPARATOR.join(parts)


def print_request_url(dq_id: int, club: str | None, sort: str | None = None) -> str:
    """Where the "Request a printout" form posts (keeps the list view for the way back)."""
    return f"{constants.COACH_ROUTE_DQ}{dq_id}{constants.COACH_ROUTE_PRINT_REQUEST_SUFFIX}" + _list_query(club, sort)


def render_print_request_form(dq_id: int, club: str | None, sort: str | None) -> str:
    """The "Request a printout" button under a slip, with the are-you-sure question.

    The question is a browser confirm on submit; a phone without scripts sends the
    request straight away (the request is harmless and the admin still decides to print).
    """
    question = json.dumps(constants.PRINT_REQUEST_CONFIRM_TEXT)
    return (
        f'<form class="print-request" method="post" action="{_escape(print_request_url(dq_id, club, sort))}" '
        f'onsubmit="return window.confirm({_escape(question)})">'
        f'<button type="submit">{_escape(PRINT_REQUEST_BUTTON_LABEL)}</button>'
        f'<p class="muted">{_escape(PRINT_REQUEST_HINT)}</p></form>'
    )


def render_print_request_result(already_requested: bool, back_url: str) -> bytes:
    """The answer after a printout request: queued (or already in the queue)."""
    text = constants.PRINT_REQUEST_ALREADY_TEXT if already_requested else constants.PRINT_REQUEST_QUEUED_TEXT
    body = (
        f'<header><h1>{_escape(PRINT_REQUEST_TITLE)}</h1></header><main>'
        f'<p class="queued">\u2713 {_escape(text)}</p>'
        f'<p><a class="back" href="{_escape(back_url)}">\u2190 {_escape(BACK_TO_LIST_LABEL)}</a></p></main>'
    )
    return _render(PRINT_REQUEST_TITLE, body, refresh=False)


def normalize_sort(sort: str | None) -> str:
    """A known sort ("event" or "name"); anything else is "event"."""
    return sort if sort in constants.COACH_SORTS else constants.COACH_SORT_BY_EVENT


def _list_query(club: str | None, sort: str | None) -> str:
    """"?club=PASA&sort=name" (empty for the default view: every club, by event)."""
    values = {}
    if club:
        values[constants.COACH_QUERY_KEY_CLUB] = club
    if normalize_sort(sort) != constants.COACH_SORT_BY_EVENT:
        values[constants.COACH_QUERY_KEY_SORT] = normalize_sort(sort)
    return ("?" + urlencode(values)) if values else ""


def list_url(club: str | None, sort: str | None = None) -> str:
    """The list's address, keeping the club filter and sort."""
    return constants.COACH_ROUTE_LIST + _list_query(club, sort)


def dq_url(dq_id: int, club: str | None, sort: str | None = None) -> str:
    """One DQ's slip, remembering the club filter and sort for the way back."""
    return f"{constants.COACH_ROUTE_DQ}{dq_id}" + _list_query(club, sort)


def swimmer_sort_key(dq: dict[str, Any]) -> tuple[bool, str, str]:
    """Swimmers by last name, then whole name; relays ("PASA-A") after the swimmers."""
    name = (dq.get("swimmer") or "").strip()
    is_relay = bool(dq.get("relay_leg")) or RELAY_NAME_PATTERN.match(name) is not None
    lowered = name.lower()
    return (is_relay or not name, lowered.split()[-1] if lowered else "", lowered)


def _render(title: str, body: str, refresh: bool) -> bytes:
    """Fill in the page template."""
    template = string.Template(COACH_TEMPLATE_PATH.read_text("utf-8"))
    refresh_tag = f'<meta http-equiv="refresh" content="{constants.COACH_PAGE_REFRESH_SECONDS}">' if refresh else ""
    return template.substitute(title=_escape(title), body=body, refresh=refresh_tag).encode("utf-8")


def render_login_page(meet_name: str | None, wrong_password: bool = False) -> bytes:
    """The password form (shown until the phone has signed in once)."""
    error = f'<p class="error">{_escape(WRONG_PASSWORD_TEXT)}</p>' if wrong_password else ""
    body = (
        f"<header><h1>{_escape(meet_name or PAGE_TITLE)}</h1><div class=\"muted\">DQ list for coaches</div></header>"
        f'<main><form method="post" action="{constants.COACH_ROUTE_LOGIN}">{error}'
        f'<label for="password">Meet password</label>'
        f'<input id="password" name="{constants.COACH_FORM_FIELD_PASSWORD}" autocomplete="off" autocapitalize="none" '
        f'autocorrect="off" spellcheck="false" maxlength="40" autofocus>'
        f'<button type="submit">Show DQs</button></form>'
        f'<p class="muted">Scanning the QR code at the admin table signs you in without typing.</p></main>'
    )
    return _render(LOGIN_TITLE, body, refresh=False)


def _event_title(dq: dict[str, Any]) -> str:
    """"Event 12 Girls 10 & Under 50 Breaststroke" (or "Event 12" without the meet file)."""
    number = dq.get("event")
    if not number:
        return UNKNOWN_EVENT_LABEL
    label = dq.get("event_label")
    return EVENT_WITH_LABEL_FORMAT.format(number=number, label=label) if label else EVENT_HEADING_FORMAT.format(number=number)


def _render_dq(dq: dict[str, Any], club: str | None, sort: str, now: datetime) -> str:
    """One DQ row (a link to its slip).

    Grouped by event, the row names the swimmer and club; grouped by swimmer
    (the heading already names them), it names the event instead.
    """
    swimmer = dq.get("swimmer") or ""
    if dq.get("relay_leg"):
        swimmer = RELAY_LEG_FORMAT.format(swimmer=swimmer, leg=dq["relay_leg"])
    if sort == constants.COACH_SORT_BY_NAME:
        who = f'<span class="who">{_escape(_event_title(dq))}</span>'
    else:
        who = f'<span class="who">{_escape(swimmer)} <span class="muted">{_escape(dq.get("club"))}</span></span>'
    label, css_class = COACH_STATUS.get(dq["state"], COACH_STATUS[constants.DQ_STATE_NOTIFIED])
    status = [f'<span class="{css_class}">{_escape(label)}</span>']
    deadline = _parse_moment(dq.get("protest_deadline"))
    if deadline is not None and dq["state"] in (constants.DQ_STATE_NOTIFIED, constants.DQ_STATE_UPHELD) and deadline > _now_like(deadline, now):
        status.append(_escape(PROTEST_OPEN_FORMAT.format(time=_clock(deadline))))
    if dq.get("print_requested_at"):
        status.append(_escape(PRINTOUT_QUEUED_LABEL))
    row_class = "dq " + (OVERTURNED_CSS_CLASS if dq["state"] == constants.DQ_STATE_OVERTURNED else "")
    return (
        f'<a class="{row_class.strip()}" href="{_escape(dq_url(dq["id"], club, sort))}">'
        f'<div class="line1">{who}'
        f'<span class="where">{_escape(WHERE_FORMAT.format(heat=dq.get("heat") or "?", lane=dq.get("lane") or "?"))} '
        f'<span class="chevron">›</span></span></div>'
        f'<div class="what">{_escape(infraction_text(dq))}</div>'
        f'<div class="status">{STATUS_SEPARATOR.join(status)}</div></a>'
    )


def _render_group(heading: str, label: str | None, dqs: list[dict[str, Any]], club: str | None, sort: str, now: datetime) -> str:
    """One card: a heading (event or swimmer) and its DQ rows."""
    return (
        f'<section class="event"><h2>{_escape(heading)}'
        + (f" <span>{_escape(label)}</span>" if label else "")
        + "</h2>"
        + "".join(_render_dq(dq, club, sort, now) for dq in dqs)
        + "</section>"
    )


def _dq_count(count: int) -> str:
    """"1 DQ" / "3 DQs"."""
    return (DQ_COUNT_FORMAT if count == 1 else DQ_COUNT_PLURAL_FORMAT).format(count=count)


def render_dq_list(
    meet: dict[str, Any] | None, dqs: list[dict[str, Any]], club: str | None, now: datetime, sort: str | None = None
) -> bytes:
    """The DQ list with a club filter, by event (latest first) or by swimmer.

    Args:
        meet: The active meet (None if no meet is running).
        dqs: The meet's DQs (as ``DqStore.list_dqs`` returns them, sorted by event,
            heat, lane); only the coach-visible ones are shown.
        club: Show only this club's DQs (None = every club).
        now: The current time (for the "updated" line and protest windows).
        sort: ``constants.COACH_SORT_BY_EVENT`` (default) or ``constants.COACH_SORT_BY_NAME``
            (grouped by swimmer, A to Z by last name; with every club shown, the
            heading also names the swimmer's club).
    """
    if meet is None:
        body = f'<header><h1>{_escape(PAGE_TITLE)}</h1></header><main><p class="empty">{_escape(NO_MEET_TEXT)}</p></main>'
        return _render(PAGE_TITLE, body, refresh=True)
    sort = normalize_sort(sort)
    visible = coach_visible_dqs(dqs)
    clubs = sorted({dq["club"] for dq in visible if dq.get("club")})
    shown = [dq for dq in visible if not club or dq.get("club") == club]
    parts = [
        f'<header><h1>{_escape(meet["name"])}</h1>'
        f'<div class="muted">{_escape(UPDATED_FORMAT.format(time=_clock(now), seconds=constants.COACH_PAGE_REFRESH_SECONDS))}</div></header><main>'
    ]
    if clubs:
        chips = [f'<a class="{"on" if not club else ""}" href="{_escape(list_url(None, sort))}">{_escape(ALL_CLUBS_LABEL)}</a>']
        chips += [f'<a class="{"on" if name == club else ""}" href="{_escape(list_url(name, sort))}">{_escape(name)}</a>' for name in clubs]
        parts.append('<nav class="clubs">' + "".join(chips) + "</nav>")
    if shown:
        options = [
            f'<a class="{"on" if option == sort else ""}" href="{_escape(list_url(club, option))}">{_escape(SORT_LABELS[option])}</a>'
            for option in constants.COACH_SORTS
        ]
        parts.append(f'<nav class="clubs sort"><span class="muted">{_escape(SORT_PROMPT)}</span>' + "".join(options) + "</nav>")
    if not shown:
        text = NO_CLUB_DQS_TEXT.format(club=club) if club else NO_DQS_TEXT
        parts.append(f'<p class="empty">{_escape(text)}</p>')
    if sort == constants.COACH_SORT_BY_NAME:
        swimmers: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for dq in sorted(shown, key=swimmer_sort_key):  # stable: each swimmer's DQs stay in event order
            swimmers.setdefault((dq.get("swimmer") or "", dq.get("club") or ""), []).append(dq)
        for (swimmer, swimmer_club), swimmer_dqs in swimmers.items():
            count = _dq_count(len(swimmer_dqs))
            label = count if club or not swimmer_club else f"{swimmer_club}{STATUS_SEPARATOR}{count}"
            parts.append(_render_group(swimmer or "?", label, swimmer_dqs, club, sort, now))
    else:
        events: dict[str, list[dict[str, Any]]] = {}
        for dq in shown:
            events.setdefault(dq.get("event") or "", []).append(dq)
        for event, event_dqs in reversed(list(events.items())):  # latest events first: what coaches are waiting for
            heading = EVENT_HEADING_FORMAT.format(number=event) if event else UNKNOWN_EVENT_LABEL
            parts.append(_render_group(heading, event_dqs[0].get("event_label"), event_dqs, club, sort, now))
    parts.append("</main>")
    return _render(meet["name"], "".join(parts), refresh=True)
