"""Printable pages: session summary, meet summary, and the team display.

All three are plain HTML built here (every value escaped) with the shared
``web/print.css`` stylesheet, so the browser's own Print works (one page for a
session or for the teams; the meet summary flows sessions one after another to
save paper). The team display also works as a big-screen page that officials
photograph with their phones.

Member IDs never appear on any printout.
"""

from __future__ import annotations

from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

from officials_signin import constants
from officials_signin.teams import format_slot_time

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{stylesheet}">
</head>
<body class="{body_class}">
<div class="toolbar"><button type="button" onclick="window.print()">Print</button>{extra_links}<a href="{back_route}">{back_label}</a></div>
{body}
<div class="footer">Printed {printed}</div>
</body>
</html>
"""
_WEEKDAY_FORMAT = "%A %b"
_PRINTED_DATE_FORMAT = "%Y-%m-%d"
_CLOCK_FORMAT = "%H:%M"
_NO_VALUE = "—"


_STANDALONE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{stylesheet}
</style>
</head>
<body class="{body_class}">
{body}
<div class="footer">Saved {printed}</div>
</body>
</html>
"""
_STYLESHEET_PATH = Path(__file__).parent / "web" / constants.PRINT_STYLESHEET_FILENAME


def _page(
    title: str,
    body: str,
    body_class: str = "",
    extra_links: str = "",
    standalone: bool = False,
    back_route: str = constants.ROUTE_OFFICIALS_PAGE,
    back_label: str = "Back to sign-in",
) -> bytes:
    """Wrap a page body in the shared HTML shell.

    Args:
        title: Page title.
        body: The page body (already escaped HTML).
        body_class: CSS class for ``<body>``.
        extra_links: More toolbar links, as HTML.
        back_route: Where the toolbar's "back" link goes (the page that opened this one).
        back_label: Its text.
        standalone: For a saved file (the meet zip): the stylesheet inside the page and
            no toolbar, so it opens on any computer without the app.
    """
    if standalone:
        return _STANDALONE_PAGE.format(
            title=escape(title),
            stylesheet=_STYLESHEET_PATH.read_text(encoding="utf-8"),
            body_class=body_class,
            body=body,
            printed=escape(_printed_now()),
        ).encode("utf-8")
    return _PAGE.format(
        extra_links=extra_links,
        back_route=back_route,
        back_label=escape(back_label),
        title=escape(title),
        stylesheet=constants.ROUTE_PRINT_STYLESHEET,
        body_class=body_class,
        body=body,
        printed=escape(_printed_now()),
    ).encode("utf-8")


def _day(iso_date: str) -> str:
    """``2026-10-16`` -> ``Friday Oct 16, 2026`` (no platform-specific format codes)."""
    day = date.fromisoformat(iso_date)
    return f"{day.strftime(_WEEKDAY_FORMAT)} {day.day}, {day.year}"


def _printed_now() -> str:
    """Now as ``2026-10-16 1:05 PM``."""
    now = datetime.now()
    return f"{now.strftime(_PRINTED_DATE_FORMAT)} {format_slot_time(now.strftime(_CLOCK_FORMAT), 0)}"


def _time(hours_minutes: str | None) -> str | None:
    """``13:00`` -> ``1:00 PM`` (None stays None)."""
    return None if not hours_minutes else format_slot_time(hours_minutes, 0)


def session_subtitle(session: dict[str, Any], signin_count: int) -> str:
    """One line describing a session: day, start, officials meeting, how many signed in."""
    parts = [_day(session[constants.KEY_DATE])]
    if session.get(constants.KEY_START_TIME):
        parts.append("starts " + _time(session[constants.KEY_START_TIME]))
    if session.get(constants.KEY_OFFICIALS_MEETING_TIME):
        parts.append("officials meeting " + _time(session[constants.KEY_OFFICIALS_MEETING_TIME]))
    parts.append(f"{signin_count} official{'' if signin_count == 1 else 's'}")
    return " · ".join(parts)


