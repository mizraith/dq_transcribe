"""Build balanced stroke & turn teams for a session.

How the owner's crews work (stated 2026-10-15):

- Stroke & turn judges are split into **equal teams** named "Team 1", "Team 2", ...
  Two teams are on deck at a time (one at each end of the pool) while the others
  rest, rotating every 30 minutes. Four teams give 30 on / 30 off; three teams give
  60 on / 30 off, the minimum so that everyone gets a break.
- **Team count:** whichever of 4 or 3 teams leaves the fewest officials over wins;
  on a tie, 4. So 8 judges make 4 teams of 2, 9 make 3 of 3, 13 make 4 of 3 plus
  one extra, and 15 make 3 of 5 (with "4 of 3 plus 3 extras" offered as the other
  choice). There is no limit on jurisdiction size. Fewer than 3 judges make one
  team each.
- **Seniority blocks:** sorted by years certified, most first; Team 1 gets the
  most senior block, the last team the least senior.
- **Officials left over** get jobs in this order: Assistant Chief Judge, 15 m,
  Relief. The most senior are suggested; the admin chooses who really does them.
- **15 m on every team** (optional): the least senior member of each team works
  the 15-meter mark instead of a lane jurisdiction.
- **Trainees** shadow a certified mentor on the mentor's team and do not count
  toward team size.
- **Team Lead:** none by default; the admin taps to choose.
- **Jurisdictions:** lanes are split as evenly as possible among a team's
  jurisdiction judges, never differing by more than one lane, mirrored at the
  other end (8 lanes, 3 judges: 3-3-2 at one end, 2-3-3 at the other).

Everything here is pure (no database), so it is easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from officials_signin import constants


@dataclass(frozen=True)
class Judge:
    """A certified stroke & turn judge available for teams.

    Attributes:
        signin_id: Their sign-in for this session.
        name: Display name.
        years_certified: Years certified, or None if unknown (sorted last).
    """

    signin_id: int
    name: str
    years_certified: int | None


@dataclass(frozen=True)
class Placement:
    """Where one judge goes.

    Attributes:
        signin_id: The judge's sign-in.
        team: Team name, or None for an extra job off the teams.
        assignment: ``constants.ASSIGNMENT_*`` value, or None for a lane jurisdiction.
    """

    signin_id: int
    team: str | None
    assignment: str | None


def team_name(number: int) -> str:
    """``1`` -> ``"Team 1"``."""
    return constants.TEAM_NAME_FORMAT.format(number=number)


def team_number(name: str) -> int:
    """``"Team 3"`` -> ``3`` (0 for a name without a trailing number), for sorting."""
    last_word = name.split()[-1] if name.split() else ""
    return int(last_word) if last_word.isdigit() else 0


def seniority_order(judges: list[Judge]) -> list[Judge]:
    """Most years certified first; unknown years last; ties by name."""
    return sorted(
        judges,
        key=lambda judge: (
            -(judge.years_certified if judge.years_certified is not None else constants.UNKNOWN_YEARS_SORT_VALUE),
            judge.name.lower(),
        ),
    )


def propose_team_count(judge_count: int) -> int:
    """Choose the number of teams for this many judges.

    Args:
        judge_count: Certified stroke & turn judges (trainees not counted).

    Returns:
        4 or 3 (fewest left over; 4 on a tie), or the judge count itself when
        there are fewer judges than ``constants.MIN_TEAMS_FOR_BREAKS``.
    """
    if judge_count < constants.MIN_TEAMS_FOR_BREAKS:
        return judge_count
    candidates = [count for count in constants.TEAM_COUNT_CHOICES if count <= judge_count]
    # min() keeps the first of equal values, and TEAM_COUNT_CHOICES lists 4 first.
    return min(candidates, key=lambda count: judge_count % count)


def alternative_team_count(judge_count: int, chosen: int) -> int | None:
    """The other sensible team count to offer (4 if 3 was chosen, and so on), or None."""
    others = [count for count in constants.TEAM_COUNT_CHOICES if count != chosen and count <= judge_count]
    return others[0] if others else None


def describe_layout(judge_count: int, team_count: int) -> dict[str, int]:
    """Team size and number of officials left over for a team count."""
    if team_count <= 0:
        return {constants.KEY_TEAM_SIZE: 0, constants.KEY_EXTRAS: judge_count}
    return {constants.KEY_TEAM_SIZE: judge_count // team_count, constants.KEY_EXTRAS: judge_count % team_count}


def plan_teams(judges: list[Judge], team_count: int, fifteen_meter_on_teams: bool) -> list[Placement]:
    """Place judges into equal seniority blocks, with extras for those left over.

    Args:
        judges: Certified stroke & turn judges for the session.
        team_count: Number of teams (``propose_team_count`` or the admin's choice).
        fifteen_meter_on_teams: Put the least senior member of each team on the 15 m mark.

    Returns:
        One placement per judge.
    """
    ordered = seniority_order(judges)
    team_count = max(0, min(team_count, len(ordered)))
    if team_count == 0:
        return [Placement(judge.signin_id, None, constants.ASSIGNMENT_RELIEF) for judge in ordered]
    team_size = len(ordered) // team_count
    extra_count = len(ordered) - team_size * team_count

    # Extras are the most senior (suggested ACJ first). With a 15 m judge on every
    # team, a separate 15 m extra is not needed, so that job is skipped.
    extra_jobs = [
        job
        for job in constants.LEFTOVER_ASSIGNMENT_ORDER
        if not (fifteen_meter_on_teams and job == constants.ASSIGNMENT_FIFTEEN_METER)
    ]
    placements = []
    for index, judge in enumerate(ordered[:extra_count]):
        job = extra_jobs[index] if index < len(extra_jobs) else constants.ASSIGNMENT_RELIEF
        placements.append(Placement(judge.signin_id, None, job))

    remaining = ordered[extra_count:]
    for team_index in range(team_count):
        members = remaining[team_index * team_size:(team_index + 1) * team_size]
        name = team_name(team_index + 1)
        for position, judge in enumerate(members):
            is_last = position == len(members) - 1
            on_fifteen = fifteen_meter_on_teams and is_last and len(members) > 1
            placements.append(
                Placement(judge.signin_id, name, constants.ASSIGNMENT_FIFTEEN_METER if on_fifteen else None)
            )
    return placements


def fifteen_meter_changes(signins: list[dict[str, Any]], fifteen_meter_on_teams: bool) -> dict[int, str | None]:
    """Turn "15 m on every team" on or off without rebuilding the teams.

    On: each team with two or more members and nobody on 15 m yet gets its least
    senior member (not the Team Lead) on the 15 m mark. Off: team members on 15 m
    go back to a lane jurisdiction. Extras off the teams are left alone.

    Args:
        signins: ``Database.list_signins`` for the session.
        fifteen_meter_on_teams: The new setting.

    Returns:
        ``{signin_id: new assignment}`` for the sign-ins that change.
    """
    judges = [signin for signin in signins if is_team_judge(signin) and signin[constants.KEY_TEAM]]
    if not fifteen_meter_on_teams:
        return {
            signin[constants.KEY_ID]: None
            for signin in judges
            if signin[constants.KEY_ASSIGNMENT] == constants.ASSIGNMENT_FIFTEEN_METER
        }
    rank = {judge.signin_id: index for index, judge in enumerate(seniority_order(judges_from_signins(judges)))}
    changes: dict[int, str | None] = {}
    teams: dict[str, list[dict[str, Any]]] = {}
    for signin in judges:
        teams.setdefault(signin[constants.KEY_TEAM], []).append(signin)
    for members in teams.values():
        if len(members) < 2 or any(member[constants.KEY_ASSIGNMENT] == constants.ASSIGNMENT_FIFTEEN_METER for member in members):
            continue
        candidates = [member for member in members if not member[constants.KEY_TEAM_LEAD]] or members
        least_senior = max(candidates, key=lambda member: rank[member[constants.KEY_ID]])
        changes[least_senior[constants.KEY_ID]] = constants.ASSIGNMENT_FIFTEEN_METER
    return changes


def assign_mentors(trainee_ids: list[int], placements: list[Placement], judges: list[Judge]) -> dict[int, int]:
    """Pair each trainee with a certified mentor on a team.

    Trainees are spread over the teams in turn (Team 1 first); on each team the
    most senior member without a trainee yet becomes the mentor.

    Args:
        trainee_ids: Sign-in IDs of trainees, in sign-in order.
        placements: Output of ``plan_teams``.
        judges: The certified judges (for seniority).

    Returns:
        ``{trainee signin_id: mentor signin_id}``; trainees are left out only
        when there is no team member at all.
    """
    seniority_rank = {judge.signin_id: rank for rank, judge in enumerate(seniority_order(judges))}
    members_by_team: dict[str, list[int]] = {}
    for placement in placements:
        if placement.team is not None:
            members_by_team.setdefault(placement.team, []).append(placement.signin_id)
    team_names = sorted(members_by_team, key=team_number)
    if not team_names:
        return {}
    mentees: dict[int, int] = {}
    mentors: dict[int, int] = {}
    for index, trainee_id in enumerate(trainee_ids):
        team = team_names[index % len(team_names)]
        by_seniority = sorted(members_by_team[team], key=lambda signin_id: seniority_rank.get(signin_id, 0))
        mentor = min(by_seniority, key=lambda signin_id: (mentees.get(signin_id, 0), seniority_rank.get(signin_id, 0)))
        mentors[trainee_id] = mentor
        mentees[mentor] = mentees.get(mentor, 0) + 1
    return mentors


def split_lanes(lane_count: int, judge_count: int) -> list[tuple[int, int]]:
    """Split lanes 1..lane_count into contiguous jurisdictions, larger ones first.

    Sizes never differ by more than one lane (8 lanes, 3 judges: 1-3, 4-6, 7-8).
    Judges beyond the number of lanes get none.

    Returns:
        ``(first lane, last lane)`` for each judge with lanes.
    """
    judges = min(judge_count, lane_count)
    if judges <= 0:
        return []
    base, larger_count = divmod(lane_count, judges)
    ranges = []
    first = 1
    for index in range(judges):
        size = base + (1 if index < larger_count else 0)
        ranges.append((first, first + size - 1))
        first += size
    return ranges


def mirror_lanes(ranges: list[tuple[int, int]], lane_count: int) -> list[tuple[int, int]]:
    """The other end of the pool: the same sizes in reverse (3-3-2 becomes 2-3-3)."""
    sizes = [last - first + 1 for first, last in reversed(ranges)]
    mirrored = []
    first = 1
    for size in sizes:
        mirrored.append((first, first + size - 1))
        first += size
    return mirrored


def jurisdiction_summary(lane_count: int, jurisdiction_judges: int) -> dict[str, Any]:
    """Lane jurisdictions for one team at either end of the pool.

    Args:
        lane_count: Lanes in the pool.
        jurisdiction_judges: Team members with lanes (members on 15 m excluded).

    Returns:
        ``{"pattern": "3-3-2 / 2-3-3", "this_end": [[1, 3], ...], "other_end": [...]}``
        (keys from ``constants.KEY_PATTERN`` and friends).
    """
    this_end = split_lanes(lane_count, jurisdiction_judges)
    other_end = mirror_lanes(this_end, lane_count)

    def sizes(ranges: list[tuple[int, int]]) -> str:
        return constants.LANE_PATTERN_SEPARATOR.join(str(last - first + 1) for first, last in ranges)

    pattern = sizes(this_end)
    if sizes(other_end) != pattern:
        pattern += constants.LANE_PATTERN_ENDS_SEPARATOR + sizes(other_end)
    return {
        constants.KEY_PATTERN: pattern,
        constants.KEY_THIS_END: [list(lanes) for lanes in this_end],
        constants.KEY_OTHER_END: [list(lanes) for lanes in other_end],
    }


def rotation_description(team_count: int) -> str:
    """How the teams take turns on deck, in words."""
    minutes = constants.ROTATION_MINUTES
    if team_count >= 4:
        return (
            f"Team 1 + Team 2 on deck, then Team 3 + Team 4; switch every {minutes} min "
            f"({minutes} on / {minutes} off)."
        )
    if team_count == 3:
        return (
            f"Team 1 + Team 2, then Team 2 + Team 3, then Team 3 + Team 1; switch every {minutes} min "
            f"({2 * minutes} on / {minutes} off)."
        )
    if team_count == 2:
        return "Both teams on deck; take breaks when you can."
    if team_count == 1:
        return "One team on deck; take breaks when you can."
    return "No stroke & turn judges signed in yet."


def is_team_judge(signin: dict[str, Any]) -> bool:
    """True for a certified stroke & turn judge (goes into teams)."""
    return constants.TEAM_POOL_ROLE in signin[constants.KEY_ROLES] and not signin[constants.KEY_TRAINEE]


def is_team_trainee(signin: dict[str, Any]) -> bool:
    """True for a stroke & turn trainee (shadows a mentor, not counted in team size)."""
    return constants.TEAM_POOL_ROLE in signin[constants.KEY_ROLES] and signin[constants.KEY_TRAINEE]


def judges_from_signins(signins: list[dict[str, Any]]) -> list[Judge]:
    """The certified stroke & turn judges among a session's sign-ins."""
    return [
        Judge(signin[constants.KEY_ID], signin[constants.KEY_NAME], signin[constants.KEY_YEARS_CERTIFIED])
        for signin in signins
        if is_team_judge(signin)
    ]


def chosen_team_count(judge_count: int, stored_team_count: int | None) -> int:
    """The admin's choice when it still fits, otherwise the proposed count."""
    if stored_team_count and 0 < stored_team_count <= judge_count:
        return stored_team_count
    return propose_team_count(judge_count)


def build_team_view(signins: list[dict[str, Any]], session: dict[str, Any]) -> dict[str, Any]:
    """Everything the Teams screen shows for one session.

    Args:
        signins: ``Database.list_signins`` for the session.
        session: ``Database.get_session`` row (lanes, team_count, fifteen_meter_on_teams, teams_built_at).

    Returns:
        A JSON-ready dictionary: settings, proposal and alternative, teams with
        members and jurisdictions, extras, judges not yet placed, trainees and
        their mentors, and the rotation in words.
    """
    lanes = session.get(constants.KEY_LANES) or constants.DEFAULT_LANES
    fifteen = bool(session.get(constants.KEY_FIFTEEN_METER_ON_TEAMS))
    judges = judges_from_signins(signins)
    judge_count = len(judges)
    proposed = propose_team_count(judge_count)
    alternative = alternative_team_count(judge_count, proposed)
    team_count = chosen_team_count(judge_count, session.get(constants.KEY_TEAM_COUNT))
    rank = {judge.signin_id: index for index, judge in enumerate(seniority_order(judges))}
    names = {signin[constants.KEY_ID]: signin[constants.KEY_NAME] for signin in signins}

    def member(signin: dict[str, Any]) -> dict[str, Any]:
        return {
            constants.KEY_ID: signin[constants.KEY_ID],
            constants.KEY_NAME: signin[constants.KEY_NAME],
            constants.KEY_YEARS_CERTIFIED: signin[constants.KEY_YEARS_CERTIFIED],
            constants.KEY_TEAM: signin[constants.KEY_TEAM],
            constants.KEY_ASSIGNMENT: signin[constants.KEY_ASSIGNMENT],
            constants.KEY_TEAM_LEAD: signin[constants.KEY_TEAM_LEAD],
        }

    team_judges = sorted((signin for signin in signins if is_team_judge(signin)), key=lambda item: rank[item[constants.KEY_ID]])
    team_names_in_use = {signin[constants.KEY_TEAM] for signin in team_judges if signin[constants.KEY_TEAM]}
    team_names = [team_name(number) for number in range(1, team_count + 1)]
    team_names += sorted(team_names_in_use - set(team_names), key=team_number)
    teams = []
    for name in team_names:
        members = [member(signin) for signin in team_judges if signin[constants.KEY_TEAM] == name]
        lane_judges = sum(1 for item in members if item[constants.KEY_ASSIGNMENT] != constants.ASSIGNMENT_FIFTEEN_METER)
        teams.append({
            constants.KEY_NAME: name,
            constants.KEY_MEMBERS: members,
            constants.KEY_JURISDICTION: jurisdiction_summary(lanes, lane_judges),
            constants.KEY_TRAINEES: [
                {
                    constants.KEY_ID: signin[constants.KEY_ID],
                    constants.KEY_NAME: signin[constants.KEY_NAME],
                    constants.KEY_MENTOR_SIGNIN_ID: signin[constants.KEY_MENTOR_SIGNIN_ID],
                    constants.KEY_MENTOR: names.get(signin[constants.KEY_MENTOR_SIGNIN_ID]),
                }
                for signin in signins
                if is_team_trainee(signin) and signin[constants.KEY_TEAM] == name
            ],
        })
    extras = [member(signin) for signin in team_judges if signin[constants.KEY_TEAM] is None and signin[constants.KEY_ASSIGNMENT]]
    unplaced = [member(signin) for signin in team_judges if signin[constants.KEY_TEAM] is None and not signin[constants.KEY_ASSIGNMENT]]
    unpaired_trainees = [
        {constants.KEY_ID: signin[constants.KEY_ID], constants.KEY_NAME: signin[constants.KEY_NAME]}
        for signin in signins
        if is_team_trainee(signin) and not signin[constants.KEY_MENTOR_SIGNIN_ID]
    ]
    return {
        constants.KEY_LANES: lanes,
        constants.KEY_LANE_CHOICES: list(constants.LANE_CHOICES),
        constants.KEY_FIFTEEN_METER_ON_TEAMS: fifteen,
        constants.KEY_JUDGE_COUNT: judge_count,
        constants.KEY_TEAM_COUNT: team_count,
        constants.KEY_PROPOSED_TEAM_COUNT: proposed,
        constants.KEY_ALTERNATIVE_TEAM_COUNT: alternative,
        constants.KEY_LAYOUTS: {
            str(count): describe_layout(judge_count, count) for count in (proposed, alternative) if count
        },
        constants.KEY_BUILT: bool(session.get(constants.KEY_TEAMS_BUILT_AT)),
        constants.KEY_TEAMS: teams,
        constants.KEY_EXTRAS: extras,
        constants.KEY_UNPLACED: unplaced,
        constants.KEY_UNPAIRED_TRAINEES: unpaired_trainees,
        constants.KEY_ROTATION: rotation_description(len([team for team in teams if team[constants.KEY_MEMBERS]])),
        constants.KEY_EXTRA_ASSIGNMENTS: list(constants.EXTRA_ASSIGNMENTS),
    }
