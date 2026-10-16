/**
 * The meets panel of the Admin Assistant main page: the meet overview (open, archive,
 * restore, delete, the demo meet) and Meet setup (the meet and its sessions as table
 * rows). Opening a meet or choosing a session here makes it current for every app.
 *
 * Moved from the Officials Sign-In page (2026-10-16): all meet setup is done on the main
 * page now. Uses the shared helpers in desk_shared.js and the main page's ``pageState``
 * and ``refresh`` (home.js); load this file before home.js.
 *
 * This file is a string.Template: the config placeholder below is replaced by
 * officials_signin.server.render_script, so never use a literal dollar sign here.
 */
"use strict";

const CONFIG = ${config};
const KEYS = CONFIG.keys;
const ROUTES = CONFIG.routes;
const element = window.Desk.element;
const getJson = window.Desk.getJson;
const postJson = window.Desk.postJson;
const makeButton = window.Desk.makeButton;
const showToast = window.Desk.showToast;
const isoToday = window.Desk.isoToday;
const minutesOfDay = window.Desk.minutesOfDay;
const hoursMinutesOf = window.Desk.hoursMinutesOf;
const addDays = window.Desk.addDays;
const NOON_HOUR = 12;
const setupOverlay = element("setup-overlay");

// --- Meet setup: the meet and its sessions as table rows ---------------------------

const WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MINUTES_PER_HOUR = 60;
const TYPE_AM = "AM";
const TYPE_PM = "PM";
const OTHER_TYPE_VALUE = "other";
let setupMeetId = null; // meet being edited in Meet setup (null: a new meet)
let setupRows = []; // one entry per session row (see addSessionRow)

/**
 * Suggest a session name, for example "Friday Prelims", "Friday PM" or "Friday Session A".
 * @param {string} isoDate  YYYY-MM-DD, or "".
 * @param {string} sessionType  Session type, or "".
 * @returns {string}  The suggestion, or "" without a date.
 */
function suggestSessionName(isoDate, sessionType) {
  if (!isoDate) { return ""; }
  const parts = isoDate.split("-").map(Number);
  const weekday = WEEKDAY_NAMES[new Date(parts[0], parts[1] - 1, parts[2]).getDay()];
  if (!sessionType) { return weekday; }
  const isLetter = CONFIG.sessionLetterTypes.indexOf(sessionType) >= 0;
  return weekday + " " + (isLetter ? CONFIG.sessionLetterPrefix + " " + sessionType : sessionType);
}

/** A small input element for the session table. */
function makeInput(type, className) {
  const input = document.createElement("input");
  input.type = type;
  input.autocomplete = "off";
  if (className) { input.className = className; }
  return input;
}

/** The type drop-down: a blank choice, the usual types, then "Other…". */
function makeTypeSelect() {
  const select = document.createElement("select");
  // "|| []": a page served by an older server process still loads (without the list).
  [["", "—"]].concat((CONFIG.sessionTypes || []).map(function (type) { return [type, type]; }))
    .concat([[OTHER_TYPE_VALUE, CONFIG.sessionTypeOtherLabel]])
    .forEach(function (pair) {
      const option = document.createElement("option");
      option.value = pair[0];
      option.textContent = pair[1];
      select.appendChild(option);
    });
  return select;
}

/** The session type chosen in a row ("" if none). */
function rowSessionType(row) {
  if (row.type.value === OTHER_TYPE_VALUE) { return row.typeOther.value.trim(); }
  return row.type.value;
}

/**
 * Fill in whatever the admin has not set by hand in a row: the type follows the
 * start time (AM/PM), the officials meeting is an hour before the start, and the
 * name is suggested from the date and type.
 */
function autoFillRow(row) {
  const time = row.time.value;
  if (!row.type.dataset.chosen && time) {
    row.type.value = minutesOfDay(time) < NOON_HOUR * MINUTES_PER_HOUR ? TYPE_AM : TYPE_PM;
  }
  if (!row.meeting.dataset.typed) {
    row.meeting.value = time ? hoursMinutesOf(minutesOfDay(time) - CONFIG.meetingMinutesBeforeStart) : "";
  }
  if (!row.name.dataset.typed) {
    row.name.value = suggestSessionName(row.date.value, rowSessionType(row));
  }
}

/** Mark a row as changed (a stripe on its left) until Save. */
function markRowChanged(row) {
  row.tr.classList.add("changed");
}