def placement_text(signin: dict[str, Any], names_by_id: dict[int, str]) -> str:
    """Team or job for one sign-in, e.g. ``Team 2 ★``, ``Team 1, 15 m``, ``Relief``."""
    team = signin.get(constants.KEY_TEAM)
    assignment = signin.get(constants.KEY_ASSIGNMENT)
    if team:
        text = team
        if assignment:
            text += ", " + assignment
        if signin.get(constants.KEY_TEAM_LEAD):
            text += " ★"
    else:
        text = assignment or ""
    mentor = names_by_id.get(signin.get(constants.KEY_MENTOR_SIGNIN_ID))
    if mentor:
        text += f" (with {mentor})"
    return text


def check_text(signin: dict[str, Any]) -> str:
    """How the official was checked: ``✓ card``, ``✓ admin`` or what still needs the admin."""
    if signin[constants.KEY_VALIDATED]:
        return "✓ admin" if signin[constants.KEY_VALIDATION_METHOD] == constants.VALIDATION_VISUAL else "✓ card"
    return "Needs admin"


def _session_table(signins: list[dict[str, Any]], compact: bool) -> str:
    """The officials of one session as an HTML table, sorted by name."""
    names_by_id = {signin[constants.KEY_ID]: signin[constants.KEY_NAME] for signin in signins}
    ordered = sorted(signins, key=lambda signin: signin[constants.KEY_NAME].lower())
    # Club right after the name, to help look people up (owner, 2026-10-16); LSC, not zone.
    if compact:
        header = "<tr><th class='number'>#</th><th>Name</th><th>Club</th><th>Role(s)</th><th>Team / job</th></tr>"
    else:
        header = (
            "<tr><th class='number'>#</th><th>Name</th><th>Club</th><th>Role(s)</th><th>Team / job</th>"
            "<th>LSC</th><th class='number'>Yrs</th><th>Check</th></tr>"
        )
    rows = []
    for number, signin in enumerate(ordered, start=1):
        roles = ", ".join(signin[constants.KEY_ROLES])
        if signin[constants.KEY_TRAINEE]:
            roles += " (trainee)"
        cells = [
            f"<td class='number'>{number}</td>",
            f"<td>{escape(signin[constants.KEY_NAME])}</td>",
            f"<td>{escape(signin[constants.KEY_CLUB] or _NO_VALUE)}</td>",
            f"<td>{escape(roles)}</td>",
            f"<td class='wrap'>{escape(placement_text(signin, names_by_id)) or _NO_VALUE}</td>",
        ]
        if not compact:
            years = signin[constants.KEY_YEARS_CERTIFIED]
            check = check_text(signin)
            cells += [
                f"<td>{escape(signin[constants.KEY_LSC] or _NO_VALUE)}</td>",
                f"<td class='number'>{_NO_VALUE if years is None else years}</td>",
                f"<td class='{'' if signin[constants.KEY_VALIDATED] else 'needs'}'>{escape(check)}</td>",
            ]
        rows.append("<tr>" + "".join(cells) + "</tr>")
    if not rows:
        rows.append("<tr><td colspan='8'>Nobody signed in.</td></tr>")
    table_class = "compact" if compact else ("dense" if len(ordered) > constants.PRINT_DENSE_ROW_COUNT else "")
    return f"<table class='{table_class}'><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table>"


def render_session_summary(
    meet: dict[str, Any], session: dict[str, Any], signins: list[dict[str, Any]], standalone: bool = False
) -> bytes:
    """One page: every official of a session with role, team or job, club, zone, years and check.

    Args:
        meet: The meet (name, start_date).
        session: The session row.
        signins: ``Database.list_signins`` for the session.
        standalone: A self-contained file for the meet zip (see ``_page``).

    Returns:
        The HTML page.
    """
    title = f"{meet[constants.KEY_NAME]}: {session[constants.KEY_NAME]}"
    body = (
        f"<h1>{escape(title)}</h1>"
        f"<p class='subtitle'>{escape(session_subtitle(session, len(signins)))}</p>"
        f"{_session_table(signins, compact=False)}"
    )
    return _page(title + " (officials)", body, standalone=standalone)


