# Handoff for the DQ Transcribe chat: joining Admin Assistant

Paste this file, or point the DQ Transcribe chat at it. It was written by the Officials
Sign-In chat on 2026-10-16, when the owner (Red) asked for one suite with one main page.
Everything on the Officials Sign-In side is built and pushed. The DQ side is yours.

## What the owner asked for (his words, trimmed)

> create a home page for Admin Assistant ... the main page will be our launcher for our
> various apps AND it will contain the Meet Overview page ... When a meet is opened on the
> main page, this sets the meet and session for all open apps ... all the apps always show
> same meet and same session regardless of which app we selected that in. THE EXCEPTION to
> this is DQ_Transcribe which if recording to a meet/session will *continue* to record that
> meet session even if displaying other meet info ... The top bar will always have the
> hamburger menu on the far left, the name of the sub-app in bold, the name of the meet and
> the current active session for the meet as a drop down. Workflows ... "Transcript" "DQs"
> and "Trash" for DQ_Transcribe [can appear in the top bar] ... The hamburger [menu] will
> contain the top level items like "Meets & Main Page" ... All meet setup will be done on
> the main page. WHAT THIS MEANS for DQ Transcribe is that the left column gets simplified:
> the meet setup box goes away (and into the main page). The Audio Capture needs to specify
> what meet/session it is capturing to ("Capturing to DEMO MEET Thursday PM") and when
> Start Capturing is selected it defaults to capturing to whatever meet is currently
> selected. This also means the "Downloads" in DQ Transcribe moves to the hamburger menu
> ... the app connections can also go [in the menu] with a sub menu ("Admin Assistant >
> Meets, DQ Transcribe, Officials Sign-in, Coaches Sign-in") ... I want to change the
> "dq_transcribe" app name to DQ Transcribe and make it a sub-app of our new Admin
> Assistant.

He chose (2026-10-16):
- **Split the work.** Officials Sign-In builds the main page and the shared service; DQ
  Transcribe changes its own page.
- **The Officials Sign-In server owns meets and sessions.** The main page is
  http://localhost:8010/; Officials Sign-In moved to /officials.
- **Link and import.** The Candy Meet is linked by name and date. DQ's "10/14 Test" goes
  into the main page's meet list. DQ's DEMO MEET stays as DQ's own training meet. Nothing is
  deleted.
- Push each part to main as soon as it is tested.

## The shared service (port 8010, already live)

The current meet and session belong to the server, and every app follows them.

### `GET http://localhost:8010/api/suite/current`

```json
{
 "suite": "Admin Assistant",
 "demo": false,
 "meet": {"id": 1, "name": "All Treats No Tricks Candy Meet", "start_date": "2026-10-16"},
 "sessions": [
  {"id": 1, "name": "Friday PM", "date": "2026-10-16", "start_time": "16:45",
   "session_type": "PM", "officials_meeting_time": "15:45", "estimated_minutes": null}
 ],
 "active_session_id": 1,
 "version": "495fa0bddbd2"
}
```

- `meet` is `null`, and `sessions` is `[]`, before any meet exists.
- `version` changes whenever anything above changes. Poll it every few seconds and redraw
  only when it differs.
- `demo` is true when this browser is in the demo meet (a cookie set by the main page; see
  "Demo" below).

### `POST http://localhost:8010/api/suite/select`

The body is `{"meet_id": 3}`, `{"session_id": 7}`, or both. It replies with the same JSON as
`current`. Use it for DQ's session drop-down so that a change made in DQ moves every app.

### `GET http://localhost:8010/api/suite/meets`

Returns `{"meets": [{id, name, start_date, archived, session_count, ...}]}`. Use it if you
want to map DQ meets to suite meets.

### CORS

Only the three suite routes answer cross-origin, and only for pages served from
`http://localhost:8000` or `http://127.0.0.1:8000`. Credentials are allowed, so call
`fetch(url, {credentials: "include"})` and the demo cookie flows with the request.
`OPTIONS` preflight is supported.

Python code in your server (for example the roster fetch) sends no cookie, so it always
sees the real meet. That is the intended behaviour.

## What DQ Transcribe should change

1. **Name.** Show "DQ Transcribe" everywhere the user can see it. Package and command names
   can stay `dq_transcribe`.

2. **Top bar** (same look as the other apps):
   - ☰ on the far left.
   - **DQ Transcribe** in bold.
   - The meet name.
   - The session drop-down, filled from `/api/suite/current`. Changing it posts
     `/api/suite/select`.
   - Then the workflows: Transcript, DQs, Trash.

   For the look, see `src/officials_signin/web/desk.css` (`header`, `.main-menu`,
   `.menu-item`, `.submenu`). Copy only the look, not the files; it is a different server.

3. **☰ menu.** In this order:
   - "Meets & Main Page" (opens or switches to the main page).
   - Downloads (moved here from the page).
   - DQ's own occasional items.
   - Last, an "Admin Assistant ›" sub-menu with Meets & Main Page, DQ Transcribe, Officials
     Sign-In and Coaches Sign-In.

   Open each app in its named tab without reloading it:

   ```js
   const tab = window.open("", name);
   if (tab.location.href === "about:blank") { tab.location.href = url; }
   tab.focus();
   ```

   The tab names and URLs are:

   | App | Tab name | URL |
   |---|---|---|
   | Main page | `admin_assistant` | `http://localhost:8010/` |
   | Officials Sign-In | `officials_signin` | `http://localhost:8010/officials` |
   | Coaches Sign-In | `coaches_signin` | `http://localhost:8010/coaches` |

   Set `window.name = "dq_transcribe"` on DQ's page, so the main page's launcher switches to
   DQ's tab and never reloads it.

4. **Left column.** Remove the meet setup box: meets are created and edited on the main page
   now. DQ's own meet data (program, meet sheet, files) can stay where it is. The box that
   held them should key off the suite's current meet.

5. **Capture** (this is the owner's exception):
   - The Audio Capture panel says what it records to, for example "Capturing to All Treats
     No Tricks Candy Meet · Friday PM".
   - **Start capturing** records to the suite's current meet and session at that moment.
   - While recording, DQ keeps recording to that meet and session, even if someone picks
     another meet or session in any app and DQ's display follows it.
   - Show the recording target clearly, and say so when it differs from what is displayed.
   - Stopping ends the recording target.

6. **Linking meets.**
   - Map each DQ meet to a suite meet. Store the suite meet id on DQ's meet; use name and
     start date to link existing ones.
   - The Candy Meet ("All Treats No Tricks Candy Meet Block Party", 2026-10-16) exists in
     both. Link it.
   - DQ's "10/14 Test" (2026-10-14) is being added to the suite's meet list by the Officials
     Sign-In chat. Link it after that.
   - When the suite's current meet has no DQ meet yet, create the DQ meet quietly, with the
     same name and date, on first use.

7. **Demo.**
   - When `/api/suite/current` says `demo: true`, use DQ's DEMO MEET (the training meet).
   - DQ's DEMO MEET is not one of the suite's meets.

8. **Start-up.**
   - `scripts/start_admin_assistant.sh` now starts the Officials Sign-In server with no tabs,
     then runs `DQ_OPEN_BROWSER=0 bash scripts/start_dq.sh start`, then opens only the main
     page.
   - Please make `start_dq.sh` skip its `termux-open-url` when `DQ_OPEN_BROWSER=0`. Until
     then DQ still opens its own tab, which is harmless.
   - `start_dq.sh` on its own (no variable) should keep opening DQ as today.

9. **Roster.** `http://localhost:8010/roster.json` is unchanged. It is still the active
   session's officials.

## Rules (same repo, two chats)

- Do not edit `src/officials_signin/**`, `scripts/start_signin.sh`,
  `scripts/start_admin_assistant.sh` or `ai_docs/officials_signin/**`. Ask in your notes if
  you need a change there.
- Before every push, run `git pull --rebase origin main`.
- Never restart the Officials Sign-In server during a meet without asking the owner.