/**
 * Add a row to the session table.
 * @param {object|null} session  A saved session to show, or null for a new row.
 * @param {object} [defaults]  For a new row: {date, time, type} to start from.
 */
function addSessionRow(session, defaults) {
  const tbody = element("session-rows");
  const row = {
    id: session ? session[KEYS.id] : null,
    signinCount: session ? session[KEYS.signinCount] : 0,
    tr: document.createElement("tr"),
    type: makeTypeSelect(),
    typeOther: makeInput("text", "type-other"),
    date: makeInput("date"),
    time: makeInput("time"),
    meeting: makeInput("time"),
    name: makeInput("text", "session-name-input"),
    hours: makeInput("number", "hours-input"),
  };
  row.typeOther.placeholder = "Type of session";
  row.typeOther.hidden = true;
  row.hours.inputMode = "decimal";
  row.hours.min = String(CONFIG.sessionLengthStepMinutes / MINUTES_PER_HOUR);
  row.hours.max = String(CONFIG.maxSessionMinutes / MINUTES_PER_HOUR);
  row.hours.step = String(CONFIG.sessionLengthStepMinutes / MINUTES_PER_HOUR);
  if (session) {
    const sessionType = session[KEYS.sessionType] || "";
    if (sessionType && CONFIG.sessionTypes.indexOf(sessionType) < 0) {
      row.type.value = OTHER_TYPE_VALUE;
      row.typeOther.value = sessionType;
      row.typeOther.hidden = false;
    } else {
      row.type.value = sessionType;
    }
    row.type.dataset.chosen = "1";
    row.date.value = session[KEYS.date];
    row.time.value = session[KEYS.startTime] || "";
    row.meeting.value = session[KEYS.meetingTime] || "";
    row.meeting.dataset.typed = "1";
    row.name.value = session[KEYS.name];
    row.name.dataset.typed = "1";
    row.hours.value = String((session[KEYS.estimatedMinutes] || CONFIG.defaultSessionMinutes) / MINUTES_PER_HOUR);
  } else {
    const start = defaults || {};
    row.date.value = start.date || element("meet-date-input").value || isoToday();
    row.time.value = start.time || "";
    if (start.type) { row.type.value = start.type; row.type.dataset.chosen = "1"; }
    row.hours.value = String((start.minutes || CONFIG.defaultSessionMinutes) / MINUTES_PER_HOUR);
    autoFillRow(row);
    markRowChanged(row);
  }
  // Wiring: suggestions follow the date, time and type until a box is typed in.
  row.type.addEventListener("change", function () {
    row.type.dataset.chosen = "1";
    row.typeOther.hidden = row.type.value !== OTHER_TYPE_VALUE;
    if (!row.typeOther.hidden) { row.typeOther.focus(); }
    autoFillRow(row);
  });
  row.typeOther.addEventListener("input", function () { autoFillRow(row); });
  [row.date, row.time].forEach(function (input) { input.addEventListener("change", function () { autoFillRow(row); }); });
  [row.name, row.meeting].forEach(function (input) {
    input.addEventListener("input", function () { input.dataset.typed = "1"; });
  });
  [row.type, row.typeOther, row.date, row.time, row.meeting, row.name, row.hours].forEach(function (input) {
    input.addEventListener("input", function () { markRowChanged(row); });
    input.addEventListener("change", function () { markRowChanged(row); });
  });
  const cell = function (children, className) {
    const td = document.createElement("td");
    if (className) { td.className = className; }
    td.append.apply(td, children);
    row.tr.appendChild(td);
    return td;
  };
  cell([row.type, row.typeOther]);
  cell([row.date]);
  cell([row.time]);
  cell([row.meeting]);
  cell([row.name]);
  cell([row.hours]);
  cell([String(row.signinCount)], "count-cell");
  cell([makeButton("Delete", "", function () { askDeleteRow(row); })]);
  tbody.appendChild(row.tr);
  setupRows.push(row);
  return row;
}

/** "+ Add session": a new row that follows on from the last one. */
function addFollowingRow() {
  const last = setupRows[setupRows.length - 1];
  if (!last) { addSessionRow(null, null); return; }
  const defaults = { minutes: Number(last.hours.value) * MINUTES_PER_HOUR || CONFIG.defaultSessionMinutes };
  // A morning session is usually followed by an afternoon one the same day; after
  // that, the next day at the same time.
  if (last.time.value && minutesOfDay(last.time.value) < NOON_HOUR * MINUTES_PER_HOUR) {
    defaults.date = last.date.value;
  } else {
    defaults.date = last.date.value ? addDays(last.date.value, 1) : "";
    defaults.time = last.time.value;
    defaults.type = last.type.value === OTHER_TYPE_VALUE ? "" : last.type.value;
  }
  const row = addSessionRow(null, defaults);
  (row.time.value ? row.name : row.time).focus();
}

