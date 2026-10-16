# Officials roster file (format `officials-roster`, version 1)

The contract between **officials_signin** (writes it) and **dq_transcribe**
(reads it with its "Import officials" button). This file is owned by the
officials_signin side; any change bumps `version` and is recorded below.

## Where to get it

- Live: `GET http://localhost:8010/roster.json`: the **active session**.
  `?session_id=<id>` picks another session.
- Download: `GET http://localhost:8010/roster-download.json` (same content, saved as
  `officials_roster_<session date>_<session-name>.json`).

## Shape

```json
{
  "format": "officials-roster",
  "version": 1,
  "generated_at": "2026-10-16T07:45:00-07:00",
  "meet": {"name": "Candy Meet", "start_date": "2026-10-16"},
  "session": {"name": "Friday Prelims", "date": "2026-10-16", "start_time": "13:00",
              "type": "Prelims", "officials_meeting_time": "12:00"},
  "officials": [
    {
      "name": "Pat Example",
      "role": "Stroke & Turn Judge",
      "club": "PASA",
      "zone": "Western",
      "years_certified": 6,
      "trainee": false,
      "validated": true,
      "validation_method": "camera",
      "team": null,
      "member_id": null
    }
  ]
}
```

## Field rules

| Field | Rule |
|---|---|
| `generated_at` | Local time with UTC offset, seconds precision. |
| `session.start_time` | `HH:MM`, or `null` if not set. |
| `session.type` | Optional (added within v1). "Timed Finals", "Prelims", "Finals", "AM", "PM", "A", "B", "C", or the admin's own text; `null` if not set. |
| `session.officials_meeting_time` | Optional (added within v1). `HH:MM` or `null`. |
| `officials` | Sorted by name. An official working two roles appears **twice**, once per role. |
| `name` | As read from the USA Swimming card (title case, nickname in quotes, e.g. `Pat "Skip" Sample`) or as typed. |
| `role` | Exactly one of dq_transcribe's `MEET_ROSTER_ROLES`: "Stroke & Turn Judge", "Chief Judge", "Deck Referee", "Meet Referee", "Starter", "Relay Take-off Judge", "Admin Official". (officials_signin keeps an identical `ROSTER_ROLES`; a test fails if they drift.) |
| `club` | Club code from the card (e.g. `PASA`), or `null`. |
| `zone` | `Eastern`, `Southern`, `Central` or `Western`, worked out from the card's LSC code, or `null`. |
| `years_certified` | Whole number or `null` (typed once, then stored as a starting year so it ages automatically). |
| `trainee` | `true` for a trainee, who must be paired with a certified official. |
| `validated` | `true` once membership, background check and athlete protection training are confirmed current for the session date. |
| `validation_method` | `camera` (card read by the tablet camera, or a camera check earlier at the same meet), `visual` (admin looked at the card), `host_list` (reserved; not produced yet) or `none`. A failed camera check is `validated: false` with method `camera`. |
| `team` | `Team 1`, `Team 2`, ... (stroke & turn teams), or `null`. A trainee carries their mentor's team. |
| `team_lead` | Optional (added within v1). `true` for the team's Team Lead (at most one per team). |
| `assignment` | Optional (added within v1). `"Assistant Chief Judge"`, `"Relief"` or `"15 m"` for a job off the teams (`team` is `null`); `"15 m"` with a `team` means that member works the 15-meter mark for the team. `null` otherwise. |
| `mentor` | Optional (added within v1). For a trainee: the name of the certified official they shadow. |
| `member_id` | USA Swimming member ID or `null`. **Personal data:** never log it, never put it in commit messages or device reports. |

Validation confirms membership and safety requirements only, **not** position
certifications; the Referee assigns positions.

## Change log

- **Version 1** (2026-10-15): first version, as proposed in the handoff.
- **Version 1, additive** (2026-10-15): `session.type` and `session.officials_meeting_time`
  added. Optional keys only, so the version stays 1; readers must ignore keys they do not know.
- **Version 1, additive** (2026-10-15): per official `team_lead`, `assignment`, `mentor`
  (team builder). `role` stays one of the seven roles; ACJ, Relief and 15 m are
  `assignment` values, so dq_transcribe's role list does not change.
