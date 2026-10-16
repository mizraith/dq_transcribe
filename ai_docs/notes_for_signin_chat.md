# Notes from the DQ Transcribe chat to the Officials Sign-In chat

DQ Transcribe does not edit `src/officials_signin/**`. Requests for your side are listed here,
newest first. Please tick them off (or tell the owner) when done.

## 2026-10-16: "Print DQ summary for event ___" in the main page's Reports

The owner wants this in the central Reports pop-up. DQ's side is built and installed:

- Link: `http://localhost:8000/event-summary?all=1&suite_meet_id=<the current suite meet id>`
  (DQ is on port 8000; open it in a new tab like the other reports).
- It shows a page that asks for the event number and also offers a button for each event
  that has DQs. The printout lists **every** DQ of the event with a **Status** column
  (Called, Incomplete, Pending notification, Notified, Protested, Upheld, Overturned, Declined),
  heat/lane order, codes (unsettled codes list every option), official and an Entered box.
- `suite_meet_id` picks DQ's meet linked to your meet id. If DQ has never opened that meet,
  the page answers 404 with "open it in DQ Transcribe first" (DQ links a meet the first time
  its page follows it).
- Suggested `SUITE_REPORTS` entry (your format): title "Print DQ summary for event",
  description "Every DQ of one event with its status (from DQ Transcribe).", and a URL
  built from the current meet id. Your entries use same-server routes today, so this one
  needs an absolute URL on port 8000.

## 2026-10-16: start_dq.sh

`DQ_OPEN_BROWSER=0 bash scripts/start_dq.sh start` no longer opens a browser tab (done).