/** The request body for one row. */
function rowBody(row) {
  const body = {};
  const sessionType = rowSessionType(row);
  body[KEYS.id] = row.id;
  body[KEYS.name] = row.name.value.trim() || suggestSessionName(row.date.value, sessionType);
  body[KEYS.date] = row.date.value;
  body[KEYS.startTime] = row.time.value || null;
  body[KEYS.sessionType] = sessionType || null;
  body[KEYS.meetingTime] = row.meeting.value || null;
  const hours = Number(row.hours.value);
  body[KEYS.estimatedMinutes] = hours > 0
    ? Math.round(hours * MINUTES_PER_HOUR / CONFIG.sessionLengthStepMinutes) * CONFIG.sessionLengthStepMinutes
    : null;
  return body;
}

let rowBeingDeleted = null; // the saved session row whose delete warning is open

/** Close the delete warning (if open). */
function closeRowWarning() {
  if (rowBeingDeleted) { rowBeingDeleted.tr.classList.remove("deleting"); }
  rowBeingDeleted = null;
  element("row-delete-warning").hidden = true;
}

/** Delete a row: a new row just goes; a saved session asks first (big warning under the table). */
function askDeleteRow(row) {
  if (row.id === null) {
    row.tr.remove();
    setupRows = setupRows.filter(function (item) { return item !== row; });
    return;
  }
  closeRowWarning();
  rowBeingDeleted = row;
  row.tr.classList.add("deleting");
  element("row-delete-title").textContent = "⚠ Delete " + (row.name.value || "this session") + "?";
  element("row-delete-detail").textContent = row.signinCount === 0
    ? "Nobody has signed in to it yet. This cannot be undone."
    : "Its " + row.signinCount + " sign-in" + (row.signinCount === 1 ? "" : "s") + " and team placements will be "
      + "deleted too (the officials stay in the app for next time). This cannot be undone.";
  const warning = element("row-delete-warning");
  warning.hidden = false;
  warning.scrollIntoView({ block: "nearest" });
}

async function deleteSavedRow() {
  const row = rowBeingDeleted;
  if (!row) { return; }
  try {
    await postJson(ROUTES.sessionPrefix + row.id + ROUTES.sessionDeleteSuffix, {});
    closeRowWarning();
    row.tr.remove();
    setupRows = setupRows.filter(function (item) { return item !== row; });
    await refresh();
    window.Desk.announceChange();
    showToast((row.name.value || "Session") + " deleted");
  } catch (error) {
    showToast(error.message, true);
  }
}

/**
 * Show Meet setup for the active meet, or for a new meet.
 * @param {boolean} newMeet  Start a new meet (one empty session row).
 */
function openSetup(newMeet) {
  const editing = !newMeet && pageState.meet !== null;
  setupMeetId = editing ? pageState.meet[KEYS.id] : null;
  closeRowWarning();
  setupRows = [];
  element("session-rows").replaceChildren();
  element("setup-title").textContent = editing ? "Meet setup" : "New meet";
  element("meet-name-input").value = editing ? pageState.meet[KEYS.name] : "";
  element("meet-date-input").value = editing ? pageState.meet[KEYS.startDate] : isoToday();
  element("setup-save").textContent = editing ? "Save" : "Create meet";
  if (editing) {
    pageState.sessions.forEach(function (session) { addSessionRow(session, null); });
  }
  if (setupRows.length === 0) { addSessionRow(null, null); }
  setupOverlay.hidden = false;
  if (!editing) { element("meet-name-input").focus(); }
}

function closeSetup() {
  closeRowWarning();
  setupOverlay.hidden = true;
}