def render_meet_summary(
    meet: dict[str, Any], sessions: list[tuple[dict[str, Any], list[dict[str, Any]]]], standalone: bool = False
) -> bytes:
    """Every session of a meet, one after another (no page per session), compact tables.

    Args:
        meet: The meet.
        sessions: ``(session, signins)`` pairs in session order.
        standalone: A self-contained file for the meet zip (see ``_page``).

    Returns:
        The HTML page.
    """
    blocks = []
    for session, signins in sessions:
        blocks.append(
            "<div class='session-block'>"
            f"<h2>{escape(session[constants.KEY_NAME])}</h2>"
            f"<p class='subtitle'>{escape(session_subtitle(session, len(signins)))}</p>"
            f"{_session_table(signins, compact=True)}"
            "</div>"
        )
    people = {signin[constants.KEY_OFFICIAL_ID] for _, signins in sessions for signin in signins}
    body = (
        f"<h1>{escape(meet[constants.KEY_NAME])}: officials</h1>"
        f"<p class='subtitle'>Starts {escape(_day(meet[constants.KEY_START_DATE]))} · {len(sessions)} session"
        f"{'' if len(sessions) == 1 else 's'} · {len(people)} different officials</p>"
        + "".join(blocks)
    )
    return _page(meet[constants.KEY_NAME] + " (meet summary)", body, standalone=standalone)


