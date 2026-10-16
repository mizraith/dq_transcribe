"""The coach page's HTML: the posted DQ list by event, and the password form.

Coaches open it on their phones over the meet Wi-Fi (see ``coach_server``). It
shows only what a coach would get on paper: each DQ's event, heat, lane,
swimmer, club, infractions and status, and (tapping a DQ) the slip itself. It
never shows audio, transcripts, notes or DQs the coach has not been told about.

Which DQs: those of the active meet whose state is one of
``constants.DQ_STATES_AFTER_NOTIFICATION`` (notified, protested, upheld,
overturned), not in the trash. Overturned DQs stay on the list, struck through,
so a coach sees the ruling.

The page is plain HTML that reloads itself every
``constants.COACH_PAGE_REFRESH_SECONDS``: no script, so any phone browser works.
"""

from __future__ import annotations

import html
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


def list_url(club: str | None) -> str:
    """The list's address, keeping the club filter."""
    return constants.COACH_ROUTE_LIST + (("?" + urlencode({constants.COACH_QUERY_KEY_CLUB: club})) if club else "")


def dq_url(dq_id: int, club: str | None) -> str:
    """One DQ's slip, remembering the club filter for the way back."""
    return f"{constants.COACH_ROUTE_DQ}{dq_id}" + (("?" + urlencode({constants.COACH_QUERY_KEY_CLUB: club})) if club else "")


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


def _render_dq(dq: dict[str, Any], club: str | None, now: datetime) -> str:
    """One DQ row (a link to its slip)."""
    swimmer = dq.get("swimmer") or ""
    if dq.get("relay_leg"):
        swimmer = RELAY_LEG_FORMAT.format(swimmer=swimmer, leg=dq["relay_leg"])
    label, css_class = COACH_STATUS.get(dq["state"], COACH_STATUS[constants.DQ_STATE_NOTIFIED])
    status = [f'<span class="{css_class}">{_escape(label)}</span>']
    deadline = _parse_moment(dq.get("protest_deadline"))
    if deadline is not None and dq["state"] in (constants.DQ_STATE_NOTIFIED, constants.DQ_STATE_UPHELD) and deadline > _now_like(deadline, now):
        status.append(_escape(PROTEST_OPEN_FORMAT.format(time=_clock(deadline))))
    row_class = "dq " + (OVERTURNED_CSS_CLASS if dq["state"] == constants.DQ_STATE_OVERTURNED else "")
    return (
        f'<a class="{row_class.strip()}" href="{_escape(dq_url(dq["id"], club))}">'
        f'<div class="line1"><span class="who">{_escape(swimmer)} <span class="muted">{_escape(dq.get("club"))}</span></span>'
        f'<span class="where">{_escape(WHERE_FORMAT.format(heat=dq.get("heat") or "?", lane=dq.get("lane") or "?"))} '
        f'<span class="chevron">›</span></span></div>'
        f'<div class="what">{_escape(infraction_text(dq))}</div>'
        f'<div class="status">{STATUS_SEPARATOR.join(status)}</div></a>'
    )


def render_dq_list(meet: dict[str, Any] | None, dqs: list[dict[str, Any]], club: str | None, now: datetime) -> bytes:
    """The DQ list by event, newest events first, with a club filter.

    Args:
        meet: The active meet (None if no meet is running).
        dqs: The meet's DQs (as ``DqStore.list_dqs`` returns them, sorted by event,
            heat, lane); only the coach-visible ones are shown.
        club: Show only this club's DQs (None = every club).
        now: The current time (for the "updated" line and protest windows).
    """
    if meet is None:
        body = f'<header><h1>{_escape(PAGE_TITLE)}</h1></header><main><p class="empty">{_escape(NO_MEET_TEXT)}</p></main>'
        return _render(PAGE_TITLE, body, refresh=True)
    visible = coach_visible_dqs(dqs)
    clubs = sorted({dq["club"] for dq in visible if dq.get("club")})
    shown = [dq for dq in visible if not club or dq.get("club") == club]
    parts = [
        f'<header><h1>{_escape(meet["name"])}</h1>'
        f'<div class="muted">{_escape(UPDATED_FORMAT.format(time=_clock(now), seconds=constants.COACH_PAGE_REFRESH_SECONDS))}</div></header><main>'
    ]
    if clubs:
        chips = [f'<a class="{"on" if not club else ""}" href="{_escape(list_url(None))}">{_escape(ALL_CLUBS_LABEL)}</a>']
        chips += [f'<a class="{"on" if name == club else ""}" href="{_escape(list_url(name))}">{_escape(name)}</a>' for name in clubs]
        parts.append('<nav class="clubs">' + "".join(chips) + "</nav>")
    if not shown:
        text = NO_CLUB_DQS_TEXT.format(club=club) if club else NO_DQS_TEXT
        parts.append(f'<p class="empty">{_escape(text)}</p>')
    events: dict[str, list[dict[str, Any]]] = {}
    for dq in shown:
        events.setdefault(dq.get("event") or "", []).append(dq)
    for event, event_dqs in reversed(list(events.items())):  # latest events first: what coaches are waiting for
        heading = EVENT_HEADING_FORMAT.format(number=event) if event else UNKNOWN_EVENT_LABEL
        label = event_dqs[0].get("event_label")
        parts.append(
            f'<section class="event"><h2>{_escape(heading)}'
            + (f" <span>{_escape(label)}</span>" if label else "")
            + "</h2>"
            + "".join(_render_dq(dq, club, now) for dq in event_dqs)
            + "</section>"
        )
    parts.append("</main>")
    return _render(meet["name"], "".join(parts), refresh=True)