/** Save the meet and every session row in one request. */
async function saveSetup() {
  const body = {};
  body[KEYS.id] = setupMeetId;
  body[KEYS.name] = element("meet-name-input").value.trim();
  body[KEYS.startDate] = element("meet-date-input").value;
  if (!body[KEYS.name] || !body[KEYS.startDate]) {
    showToast("Enter the meet name and start date", true);
    return;
  }
  const missingDate = setupRows.findIndex(function (row) { return !row.date.value; });
  if (missingDate >= 0) {
    showToast("Session " + (missingDate + 1) + " needs a date", true);
    return;
  }
  body[KEYS.sessions] = setupRows.map(rowBody);
  const isNew = setupMeetId === null;
  try {
    if (isNew && pageState.demo) { await postJson(ROUTES.demoExit, {}); } // a new meet is always real
    await postJson(ROUTES.meetSave, body);
    closeSetup();
    await refresh();
    window.Desk.announceChange();
    showToast("✓ " + body[KEYS.name] + (isNew ? " created" : " saved"));
  } catch (error) {
    showToast(error.message, true);
  }
}

// When a new meet's start date changes, rows not yet touched follow it.
element("meet-date-input").addEventListener("change", function () {
  if (setupMeetId !== null || setupRows.length !== 1) { return; }
  const row = setupRows[0];
  row.date.value = element("meet-date-input").value;
  autoFillRow(row);
});

// --- Meet overview and the demo meet ---------------------------------------------

let demoResetTimer = null;

let showArchivedMeets = false;
let meetBeingDeleted = null;

/**
 * One meet in the overview: name, date, sessions and officials, and its buttons.
 * Current meet: "Open now". Other meets: Open and Archive. Archived meets: Open,
 * Restore and Delete (behind a warning).
 */
function meetRow(meet, isCurrent) {
  const row = document.createElement("li");
  row.className = "meet-row" + (isCurrent ? " current" : "");
  const text = document.createElement("span");
  text.className = "meet-text";
  const title = document.createElement("span");
  title.className = "meet-title";
  title.textContent = meet[KEYS.name];
  const detail = document.createElement("span");
  detail.className = "signin-detail";
  const sessions = meet[KEYS.sessionCount];
  const people = meet[KEYS.officialCount];
  detail.textContent = "starts " + meet[KEYS.startDate] + " · " + sessions + " session" + (sessions === 1 ? "" : "s")
    + " · " + people + " official" + (people === 1 ? "" : "s");
  text.append(title, detail);
  const actions = document.createElement("span");
  actions.className = "meet-actions";
  if (isCurrent) {
    const here = document.createElement("strong");
    here.textContent = "Open now";
    actions.appendChild(here);
  } else if (meet[KEYS.archived]) {
    const zip = document.createElement("a");
    zip.className = "button-link";
    zip.href = ROUTES.meetPrefix + meet[KEYS.id] + ROUTES.meetZipSuffix;
    zip.textContent = "Save zip";
    actions.append(
      zip,
      makeButton("Restore", "", function () { archiveMeet(meet, false); }),
      makeButton("Delete…", "danger", function () { askDeleteMeet(meet); })
    );
  } else {
    actions.append(
      makeButton("Archive", "", function () { archiveMeet(meet, true); }),
      makeButton("Open", "go", function () { openMeet(meet[KEYS.id]); })
    );
  }
  row.append(text, actions);
  return row;
}

/** Draw the meet list (in use, archived) and the demo row from the server's meet overview. */
async function drawMeets(showResetWarning) {
  const overview = await getJson(ROUTES.meets);
  const current = overview[KEYS.demo] ? null : overview[KEYS.activeMeetId];
  const active = overview[KEYS.meets].filter(function (meet) { return !meet[KEYS.archived]; });
  const archived = overview[KEYS.meets].filter(function (meet) { return meet[KEYS.archived]; });
  const list = element("meet-list");
  list.replaceChildren();
  active.forEach(function (meet) { list.appendChild(meetRow(meet, meet[KEYS.id] === current)); });
  if (!active.length) {
    const empty = document.createElement("li");
    empty.className = "signin-detail";
    empty.textContent = archived.length ? "No meets in use. Start a new one, or open an archived meet." : "No meets yet.";
    list.appendChild(empty);
  }
  const toggle = element("archived-toggle");
  toggle.hidden = archived.length === 0;
  toggle.textContent = (showArchivedMeets ? "Hide" : "Show") + " archived meets (" + archived.length + ")";
  const archivedList = element("archived-list");
  archivedList.replaceChildren();
  archived.forEach(function (meet) { archivedList.appendChild(meetRow(meet, false)); });
  archivedList.hidden = !showArchivedMeets || archived.length === 0;
  closeMeetDeleteWarning();
  element("demo-row").classList.toggle("current", overview[KEYS.demo]);
  element("demo-open").textContent = overview[KEYS.demo] ? "Open now" : "Open";
  element("demo-open").disabled = overview[KEYS.demo];
  element("demo-reset-overview").hidden = !overview[KEYS.demoReady];
  element("demo-size-link").href = ROUTES.demo;
  showDemoResetWarning(Boolean(showResetWarning));
}