def render_team_display(
    meet: dict[str, Any],
    session: dict[str, Any],
    view: dict[str, Any],
    signin_count: int | None = None,
    standalone: bool = False,
) -> bytes:
    """Big-screen team page (fits one printed page): teams, jobs off the teams, jurisdiction, rotation.

    Args:
        meet: The meet.
        session: The session row.
        view: ``teams.build_team_view`` for the session.
        signin_count: Everyone signed in to the session (default: those shown on the page).
        standalone: A self-contained file for the meet zip (see ``_page``).

    Returns:
        The HTML page.
    """
    cards = []
    for team in view[constants.KEY_TEAMS]:
        if not team[constants.KEY_MEMBERS]:
            continue
        items = []
        for member in team[constants.KEY_MEMBERS]:
            name = escape(member[constants.KEY_NAME])
            extras = ""
            if member[constants.KEY_TEAM_LEAD]:
                name = f"<span class='lead'>★ {name}</span>"
            if member[constants.KEY_ASSIGNMENT]:
                extras = f"<span class='tag'>{escape(member[constants.KEY_ASSIGNMENT])}</span>"
            items.append(f"<li>{name}{extras}</li>")
        for trainee in team[constants.KEY_TRAINEES]:
            mentor = trainee.get(constants.KEY_MENTOR)
            suffix = f" (with {escape(mentor)})" if mentor else ""
            items.append(f"<li class='trainee'>↳ {escape(trainee[constants.KEY_NAME])}, trainee{suffix}</li>")
        cards.append(f"<div class='team'><h2>{escape(team[constants.KEY_NAME])}</h2><ul>{''.join(items)}</ul></div>")
    if view[constants.KEY_EXTRAS]:
        items = "".join(
            f"<li>{escape(member[constants.KEY_NAME])}<span class='tag'>{escape(member[constants.KEY_ASSIGNMENT])}</span></li>"
            for member in view[constants.KEY_EXTRAS]
        )
        cards.append(f"<div class='team'><h2>Off the teams</h2><ul>{items}</ul></div>")
    if not cards:
        cards.append("<p>No teams yet. Open Teams on the sign-in page to build them.</p>")
    schedule_rows = "".join(
        f"<tr><td>{escape(row[constants.KEY_TIME])}</td><td>{escape(_team_number(row[constants.KEY_START_END_TEAM]))}</td>"
        f"<td>{escape(_team_number(row[constants.KEY_TURN_END_TEAM]))}</td></tr>"
        for row in view[constants.KEY_ROTATION_SCHEDULE]
    )
    schedule = (
        "<table class='rotation-table'><thead><tr><th>Time</th><th>S</th><th>T</th></tr></thead>"
        f"<tbody>{schedule_rows}</tbody></table>"
        if schedule_rows else ""
    )
    # With 3 or more teams the ends matter: say which way first, in bold, then explain.
    active_teams = sum(1 for team in view[constants.KEY_TEAMS] if team[constants.KEY_MEMBERS])
    mode = view.get(constants.KEY_ROTATION_MODE) or constants.DEFAULT_ROTATION_MODE
    mode_label = (
        f"<strong>{escape(constants.ROTATION_MODE_LABELS[mode])}</strong> · "
        if active_teams >= constants.MIN_TEAMS_FOR_BREAKS else ""
    )
    title = f"{meet[constants.KEY_NAME]}: {session[constants.KEY_NAME]} teams"
    if signin_count is None:
        signin_count = len(view[constants.KEY_EXTRAS]) + sum(
            len(team[constants.KEY_MEMBERS]) + len(team[constants.KEY_TRAINEES]) for team in view[constants.KEY_TEAMS]
        )
    subtitle = session_subtitle(session, signin_count)
    body = (
        f"<h1>{escape(session[constants.KEY_NAME])}: teams</h1>"
        f"<p class='subtitle'>{escape(meet[constants.KEY_NAME])} · {escape(subtitle)} · {view[constants.KEY_LANES]} lanes</p>"
        f"<p class='subtitle rotation-line'>{mode_label}{escape(view[constants.KEY_ROTATION])}</p>"
        f"<div class='display-columns'><div><div class='team-grid'>{''.join(cards)}</div>{jurisdiction_box(view)}</div>"
        f"<div><h2 class='rotation-heading'>Rotation</h2><p class='rotation-key'>S = start end, T = turn end</p>"
        f"{schedule}</div></div>"
    )
    back_to_teams = (
        f"<a href='{constants.ROUTE_OFFICIALS_PAGE}?{constants.OPEN_QUERY_KEY}={constants.OPEN_TEAMS_VALUE}'>Back to Teams</a>"
    )
    return _page(title, body, body_class="display", extra_links=back_to_teams, standalone=standalone)


