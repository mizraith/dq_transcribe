"""Tests for officials_signin.teams (team count, seniority blocks, extras, lanes).

The examples are the owner's own (2026-10-15).

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin
"""

from __future__ import annotations

import unittest

from officials_signin import constants
from officials_signin.teams import (
    Judge,
    alternative_team_count,
    assign_mentors,
    describe_layout,
    jurisdiction_summary,
    plan_teams,
    propose_team_count,
    rotation_description,
    seniority_order,
    split_lanes,
)


def make_judges(count: int) -> list[Judge]:
    """Judges A, B, C, ... with A the most senior (years count, count-1, ...)."""
    return [Judge(index + 1, chr(ord("A") + index), count - index) for index in range(count)]


def layout(judge_count: int) -> tuple[int, int, int]:
    """(teams, team size, extras) proposed for a number of judges."""
    teams = propose_team_count(judge_count)
    sizes = describe_layout(judge_count, teams)
    return teams, sizes[constants.KEY_TEAM_SIZE], sizes[constants.KEY_EXTRAS]


class TeamCountTests(unittest.TestCase):
    """Fewest officials left over wins; 4 teams on a tie; at least 3 teams when possible."""

    def test_owner_examples(self) -> None:
        self.assertEqual(layout(13), (4, 3, 1))  # 4 teams of 3 plus one ACJ
        self.assertEqual(layout(14), (4, 3, 2))  # 4 teams plus 2 extras
        self.assertEqual(layout(15), (3, 5, 0))  # 3 of 5 ...
        self.assertEqual(alternative_team_count(15, 3), 4)  # ... or 4 of 3 plus extras, one tap away
        self.assertEqual(layout(6), (3, 2, 0))  # 3 teams of 2, even with 10 lanes
        self.assertEqual(layout(2), (2, 1, 0))  # stuck with two teams of 1
        self.assertEqual(layout(8), (4, 2, 0))  # 4 teams of 2 ...
        self.assertEqual(layout(9), (3, 3, 0))  # ... or 3 of 3 when a 9th shows up

    def test_ties_go_to_four_teams(self) -> None:
        self.assertEqual(layout(12), (4, 3, 0))
        self.assertEqual(layout(16), (4, 4, 0))

    def test_tiny_and_empty_pools(self) -> None:
        self.assertEqual(propose_team_count(0), 0)
        self.assertEqual(propose_team_count(1), 1)
        self.assertIsNone(alternative_team_count(2, 2))


class PlanTests(unittest.TestCase):
    """Seniority blocks, extras and the 15 m option."""

    def test_blocks_by_seniority_with_senior_acj(self) -> None:
        placements = {placement.signin_id: placement for placement in plan_teams(make_judges(13), 4, False)}
        self.assertEqual(placements[1].assignment, constants.ASSIGNMENT_ACJ)  # A, most senior
        self.assertIsNone(placements[1].team)
        self.assertEqual([placements[index].team for index in (2, 3, 4)], ["Team 1"] * 3)
        self.assertEqual([placements[index].team for index in (11, 12, 13)], ["Team 4"] * 3)

    def test_extras_in_order_acj_fifteen_relief(self) -> None:
        extras = [placement.assignment for placement in plan_teams(make_judges(15), 4, False) if placement.team is None]
        self.assertEqual(extras, [constants.ASSIGNMENT_ACJ, constants.ASSIGNMENT_FIFTEEN_METER, constants.ASSIGNMENT_RELIEF])

    def test_fifteen_meter_on_every_team(self) -> None:
        placements = plan_teams(make_judges(14), 4, True)
        on_fifteen = [placement for placement in placements if placement.team and placement.assignment]
        self.assertEqual(len(on_fifteen), 4)
        self.assertTrue(all(placement.assignment == constants.ASSIGNMENT_FIFTEEN_METER for placement in on_fifteen))
        # The separate 15 m extra is skipped: extras are ACJ then Relief.
        extras = [placement.assignment for placement in placements if placement.team is None]
        self.assertEqual(extras, [constants.ASSIGNMENT_ACJ, constants.ASSIGNMENT_RELIEF])
        # The least senior member of Team 1 (D, signin 4... B C D are Team 1) is on 15 m.
        team_one = [placement for placement in placements if placement.team == "Team 1"]
        self.assertEqual(team_one[-1].assignment, constants.ASSIGNMENT_FIFTEEN_METER)

    def test_unknown_years_sort_last(self) -> None:
        judges = [Judge(1, "New", None), Judge(2, "Veteran", 20), Judge(3, "Mid", 5)]
        self.assertEqual([judge.name for judge in seniority_order(judges)], ["Veteran", "Mid", "New"])

    def test_every_judge_placed_once(self) -> None:
        for count in range(1, 20):
            placements = plan_teams(make_judges(count), propose_team_count(count), False)
            self.assertEqual(sorted(placement.signin_id for placement in placements), list(range(1, count + 1)))


class MentorTests(unittest.TestCase):
    """Trainees shadow a certified mentor."""

    def test_trainees_spread_over_teams_with_senior_mentors(self) -> None:
        judges = make_judges(12)
        placements = plan_teams(judges, 4, False)
        mentors = assign_mentors([101, 102, 103, 104, 105], placements, judges)
        team_of = {placement.signin_id: placement.team for placement in placements}
        self.assertEqual([team_of[mentors[trainee]] for trainee in (101, 102, 103, 104, 105)],
                         ["Team 1", "Team 2", "Team 3", "Team 4", "Team 1"])
        self.assertEqual(mentors[101], 1)  # most senior on Team 1
        self.assertEqual(mentors[105], 2)  # next mentor on Team 1, not a double load

    def test_no_teams_no_mentors(self) -> None:
        self.assertEqual(assign_mentors([101], [], []), {})


class LaneTests(unittest.TestCase):
    """Jurisdictions never differ by more than one lane, mirrored at the other end."""

    def test_eight_lanes_three_judges(self) -> None:
        summary = jurisdiction_summary(8, 3)
        self.assertEqual(summary[constants.KEY_PATTERN], "3-3-2 / 2-3-3")
        self.assertEqual(summary[constants.KEY_THIS_END], [[1, 3], [4, 6], [7, 8]])
        self.assertEqual(summary[constants.KEY_OTHER_END], [[1, 2], [3, 5], [6, 8]])

    def test_even_split_is_one_pattern(self) -> None:
        self.assertEqual(jurisdiction_summary(10, 2)[constants.KEY_PATTERN], "5-5")

    def test_more_judges_than_lanes(self) -> None:
        self.assertEqual(split_lanes(2, 3), [(1, 1), (2, 2)])
        self.assertEqual(split_lanes(8, 0), [])


class RotationTests(unittest.TestCase):
    """Rotation text matches the team count."""

    def test_rotation_texts(self) -> None:
        self.assertIn("30 on / 30 off", rotation_description(4))
        self.assertIn("60 on / 30 off", rotation_description(3))
        self.assertIn("breaks when you can", rotation_description(2))


if __name__ == "__main__":
    unittest.main()