async function archiveMeet(meet, archived) {
  const body = {};
  body[KEYS.archived] = archived;
  try {
    await postJson(ROUTES.meetPrefix + meet[KEYS.id] + ROUTES.meetArchiveSuffix, body);
    showToast(meet[KEYS.name] + (archived ? " archived" : " restored"));
    await refresh();
  } catch (error) {
    showToast(error.message, true);
  }
}

function closeMeetDeleteWarning() {
  meetBeingDeleted = null;
  element("meet-delete-warning").hidden = true;
}

/** The big warning before deleting an archived meet for good. */
function askDeleteMeet(meet) {
  meetBeingDeleted = meet;
  const signins = meet[KEYS.signinCount];
  element("meet-delete-title").textContent = "⚠ Delete " + meet[KEYS.name] + " for good?";
  element("meet-delete-detail").textContent = "Its " + meet[KEYS.sessionCount] + " session"
    + (meet[KEYS.sessionCount] === 1 ? "" : "s") + " and " + signins + " sign-in" + (signins === 1 ? "" : "s")
    + " (teams included) will be deleted. The officials stay in the app for next time. This cannot be undone. "
    + "To keep a record, tap Save zip first (pages, spreadsheet and rosters).";
  const warning = element("meet-delete-warning");
  warning.hidden = false;
  warning.scrollIntoView({ block: "nearest" });
}

async function deleteMeet() {
  const meet = meetBeingDeleted;
  if (!meet) { return; }
  try {
    await postJson(ROUTES.meetPrefix + meet[KEYS.id] + ROUTES.meetDeleteSuffix, {});
    showToast(meet[KEYS.name] + " deleted");
    await refresh();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function openMeet(meetId) {
  try {
    await postJson(ROUTES.meetPrefix + meetId + ROUTES.meetOpenSuffix, {});
    await refresh();
    window.Desk.announceChange();
    showToast("✓ " + (pageState.meet ? pageState.meet[KEYS.name] : "Meet") + " open");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function openDemo() {
  try {
    await postJson(ROUTES.demoOpen, {});
    await refresh();
    window.Desk.announceChange();
  } catch (error) {
    showToast(error.message, true);
  }
}

/** The "Reset the demo meet?" warning; it closes by itself after a few seconds. */
function showDemoResetWarning(show) {
  clearTimeout(demoResetTimer);
  element("demo-reset-warning").hidden = !show;
  if (show) {
    demoResetTimer = setTimeout(function () { element("demo-reset-warning").hidden = true; },
      CONFIG.demoResetWarningSeconds * 1000);
  }
}

async function resetDemo() {
  showDemoResetWarning(false);
  try {
    await postJson(ROUTES.demoReset, {});
    await refresh();
    window.Desk.announceChange();
    showToast("✓ Demo meet reset");
  } catch (error) {
    showToast("Could not reset the demo meet: " + error.message, true);
  }
}

/** "+ New meet": always a real meet, so leave demo mode first. */
async function newMeetFromOverview() {
  if (pageState.demo) {
    await postJson(ROUTES.demoExit, {});
    await refresh();
    window.Desk.announceChange();
  }
  openSetup(true);
}

// --- Wiring --------------------------------------------------------------------------

element("meets-new").addEventListener("click", newMeetFromOverview);
element("archived-toggle").addEventListener("click", function () {
  showArchivedMeets = !showArchivedMeets;
  drawMeets(false);
});
element("meet-delete-keep").addEventListener("click", closeMeetDeleteWarning);
element("meet-delete-confirm").addEventListener("click", deleteMeet);
element("demo-open").addEventListener("click", openDemo);
element("demo-reset-overview").addEventListener("click", function () { showDemoResetWarning(true); });
element("demo-reset-cancel").addEventListener("click", function () { showDemoResetWarning(false); });
element("demo-reset-confirm").addEventListener("click", resetDemo);
element("setup-cancel").addEventListener("click", closeSetup);
element("setup-save").addEventListener("click", saveSetup);
element("session-add-row").addEventListener("click", addFollowingRow);
element("row-delete-keep").addEventListener("click", closeRowWarning);
element("row-delete-confirm").addEventListener("click", deleteSavedRow);