def _coaches_table(coaches: list[dict[str, Any]], compact: bool) -> str:
    """Coaches of one session, sorted by club (head coaches first in each club), as a table."""
    ordered = sorted(
        coaches,
        key=lambda coach: ((coach[constants.KEY_CLUB] or "~").lower(), not coach[constants.KEY_HEAD_COACH],
                           coach[constants.KEY_NAME].lower()),
    )
    header = (
        "<tr><th>Name</th><th>Club</th><th>LSC</th><th>Head coach</th>" + ("" if compact else "<th>Check</th>") + "</tr>"
    )
    rows = []
    for coach in ordered:
        cells = [
            f"<td>{escape(coach[constants.KEY_NAME])}</td>",
            f"<td>{escape(coach[constants.KEY_CLUB] or _NO_VALUE)}</td>",
            f"<td>{escape(coach[constants.KEY_LSC] or _NO_VALUE)}</td>",
            f"<td>{'★ Head coach' if coach[constants.KEY_HEAD_COACH] else ''}</td>",
        ]
        if not compact:
            needs = "" if coach[constants.KEY_VALIDATED] else "needs"
            cells.append(f"<td class='{needs}'>{escape(check_text(coach))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    if not rows:
        rows.append("<tr><td colspan='5'>No coaches signed in.</td></tr>")
    return f"<table class='{'compact' if compact else ''}'><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table>"


def _coach_counts_text(coaches: list[dict[str, Any]]) -> str:
    """``12 coaches · 4 head coaches · 6 clubs``."""
    heads = sum(1 for coach in coaches if coach[constants.KEY_HEAD_COACH])
    clubs = len({coach[constants.KEY_CLUB] for coach in coaches if coach[constants.KEY_CLUB]})
    return (
        f"{len(coaches)} coach{'' if len(coaches) == 1 else 'es'} · {heads} head coach{'' if heads == 1 else 'es'}"
        f" · {clubs} club{'' if clubs == 1 else 's'}"
    )


def render_coaches_session(
    meet: dict[str, Any], session: dict[str, Any], coaches: list[dict[str, Any]], standalone: bool = False
) -> bytes:
    """One page: the coaches of a session, by club, head coaches marked.

    Args:
        meet: The meet.
        session: The session row.
        coaches: ``coaches.list_coach_signins`` for the session.
        standalone: A self-contained file for the meet zip (see ``_page``).

    Returns:
        The HTML page.
    """
    title = f"{meet[constants.KEY_NAME]}: {session[constants.KEY_NAME]}"
    subtitle = session_subtitle(session, len(coaches)).rsplit(" · ", 1)[0] + " · " + _coach_counts_text(coaches)
    body = f"<h1>{escape(title)}: coaches</h1><p class='subtitle'>{escape(subtitle)}</p>{_coaches_table(coaches, compact=False)}"
    return _page(title + " (coaches)", body, standalone=standalone,
                 back_route=constants.ROUTE_COACHES, back_label="Back to coaches")


def render_coaches_meet(
    meet: dict[str, Any], sessions: list[tuple[dict[str, Any], list[dict[str, Any]]]], standalone: bool = False
) -> bytes:
    """Every session's coaches, one after another (no page per session).

    Args:
        meet: The meet.
        sessions: ``(session, coach sign-ins)`` pairs in session order.
        standalone: A self-contained file for the meet zip (see ``_page``).

    Returns:
        The HTML page.
    """
    blocks = [
        "<div class='session-block'>"
        f"<h2>{escape(session[constants.KEY_NAME])}</h2>"
        f"<p class='subtitle'>{escape(_day(session[constants.KEY_DATE]))} · {escape(_coach_counts_text(coaches))}</p>"
        f"{_coaches_table(coaches, compact=True)}</div>"
        for session, coaches in sessions
    ]
    body = f"<h1>{escape(meet[constants.KEY_NAME])}: coaches</h1>" + "".join(blocks)
    return _page(meet[constants.KEY_NAME] + " (coaches)", body, standalone=standalone,
                 back_route=constants.ROUTE_COACHES, back_label="Back to coaches")


def jurisdiction_box(view: dict[str, Any]) -> str:
    """The Jurisdiction box for the team page: lanes at the start and turn ends.

    For example "Start end 1-8: 3-3-2" and "Turn end 1-8: 2-3-3" (prefixed with
    "Teams of N" when teams differ in size). Empty when there are no teams yet.
    """
    entries = view.get(constants.KEY_JURISDICTIONS) or []
    if not entries:
        return ""
    lines = []
    for entry in entries:
        prefix = f"<div class='jurisdiction-size'>Teams of {entry[constants.KEY_JUDGE_COUNT]}</div>" if len(entries) > 1 else ""
        lanes = escape(entry[constants.KEY_LANE_RANGE])
        lines.append(
            f"{prefix}<div>Start end {lanes}: <strong>{escape(entry[constants.KEY_START_END])}</strong></div>"
            f"<div>Turn end {lanes}: <strong>{escape(entry[constants.KEY_TURN_END])}</strong></div>"
        )
    return f"<div class='jurisdiction'><h2 class='rotation-heading'>Jurisdiction</h2>{''.join(lines)}</div>"


def _team_number(name: str | None) -> str:
    """``Team 3`` -> ``3``; None -> a dash."""
    return _NO_VALUE if not name else name.split()[-1]
