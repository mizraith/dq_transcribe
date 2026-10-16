/**
 * Officials Sign-In page behaviour.
 *
 * Common case, about three taps: "Capture USA Registration" -> the official
 * holds up their phone (the card is read automatically) -> the sign-in sheet
 * opens with name, club, zone and last roles pre-filled -> "Sign in".
 * A returning official whose card was already read at this meet can instead
 * type a few letters of their name, tap their row and tap "Sign in".
 * The admin is involved only for sign-ins that could not be validated: they
 * appear at the top of the list with "Looks good" (checked by eye) and "Remove".
 *
 * This file is a string.Template: the config placeholder below is replaced by
 * officials_signin.server.render_script, so never use a literal dollar sign here
 * (so no JavaScript template literals either).
 */
"use strict";

const CONFIG = ${config};
const KEYS = CONFIG.keys;
const ROUTES = CONFIG.routes;
const MATCH_LIMIT = 8;
const TOAST_SECONDS = 2.5;
const REMOVE_CONFIRM_SECONDS = 3;

// --- Page elements ----------------------------------------------------------

const element = function (id) { return document.getElementById(id); };
const meetNameText = element("meet-name");
const sessionSelect = element("session-select");
const mainMenu = element("main-menu");
const captureButton = element("capture-button");
const searchInput = element("search");
const matchList = element("matches");
const newPersonButton = element("new-person");
const deskPanel = element("desk-panel");
const noSessionPanel = element("no-session-panel");
const signinsTitle = element("signins-title");
const signinsList = element("signins");
const sheetOverlay = element("sheet-overlay");
const sheetName = element("sheet-name");
const sheetYears = element("sheet-years");
const sheetClub = element("sheet-club");
const sheetCheck = element("sheet-check");
const sheetRoles = element("sheet-roles");
const sheetTrainee = element("sheet-trainee");
const sheetLaterBlock = element("sheet-later-block");
const sheetLater = element("sheet-later");
const setupOverlay = element("setup-overlay");
const toast = element("toast");

// --- State ------------------------------------------------------------------

let pageState = { meet: null, sessions: [], activeSessionId: null, signins: [] };
let officials = [];
// What the open sign-in sheet is about.
let sheet = { officialId: null, card: null, cardResult: null, roles: [], trainee: false, laterSessionIds: [] };

// --- Helpers ----------------------------------------------------------------

/** Lower-case letters only, for name matching (same rule as the server). */
function nameKey(text) {
  return (text || "").toLowerCase().replace(/[^a-z]+/g, "");
}

function showToast(message, isError) {
  toast.textContent = message;
  toast.classList.toggle("error", Boolean(isError));
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(function () { toast.classList.remove("show"); }, TOAST_SECONDS * 1000);
}

async function getJson(route) {
  const response = await fetch(route, { cache: "no-store" });
  return response.json();
}

async function postJson(route, body) {
  const response = await fetch(route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload[KEYS.error] || "Something went wrong");
  }
  return payload;
}

function makeButton(label, className, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  if (className) { button.className = className; }
  button.addEventListener("click", onClick);
  return button;
}

function activeSession() {
  return pageState.sessions.find(function (session) { return session[KEYS.id] === pageState.activeSessionId; }) || null;
}

/** Sessions later on the same day as the active one (for pre-sign-up). */
function laterSessionsToday() {
  const active = activeSession();
  if (active === null) { return []; }
  const index = pageState.sessions.indexOf(active);
  return pageState.sessions.slice(index + 1).filter(function (session) {
    return session[KEYS.date] === active[KEYS.date];
  });
}

/** "PASA · Pacific Swimming · 3 yr certified" (club and LSC from the shared Desk helper). */
function describeOfficial(official) {
  const parts = [];
  const club = window.Desk.describeClub(official);
  if (club) { parts.push(club); }
  if (official[KEYS.yearsCertified] !== null && official[KEYS.yearsCertified] !== undefined) {
    parts.push(official[KEYS.yearsCertified] + " yr certified");
  }
  return parts.join(" · ");
}

// --- Loading and drawing -------------------------------------------------------

async function refresh() {
  const state = await getJson(ROUTES.state);
  pageState = {
    demo: Boolean(state[KEYS.demo]),
    meet: state[KEYS.meet],
    sessions: state[KEYS.sessions],
    activeSessionId: state[KEYS.activeSessionId],
    signins: state[KEYS.signins],
  };
  officials = (await getJson(ROUTES.officials))[KEYS.officials];
  drawHeader();
  drawSignins();
  drawMatches();
}

function drawHeader() {
  meetNameText.textContent = pageState.meet ? pageState.meet[KEYS.name] : "No meet yet";
  // The session drop-down: "Friday PM · 18" (18 signed in); picking one makes it the session.
  sessionSelect.replaceChildren();
  pageState.sessions.forEach(function (session) {
    const option = document.createElement("option");
    option.value = String(session[KEYS.id]);
    option.textContent = session[KEYS.name] + "  ·  " + session[KEYS.signinCount];
    option.selected = session[KEYS.id] === pageState.activeSessionId;
    sessionSelect.appendChild(option);
  });
  element("session-picker").hidden = pageState.sessions.length === 0;
  const ready = pageState.activeSessionId !== null;
  element("teams-button").hidden = !ready;
  deskPanel.hidden = !ready;
  noSessionPanel.hidden = ready;
  const session = activeSession();
  const meetingTime = element("meeting-time");
  meetingTime.hidden = !(session && session[KEYS.meetingTime]);
  meetingTime.textContent = meetingTime.hidden ? "" : "Officials Meeting: " + formatTime12(session[KEYS.meetingTime]);
  signinsTitle.textContent = session ? "Signed in: " + session[KEYS.name] : "Signed in";
  element("demo-banner").hidden = !pageState.demo;
  element("demo-new").href = ROUTES.demo;
  element("coaches-link").hidden = !CONFIG.coachesPage;
  element("coaches-link").href = ROUTES.coaches;
  element("coaches-button").hidden = !CONFIG.coachesPage;
  element("coaches-button").href = ROUTES.coaches;
  // The coaches page opens in its own tab (the same one each time).
  element("coaches-button").target = CONFIG.coachesTabName;
  element("coaches-link").target = CONFIG.coachesTabName;
  const sessionQuery = "?" + KEYS.sessionId + "=" + pageState.activeSessionId;
  element("print-session-link").href = ROUTES.printSession + sessionQuery;
  element("print-meet-link").href = ROUTES.printMeet;
  element("meet-zip-link").href = ROUTES.meetZip;
  element("print-panel").hidden = !ready;
  element("team-display-link").href = ROUTES.teamDisplay + sessionQuery;
  element("roster-link").href = ROUTES.roster;
  element("roster-download-link").href = ROUTES.rosterDownload;
}

function drawSignins() {
  signinsList.replaceChildren();
  // Anyone who needs the admin goes first.
  const ordered = pageState.signins.slice().sort(function (first, second) {
    return Number(first[KEYS.validated]) - Number(second[KEYS.validated]);
  });
  if (ordered.length === 0) {
    signinsList.textContent = "Nobody yet.";
    return;
  }
  ordered.forEach(function (signin) {
    const row = document.createElement("div");
    row.className = "signin-row";
    const info = document.createElement("div");
    const name = document.createElement("div");
    name.className = "signin-name";
    name.textContent = signin[KEYS.name];
    if (signin[KEYS.validated]) {
      const badge = document.createElement("span");
      badge.className = "badge ok";
      badge.textContent = signin[KEYS.validationMethod] === CONFIG.validationMethods.visual ? "✓ admin" : "✓ card";
      name.appendChild(badge);
    }
    const placement = signin[KEYS.team] || signin[KEYS.assignment];
    if (placement) {
      const badge = document.createElement("span");
      badge.className = "badge team";
      badge.textContent = placement + (signin[KEYS.teamLead] ? " ★" : "");
      name.appendChild(badge);
    }
    if (signin[KEYS.trainee]) {
      const badge = document.createElement("span");
      badge.className = "badge trainee";
      badge.textContent = "Trainee";
      name.appendChild(badge);
    }
    const detail = document.createElement("div");
    detail.className = "signin-detail";
    detail.textContent = [signin[KEYS.roles].join(", "), describeOfficial(signin)].filter(Boolean).join(" · ");
    info.append(name, detail);
    if (!signin[KEYS.validated]) {
      row.classList.add("needs-admin");
      const problem = document.createElement("div");
      problem.className = "problem";
      problem.textContent = "Needs admin: " + signin[KEYS.problems].join("; ");
      info.appendChild(problem);
    }
    const actions = document.createElement("div");
    actions.className = "row-actions";
    if (!signin[KEYS.validated]) {
      actions.appendChild(makeButton("Looks good", "go", function () { signinAction(signin, ROUTES.validateSuffix); }));
    }
    actions.appendChild(makeButton("Edit", "", function () { openEditSheet(signin); }));
    const removeButton = makeButton("Remove", "", function () {
      if (removeButton.dataset.armed) {
        signinAction(signin, ROUTES.removeSuffix);
        return;
      }
      removeButton.dataset.armed = "1";
      removeButton.textContent = "Tap to confirm";
      setTimeout(function () { delete removeButton.dataset.armed; removeButton.textContent = "Remove"; }, REMOVE_CONFIRM_SECONDS * 1000);
    });
    actions.appendChild(removeButton);
    row.append(info, actions);
    signinsList.appendChild(row);
  });
}

/**
 * Validate a sign-in by eye ("Looks good") or remove it, then redraw.
 * @param {object} signin  Sign-in from the list.
 * @param {string} actionSuffix  ``ROUTES.validateSuffix`` or ``ROUTES.removeSuffix``.
 */
async function signinAction(signin, actionSuffix) {
  try {
    await postJson(ROUTES.signinPrefix + signin[KEYS.id] + actionSuffix, {});
    showToast(signin[KEYS.name] + (actionSuffix === ROUTES.removeSuffix ? " removed" : " checked by the admin"));
    await refresh();
  } catch (error) {
    showToast(error.message, true);
  }
}

function drawMatches() {
  matchList.replaceChildren();
  const query = searchInput.value.trim();
  newPersonButton.hidden = query.length === 0;
  newPersonButton.textContent = "Not listed? Sign in “" + query + "” as new";
  if (query.length === 0) { return; }
  const queryKey = nameKey(query);
  const queryWords = query.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = officials.filter(function (official) {
    const words = official[KEYS.name].toLowerCase().replace(/["']/g, "").split(/\s+/);
    const everyWordMatches = queryWords.every(function (queryWord) {
      return words.some(function (word) { return word.indexOf(queryWord) === 0; });
    });
    return everyWordMatches || nameKey(official[KEYS.name]).indexOf(queryKey) >= 0;
  }).slice(0, MATCH_LIMIT);
  matches.forEach(function (official) {
    const item = document.createElement("li");
    const button = makeButton("", "", function () { openSheet(official, null, null); });
    const label = document.createElement("span");
    label.textContent = official[KEYS.name];
    const detail = document.createElement("span");
    detail.className = "match-detail";
    detail.textContent = describeOfficial(official);
    button.append(label, detail);
    item.appendChild(button);
    matchList.appendChild(item);
  });
}

// --- Sessions and setup --------------------------------------------------------

async function chooseSession(sessionId) {
  const body = {};
  body[KEYS.sessionId] = sessionId;
  try {
    await postJson(ROUTES.activeSession, body);
    await refresh();
    window.Desk.announceChange();
  } catch (error) {
    showToast(error.message, true);
  }
}

const WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const NOON_HOUR = 12;
const MINUTES_PER_HOUR = 60;
const MINUTES_PER_DAY = 24 * MINUTES_PER_HOUR;
const MILLISECONDS_PER_MINUTE = 60000;
const ISO_DATE_LENGTH = 10;
const TYPE_AM = "AM";
const TYPE_PM = "PM";
const OTHER_TYPE_VALUE = "other";
let setupMeetId = null; // meet being edited in Meet setup (null: a new meet)
let setupRows = []; // one entry per session row (see addSessionRow)

/** Today's date as YYYY-MM-DD in local time. */
function isoToday() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * MILLISECONDS_PER_MINUTE).toISOString().slice(0, ISO_DATE_LENGTH);
}

/** "13:05" -> minutes after midnight. */
function minutesOfDay(hoursMinutes) {
  const parts = hoursMinutes.split(":").map(Number);
  return parts[0] * MINUTES_PER_HOUR + parts[1];
}

/** Minutes after midnight -> "13:05" (clamped to the same day). */
function hoursMinutesOf(minutes) {
  const clamped = Math.max(0, Math.min(MINUTES_PER_DAY - 1, minutes));
  const hours = Math.floor(clamped / MINUTES_PER_HOUR);
  const rest = clamped % MINUTES_PER_HOUR;
  return String(hours).padStart(2, "0") + ":" + String(rest).padStart(2, "0");
}

/** "13:05" -> "1:05 PM". */
function formatTime12(hoursMinutes) {
  const minutes = minutesOfDay(hoursMinutes);
  const hours = Math.floor(minutes / MINUTES_PER_HOUR);
  const displayHours = hours % NOON_HOUR === 0 ? NOON_HOUR : hours % NOON_HOUR;
  return displayHours + ":" + String(minutes % MINUTES_PER_HOUR).padStart(2, "0") + (hours < NOON_HOUR ? " AM" : " PM");
}

/** YYYY-MM-DD plus some days. */
function addDays(isoDate, days) {
  const parts = isoDate.split("-").map(Number);
  const day = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + days));
  return day.toISOString().slice(0, ISO_DATE_LENGTH);
}

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

// --- Teams --------------------------------------------------------------------------

const teamsOverlay = element("teams-overlay");
const placeOverlay = element("place-overlay");
const REBUILD_CONFIRM_SECONDS = 3;
let teamView = null;
let placeTarget = null; // {id, trainee} of the official being moved

/** "4 teams of 3 + 1 extra" for a team count. */
function describeTeamLayout(count) {
  const layout = teamView[KEYS.layouts][String(count)];
  if (!layout) { return count + " teams"; }
  const extras = layout[KEYS.extras];
  return count + " team" + (count === 1 ? "" : "s") + " of " + layout[KEYS.teamSize]
    + (extras ? " + " + extras + " extra" + (extras === 1 ? "" : "s") : "");
}

async function loadTeams() {
  teamView = await getJson(ROUTES.teams);
  if (teamView[KEYS.error]) { throw new Error(teamView[KEYS.error]); }
  // First visit with judges signed in: build straight away (no tap needed).
  if (!teamView[KEYS.built] && teamView[KEYS.judgeCount] > 0) {
    teamView = await postJson(ROUTES.teamsBuild, {});
  }
}

/**
 * The Teams button: when some officials of this session are not checked yet (card or
 * "Looks good"), say who first; they are kept off the teams until checked.
 */
function askBeforeTeams() {
  const unchecked = pageState.signins.filter(function (signin) { return !signin[KEYS.validated]; });
  if (!unchecked.length) { openTeams(); return; }
  element("teams-check-detail").textContent = unchecked.length + " official" + (unchecked.length === 1 ? " has" : "s have")
    + " not been checked by card or by the admin:";
  const list = element("teams-check-names");
  list.replaceChildren();
  unchecked.forEach(function (signin) {
    const item = document.createElement("li");
    item.textContent = signin[KEYS.name];
    list.appendChild(item);
  });
  element("teams-check-overlay").hidden = false;
}

async function openTeams() {
  try {
    await loadTeams();
    drawTeams();
    teamsOverlay.hidden = false;
  } catch (error) {
    showToast(error.message, true);
  }
}

async function teamsRequest(route, body) {
  try {
    teamView = await postJson(route, body);
    drawTeams();
    if (!placeOverlay.hidden) { drawPlace(); }
  } catch (error) {
    showToast(error.message, true);
  }
}

/**
 * One name on the Teams screen: tap to place them, drag to move or swap, and (for a
 * team member) the ☆ star to make them the Team Lead.
 */
function memberButton(member, isTrainee) {
  const chip = document.createElement("div");
  chip.className = "member" + (isTrainee ? " trainee" : "");
  chip.setAttribute("role", "button");
  chip.tabIndex = 0;
  const openPlace = function () {
    if (dragJustEnded) { return; } // the tap that ended a drag is not a "place" tap
    placeTarget = { id: member[KEYS.id], trainee: isTrainee };
    drawPlace();
    placeOverlay.hidden = false;
  };
  chip.addEventListener("click", function (event) {
    if (event.target.closest(".star-toggle")) { return; }
    openPlace();
  });
  chip.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openPlace(); }
  });
  const label = document.createElement("span");
  label.className = "member-name";
  label.textContent = (isTrainee ? "↳ " : "") + member[KEYS.name];
  if (member[KEYS.assignment] === CONFIG.assignmentFifteenMeter && member[KEYS.team]) {
    const tag = document.createElement("span");
    tag.className = "tag fifteen";
    tag.textContent = "15 m";
    label.appendChild(tag);
  }
  const end = document.createElement("span");
  end.className = "member-end";
  const detail = document.createElement("span");
  detail.className = "years";
  if (isTrainee) {
    detail.textContent = member[KEYS.mentor] ? "trainee, with " + member[KEYS.mentor] : "trainee, no mentor";
  } else {
    const years = member[KEYS.yearsCertified];
    detail.textContent = years === null || years === undefined ? "? yr" : years + " yr";
  }
  end.appendChild(detail);
  if (!isTrainee && member[KEYS.team]) {
    const isLead = Boolean(member[KEYS.teamLead]);
    const star = makeButton(isLead ? "★ Lead" : "☆", "star-toggle" + (isLead ? " on" : ""), function (event) {
      event.stopPropagation();
      const body = {};
      body[KEYS.teamLead] = !isLead;
      teamsRequest(ROUTES.signinPrefix + member[KEYS.id] + ROUTES.teamSuffix, body);
    });
    star.setAttribute("aria-label", isLead ? "Team Lead (tap to remove)" : "Make Team Lead");
    end.appendChild(star);
  }
  chip.append(label, end);
  chip.dataset.signinId = String(member[KEYS.id]);
  if (isTrainee) { chip.dataset.trainee = "1"; }
  enableDrag(chip);
  return chip;
}

function teamCard(title, subtitle, className) {
  const card = document.createElement("div");
  card.className = "team-card" + (className ? " " + className : "");
  const heading = document.createElement("h3");
  heading.textContent = title;
  if (subtitle) {
    const lanes = document.createElement("span");
    lanes.className = "lanes";
    lanes.textContent = subtitle;
    heading.appendChild(lanes);
  }
  card.appendChild(heading);
  return card;
}

function drawTeams() {
  const view = teamView;
  const judgeCount = view[KEYS.judgeCount];
  element("teams-summary").textContent = judgeCount + " stroke & turn judge" + (judgeCount === 1 ? "" : "s");
  // Lanes
  const lanes = element("teams-lanes");
  lanes.replaceChildren();
  const laneChoices = view[KEYS.laneChoices].slice();
  if (laneChoices.indexOf(view[KEYS.lanes]) < 0) { laneChoices.push(view[KEYS.lanes]); }
  laneChoices.forEach(function (count) {
    const chip = makeButton(String(count), "chip", function () {
      const body = {};
      body[KEYS.lanes] = count;
      teamsRequest(ROUTES.teamsSettings, body);
    });
    chip.classList.toggle("on", count === view[KEYS.lanes]);
    lanes.appendChild(chip);
  });
  // Team layouts: the suggestion and the other choice
  const layouts = element("teams-layouts");
  layouts.replaceChildren();
  [view[KEYS.proposedTeamCount], view[KEYS.alternativeTeamCount]].forEach(function (count) {
    if (!count) { return; }
    const chip = makeButton(describeTeamLayout(count), "chip", function () {
      const body = {};
      body[KEYS.teamCount] = count;
      teamsRequest(ROUTES.teamsBuild, body);
    });
    if (count === view[KEYS.proposedTeamCount]) {
      const note = document.createElement("span");
      note.className = "suggested";
      note.textContent = "suggested";
      chip.appendChild(note);
    }
    chip.classList.toggle("on", count === view[KEYS.teamCount]);
    layouts.appendChild(chip);
  });
  const modes = element("teams-rotation-modes");
  modes.replaceChildren();
  CONFIG.rotationModes.forEach(function (pair) {
    const chip = makeButton(pair[1], "chip", function () {
      const body = {};
      body[KEYS.rotationMode] = pair[0];
      teamsRequest(ROUTES.teamsSettings, body);
    });
    chip.classList.toggle("on", view[KEYS.rotationMode] === pair[0]);
    modes.appendChild(chip);
  });
  element("teams-fifteen").checked = view[KEYS.fifteenMeterOnTeams];
  drawJurisdiction(view);
  element("teams-rotation").textContent = view[KEYS.rotation];
  element("teams-display-link").href = ROUTES.teamDisplay + "?" + KEYS.sessionId + "=" + pageState.activeSessionId;
  // Alerts
  const alerts = element("teams-alerts");
  alerts.replaceChildren();
  const awaiting = view[KEYS.awaitingCheck] || [];
  if (awaiting.length) {
    const alert = document.createElement("div");
    alert.className = "teams-alert bad";
    alert.textContent = "Not checked yet, so not on a team: "
      + awaiting.map(function (signin) { return signin[KEYS.name]; }).join(", ") + ".";
    alerts.appendChild(alert);
  }
  const unplaced = view[KEYS.unplaced];
  if (unplaced.length) {
    const alert = document.createElement("div");
    alert.className = "teams-alert warn";
    alert.textContent = unplaced.length + " not on a team yet (signed in or checked after the teams were built). "
      + "Drag them onto a team, tap a name to place them, or Rebuild.";
    alerts.appendChild(alert);
  }
  const unpaired = view[KEYS.unpairedTrainees];
  if (unpaired.length) {
    const alert = document.createElement("div");
    alert.className = "teams-alert bad";
    alert.textContent = "Trainee" + (unpaired.length === 1 ? "" : "s") + " without a mentor: "
      + unpaired.map(function (trainee) { return trainee[KEYS.name]; }).join(", ") + ". Tap to pair them.";
    alerts.appendChild(alert);
  }
  // Cards
  const grid = element("teams-grid");
  grid.replaceChildren();
  view[KEYS.teams].forEach(function (team) {
    const card = teamCard(team[KEYS.name], "", "");
    card.dataset.dropTeam = team[KEYS.name];
    team[KEYS.members].forEach(function (member) { card.appendChild(memberButton(member, false)); });
    team[KEYS.trainees].forEach(function (trainee) { card.appendChild(memberButton(trainee, true)); });
    grid.appendChild(card);
  });
  if (view[KEYS.teams].length) {
    // Always there, so a name can be dragged off a team into it.
    const card = teamCard("Off the teams", "", "extras");
    card.dataset.dropExtras = "1";
    view[KEYS.extras].forEach(function (member) {
      const button = memberButton(member, false);
      button.querySelector(".years").textContent = CONFIG.assignmentShortLabels[member[KEYS.assignment]] || member[KEYS.assignment] || "";
      card.appendChild(button);
      card.appendChild(extraJobChips(member, view));
    });
    if (!view[KEYS.extras].length) {
      const hint = document.createElement("p");
      hint.className = "drop-hint";
      hint.textContent = "Drag a name here to take them off the teams.";
      card.appendChild(hint);
    }
    grid.appendChild(card);
  }
  if (unplaced.length || unpaired.length) {
    const card = teamCard("Not placed yet", "", "unplaced");
    unplaced.forEach(function (member) { card.appendChild(memberButton(member, false)); });
    unpaired.forEach(function (trainee) { card.appendChild(memberButton(trainee, true)); });
    grid.appendChild(card);
  }
  if (judgeCount === 0) {
    grid.textContent = "No stroke & turn judges have signed in to this session yet.";
  }
}

/**
 * The job chips under someone off the teams: ACJ, Relief, and 15 m (offered when the
 * teams do not have their own 15 m judges, or when this person already has it).
 */
function extraJobChips(member, view) {
  const chips = document.createElement("div");
  chips.className = "job-chips";
  view[KEYS.extraAssignments].forEach(function (job) {
    const isCurrent = member[KEYS.assignment] === job;
    if (job === CONFIG.assignmentFifteenMeter && view[KEYS.fifteenMeterOnTeams] && !isCurrent) { return; }
    const chip = makeButton(CONFIG.assignmentShortLabels[job] || job, "chip small", function () {
      const body = {};
      body[KEYS.team] = null;
      body[KEYS.assignment] = job;
      teamsRequest(ROUTES.signinPrefix + member[KEYS.id] + ROUTES.teamSuffix, body);
    });
    chip.classList.toggle("on", isCurrent);
    chip.setAttribute("aria-pressed", isCurrent ? "true" : "false");
    chips.appendChild(chip);
  });
  return chips;
}

// --- Drag and drop on the Teams screen -----------------------------------------
// Press and drag a name (mouse: just drag; touch: hold briefly, then drag) and drop it:
// on another name to swap the two (a trainee dropped on someone makes them the
// mentor), on a team to move there, or on "Off the teams" to take them off (Relief).
// Pointer events, so it works the same with a finger, a mouse or a pen.

const DRAG_START_DISTANCE_PX = 8;
const TOUCH_HOLD_MILLISECONDS = 280;
const TOUCH_SLOP_PX = 12;
const DRAG_EDGE_PX = 48;
const DRAG_SCROLL_STEP_PX = 14;
let drag = null; // {button, pointerId, startX, startY, active, ghost, holdTimer, target}
let dragJustEnded = false;

function enableDrag(button) {
  button.addEventListener("pointerdown", startPress);
  button.addEventListener("contextmenu", function (event) { event.preventDefault(); });
}

function startPress(event) {
  if (event.button !== undefined && event.button > 0) { return; }
  if (event.target.closest(".star-toggle")) { return; } // the star is a tap, not a drag
  cancelDrag();
  drag = {
    button: event.currentTarget,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    active: false,
    ghost: null,
    holdTimer: null,
    target: null,
  };
  if (event.pointerType === "touch") {
    // Touch: a short hold starts the drag; moving first is an ordinary scroll.
    drag.holdTimer = setTimeout(function () { if (drag) { beginDrag(drag.startX, drag.startY); } }, TOUCH_HOLD_MILLISECONDS);
  }
  document.addEventListener("pointermove", movePress);
  document.addEventListener("pointerup", endPress);
  document.addEventListener("pointercancel", cancelDrag);
}

function beginDrag(x, y) {
  drag.active = true;
  clearTimeout(drag.holdTimer);
  try { drag.button.setPointerCapture(drag.pointerId); } catch (error) { /* capture is optional */ }
  const box = drag.button.getBoundingClientRect();
  const ghost = drag.button.cloneNode(true);
  ghost.classList.add("drag-ghost");
  ghost.style.width = box.width + "px";
  document.body.appendChild(ghost);
  drag.ghost = ghost;
  drag.offsetX = x - box.left;
  drag.offsetY = y - box.top;
  drag.button.classList.add("dragging");
  if (navigator.vibrate) { try { navigator.vibrate(15); } catch (error) { /* not supported */ } }
  placeGhost(x, y);
}

function placeGhost(x, y) {
  drag.ghost.style.left = (x - drag.offsetX) + "px";
  drag.ghost.style.top = (y - drag.offsetY) + "px";
}

/** The name or card under the finger: {kind: "member"|"team"|"extras", element}. */
function dropTargetAt(x, y) {
  const under = document.elementFromPoint(x, y);
  if (!under) { return null; }
  const member = under.closest("#teams-grid .member");
  if (member && member !== drag.button) { return { kind: "member", element: member }; }
  const card = under.closest("#teams-grid .team-card");
  if (card && card.dataset.dropTeam) { return { kind: "team", element: card }; }
  if (card && card.dataset.dropExtras) { return { kind: "extras", element: card }; }
  return null;
}

function movePress(event) {
  if (!drag || event.pointerId !== drag.pointerId) { return; }
  const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
  if (!drag.active) {
    if (event.pointerType === "touch") {
      if (distance > TOUCH_SLOP_PX) { cancelDrag(); } // the finger is scrolling
      return;
    }
    if (distance < DRAG_START_DISTANCE_PX) { return; }
    beginDrag(event.clientX, event.clientY);
  }
  event.preventDefault();
  placeGhost(event.clientX, event.clientY);
  const target = dropTargetAt(event.clientX, event.clientY);
  if (drag.target) { drag.target.element.classList.remove("drop-here"); }
  drag.target = target;
  if (target) { target.element.classList.add("drop-here"); }
  // Near the top or bottom of the Teams sheet: scroll it so every team can be reached.
  const sheet = teamsOverlay.querySelector(".sheet");
  const bounds = sheet.getBoundingClientRect();
  if (event.clientY < bounds.top + DRAG_EDGE_PX) { sheet.scrollTop -= DRAG_SCROLL_STEP_PX; }
  if (event.clientY > bounds.bottom - DRAG_EDGE_PX) { sheet.scrollTop += DRAG_SCROLL_STEP_PX; }
}

// While dragging with a finger, stop the page from scrolling under it.
document.addEventListener("touchmove", function (event) {
  if (drag && drag.active) { event.preventDefault(); }
}, { passive: false });

function endPress(event) {
  if (!drag || event.pointerId !== drag.pointerId) { return; }
  const finished = drag;
  const wasActive = drag.active;
  cancelDrag();
  if (!wasActive) { return; } // a plain tap: the button's click opens the place sheet
  dragJustEnded = true;
  setTimeout(function () { dragJustEnded = false; }, 0);
  if (finished.target) { dropOn(finished.button, finished.target); }
}

function cancelDrag() {
  if (!drag) { return; }
  clearTimeout(drag.holdTimer);
  if (drag.ghost) { drag.ghost.remove(); }
  if (drag.target) { drag.target.element.classList.remove("drop-here"); }
  drag.button.classList.remove("dragging");
  document.removeEventListener("pointermove", movePress);
  document.removeEventListener("pointerup", endPress);
  document.removeEventListener("pointercancel", cancelDrag);
  drag = null;
}

/** Carry out a drop: swap, pick a mentor, move to a team, or take off the teams. */
function dropOn(button, target) {
  const signinId = Number(button.dataset.signinId);
  const isTrainee = Boolean(button.dataset.trainee);
  const body = {};
  if (target.kind === "member") {
    const otherId = Number(target.element.dataset.signinId);
    if (isTrainee || target.element.dataset.trainee) {
      if (!isTrainee || target.element.dataset.trainee) {
        showToast("Drop a trainee on the official they will shadow", true);
        return;
      }
      body[KEYS.mentorSigninId] = otherId;
      teamsRequest(ROUTES.signinPrefix + signinId + ROUTES.teamSuffix, body);
      return;
    }
    body[KEYS.withSigninId] = otherId;
    teamsRequest(ROUTES.signinPrefix + signinId + ROUTES.swapSuffix, body);
    return;
  }
  if (isTrainee) {
    showToast("Drop a trainee on the official they will shadow", true);
    return;
  }
  if (target.kind === "team") {
    body[KEYS.team] = target.element.dataset.dropTeam;
    body[KEYS.assignment] = null;
  } else {
    body[KEYS.team] = null;
    body[KEYS.assignment] = CONFIG.assignmentRelief;
  }
  teamsRequest(ROUTES.signinPrefix + signinId + ROUTES.teamSuffix, body);
}

/**
 * The Jurisdiction box: lanes at each end, e.g. "Start end 1-8: 3-3-2" and
 * "Turn end 1-8: 2-3-3" (always opposite when uneven, to balance the deck).
 * "Flip jurisdiction" swaps the two ends; it only matters for an uneven split.
 */
function jurisdictionLines(view) {
  const entries = view[KEYS.jurisdictions] || [];
  return entries.map(function (entry) {
    const prefix = entries.length > 1 ? "Teams of " + entry[KEYS.judgeCount] + ": " : "";
    return prefix + "Start end " + entry[KEYS.laneRange] + ": " + entry[KEYS.startEnd]
      + "   ·   Turn end " + entry[KEYS.laneRange] + ": " + entry[KEYS.turnEnd];
  });
}

function drawJurisdiction(view) {
  const box = element("teams-jurisdiction");
  box.replaceChildren();
  const lines = jurisdictionLines(view);
  if (!lines.length) { box.textContent = "Build the teams to see the lanes."; }
  lines.forEach(function (text) {
    const line = document.createElement("div");
    line.className = "jurisdiction-line";
    line.textContent = text;
    box.appendChild(line);
  });
  const uneven = (view[KEYS.jurisdictions] || []).some(function (entry) { return entry[KEYS.uneven]; });
  const flip = element("teams-flip");
  flip.checked = Boolean(view[KEYS.jurisdictionFlipped]);
  flip.disabled = !uneven;
  flip.closest("label").title = uneven ? "" : "Both ends are the same, so there is nothing to flip";
}

/** Find an official in the team view by sign-in ID. */
function findInTeamView(signinId) {
  const view = teamView;
  let found = null;
  view[KEYS.teams].forEach(function (team) {
    team[KEYS.members].concat(team[KEYS.trainees]).forEach(function (item) {
      if (item[KEYS.id] === signinId) { found = item; }
    });
  });
  view[KEYS.extras].concat(view[KEYS.unplaced], view[KEYS.unpairedTrainees]).forEach(function (item) {
    if (item[KEYS.id] === signinId) { found = item; }
  });
  return found;
}

function postTeamChange(changes) {
  teamsRequest(ROUTES.signinPrefix + placeTarget.id + ROUTES.teamSuffix, changes);
}

function drawPlace() {
  const member = findInTeamView(placeTarget.id);
  if (!member) { placeOverlay.hidden = true; return; }
  element("place-name").textContent = member[KEYS.name];
  element("place-move-block").hidden = placeTarget.trainee;
  element("place-mentor-block").hidden = !placeTarget.trainee;
  if (placeTarget.trainee) {
    element("place-detail").textContent = "Trainee: shadows a mentor and moves with them.";
    const mentors = element("place-mentors");
    mentors.replaceChildren();
    teamView[KEYS.teams].forEach(function (team) {
      team[KEYS.members].forEach(function (candidate) {
        const chip = makeButton(candidate[KEYS.name] + " (" + team[KEYS.name] + ")", "chip", function () {
          const body = {};
          body[KEYS.mentorSigninId] = candidate[KEYS.id];
          postTeamChange(body);
        });
        chip.classList.toggle("on", candidate[KEYS.id] === member[KEYS.mentorSigninId]);
        mentors.appendChild(chip);
      });
    });
    return;
  }
  const years = member[KEYS.yearsCertified];
  element("place-detail").textContent = (years === null || years === undefined ? "Years certified unknown" : years + " years certified")
    + " · " + (member[KEYS.team] || member[KEYS.assignment] || "not placed");
  const teamChips = element("place-teams");
  teamChips.replaceChildren();
  teamView[KEYS.teams].forEach(function (team) {
    const chip = makeButton(team[KEYS.name], "chip", function () {
      const body = {};
      body[KEYS.team] = team[KEYS.name];
      body[KEYS.assignment] = null;
      postTeamChange(body);
    });
    chip.classList.toggle("on", member[KEYS.team] === team[KEYS.name]);
    teamChips.appendChild(chip);
  });
  const extraChips = element("place-extras");
  extraChips.replaceChildren();
  teamView[KEYS.extraAssignments].forEach(function (job) {
    const chip = makeButton(job, "chip", function () {
      const body = {};
      body[KEYS.team] = null;
      body[KEYS.assignment] = job;
      postTeamChange(body);
    });
    chip.classList.toggle("on", !member[KEYS.team] && member[KEYS.assignment] === job);
    extraChips.appendChild(chip);
  });
  element("place-team-options").hidden = !member[KEYS.team];
  element("place-lead").classList.toggle("on", Boolean(member[KEYS.teamLead]));
  element("place-fifteen").classList.toggle("on", member[KEYS.assignment] === CONFIG.assignmentFifteenMeter);
}

function rebuildTeams() {
  const button = element("teams-rebuild");
  if (!button.dataset.armed) {
    button.dataset.armed = "1";
    button.textContent = "Tap again: replaces your changes";
    setTimeout(function () { delete button.dataset.armed; button.textContent = "Rebuild automatically"; }, REBUILD_CONFIRM_SECONDS * 1000);
    return;
  }
  delete button.dataset.armed;
  button.textContent = "Rebuild automatically";
  teamsRequest(ROUTES.teamsBuild, {});
}

function closeTeams() {
  const unpaired = teamView ? teamView[KEYS.unpairedTrainees] : [];
  const hasTeams = teamView && teamView[KEYS.teams].some(function (team) { return team[KEYS.members].length > 0; });
  if (unpaired.length && hasTeams) {
    // Trainees must be paired with a certified official.
    showToast("Pair every trainee with a mentor first", true);
    return;
  }
  teamsOverlay.hidden = true;
  refresh();
}

// --- Meet overview and the demo meet ---------------------------------------------

const meetsOverlay = element("meets-overlay");
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

async function openMeetOverview(showResetWarning) {
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
  meetsOverlay.hidden = false;
}

async function archiveMeet(meet, archived) {
  const body = {};
  body[KEYS.archived] = archived;
  try {
    await postJson(ROUTES.meetPrefix + meet[KEYS.id] + ROUTES.meetArchiveSuffix, body);
    showToast(meet[KEYS.name] + (archived ? " archived" : " restored"));
    await openMeetOverview(false);
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
    await openMeetOverview(false);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function openMeet(meetId) {
  try {
    await postJson(ROUTES.meetPrefix + meetId + ROUTES.meetOpenSuffix, {});
    meetsOverlay.hidden = true;
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
    meetsOverlay.hidden = true;
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
    meetsOverlay.hidden = true;
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
  meetsOverlay.hidden = true;
  openSetup(true);
}

// --- Camera -------------------------------------------------------------------

/**
 * Open the shared camera window (card_camera.js) and read a card; then open (or
 * refresh) the sign-in sheet with what was read.
 * @param {object|null} forOfficial  The official whose sheet asked for the scan, if any.
 */
function startCamera(forOfficial) {
  window.CardCamera.read({ allowDiagnostics: true, onMessage: showToast }).then(function (result) {
    if (result.cancelled) { return; }
    if (result.reading === null) {
      showToast("Could not read the card. Sign in by name; the admin will check.", true);
      if (forOfficial) { openSheet(forOfficial, null, null); }
      return;
    }
    openSheet(result.reading[KEYS.match] || forOfficial, result.reading[KEYS.card], result.reading);
  }).catch(function (error) {
    showToast("Camera problem: " + error.message, true);
  });
}

// --- Sign-in sheet ---------------------------------------------------------------

/**
 * Open the sign-in sheet.
 * @param {object|null} official  Known official (from the search or a card match), or null for someone new.
 * @param {object|null} card  Card reading, if the card was scanned.
 * @param {object|null} cardResult  Server reply for the card (validated, problems).
 */
function openSheet(official, card, cardResult) {
  const typedName = searchInput.value.trim();
  sheet = {
    officialId: official ? official[KEYS.id] : null,
    card: card,
    cardResult: cardResult,
    roles: official && official[KEYS.roles].length ? official[KEYS.roles].slice() : [CONFIG.defaultRole],
    trainee: official ? official[KEYS.trainee] : false,
    laterSessionIds: [],
    official: official,
    editSigninId: null,
  };
  // A known official keeps their stored name (an OCR slip must not rename them).
  sheetName.value = official ? official[KEYS.name] : ((card && card[KEYS.cardName]) || typedName);
  // A name the camera read for someone new must be checked: it is what gets credited.
  markNameForChecking(!official && Boolean(card && card[KEYS.cardName]));
  showSheetMode(false);
  sheetYears.value = official && official[KEYS.yearsCertified] !== null ? official[KEYS.yearsCertified] : "";
  // LSC and club: from the card, else what is stored; the admin can fix either.
  window.Desk.fillLscSelect(element("sheet-lsc"), (card && card[KEYS.lsc]) || (official && official[KEYS.lsc]));
  sheetClub.value = (card && card[KEYS.club]) || (official && official[KEYS.club]) || "";
  drawSheetCheck();
  drawSheetRoles();
  sheetTrainee.classList.toggle("on", sheet.trainee);
  const later = laterSessionsToday();
  sheetLaterBlock.hidden = later.length === 0;
  sheetLater.replaceChildren();
  later.forEach(function (session) {
    const chip = makeButton(session[KEYS.name], "chip", function () {
      const index = sheet.laterSessionIds.indexOf(session[KEYS.id]);
      if (index >= 0) { sheet.laterSessionIds.splice(index, 1); } else { sheet.laterSessionIds.push(session[KEYS.id]); }
      chip.classList.toggle("on", index < 0);
    });
    sheetLater.appendChild(chip);
  });
  sheetOverlay.hidden = false;
}

/** Highlight the name box and show "check the spelling" (or clear it). */
function markNameForChecking(needsCheck) {
  sheetName.classList.toggle("check", needsCheck);
  element("sheet-name-hint").hidden = !needsCheck;
}

/** Sign-in mode (new sign-in) or edit mode (fix an existing sign-in). */
function showSheetMode(editing) {
  element("sheet-submit").textContent = editing ? "Save changes" : "Sign in";
  element("sheet-scan").hidden = editing;
  if (editing) { sheetLaterBlock.hidden = true; }
}

/**
 * Open the sheet to fix a sign-in that is already in the list: name (renames the
 * official everywhere), years certified, roles and trainee.
 * @param {object} signin  Sign-in row from the list.
 */
function openEditSheet(signin) {
  const official = {};
  official[KEYS.id] = signin[KEYS.officialId];
  official[KEYS.name] = signin[KEYS.name];
  official[KEYS.yearsCertified] = signin[KEYS.yearsCertified];
  official[KEYS.roles] = signin[KEYS.roles];
  official[KEYS.trainee] = signin[KEYS.trainee];
  official[KEYS.club] = signin[KEYS.club];
  official[KEYS.lsc] = signin[KEYS.lsc];
  official[KEYS.zone] = signin[KEYS.zone];
  openSheet(official, null, null);
  sheet.editSigninId = signin[KEYS.id];
  showSheetMode(true);
  sheetCheck.className = "check-line" + (signin[KEYS.validated] ? " ok" : " warn");
  sheetCheck.textContent = signin[KEYS.validated] ? "✓ Checked" : "Admin will check: " + signin[KEYS.problems].join("; ");
  sheetName.focus();
}

/** Save the edit sheet. */
async function saveEdit() {
  const body = {};
  body[KEYS.name] = sheetName.value.trim();
  const years = sheetYears.value.trim();
  body[KEYS.yearsCertified] = years === "" ? null : Math.round(Number(years));
  body[KEYS.roles] = sheet.roles;
  body[KEYS.trainee] = sheet.trainee;
  body[KEYS.lsc] = element("sheet-lsc").value;
  body[KEYS.club] = sheetClub.value.trim();
  try {
    const reply = await postJson(ROUTES.signinPrefix + sheet.editSigninId + ROUTES.editSuffix, body);
    sheetOverlay.hidden = true;
    const merged = reply[KEYS.merged];
    showToast("✓ Saved" + (merged ? " (merged " + merged + " duplicate record" + (merged === 1 ? "" : "s") + ")" : ""));
    await refresh();
  } catch (error) {
    showToast(error.message, true);
  }
}

function drawSheetCheck() {
  sheetCheck.className = "check-line";
  const official = sheet.official;
  if (sheet.cardResult) {
    if (sheet.cardResult[KEYS.validated]) {
      sheetCheck.textContent = "✓ Card checked: membership, background check and training are current";
      sheetCheck.classList.add("ok");
    } else {
      sheetCheck.textContent = "Admin will check: " + sheet.cardResult[KEYS.problems].join("; ");
      sheetCheck.classList.add("warn");
    }
  } else if (official && pageState.meet && official[KEYS.cardMeetId] === pageState.meet[KEYS.id]) {
    sheetCheck.textContent = "✓ Card already checked at this meet";
    sheetCheck.classList.add("ok");
  } else {
    sheetCheck.textContent = "Card not checked: tap Scan card, or the admin will check it";
    sheetCheck.classList.add("warn");
  }
}

function drawSheetRoles() {
  sheetRoles.replaceChildren();
  CONFIG.roles.forEach(function (role) {
    const chip = makeButton(role, "chip", function () {
      const index = sheet.roles.indexOf(role);
      if (index >= 0) { sheet.roles.splice(index, 1); } else { sheet.roles.push(role); }
      chip.classList.toggle("on", index < 0);
    });
    chip.classList.toggle("on", sheet.roles.indexOf(role) >= 0);
    sheetRoles.appendChild(chip);
  });
}

async function submitSheet() {
  if (sheet.editSigninId) {
    await saveEdit();
    return;
  }
  const body = {};
  body[KEYS.officialId] = sheet.officialId;
  body[KEYS.name] = sheetName.value.trim();
  const years = sheetYears.value.trim();
  body[KEYS.yearsCertified] = years === "" ? null : Math.round(Number(years));
  body[KEYS.roles] = sheet.roles;
  body[KEYS.trainee] = sheet.trainee;
  body[KEYS.sessionIds] = [pageState.activeSessionId].concat(sheet.laterSessionIds);
  body[KEYS.lsc] = element("sheet-lsc").value;
  body[KEYS.club] = sheetClub.value.trim();
  if (sheet.card) { body[KEYS.card] = sheet.card; }
  try {
    const reply = await postJson(ROUTES.signins, body);
    sheetOverlay.hidden = true;
    searchInput.value = "";
    const name = body[KEYS.name] || "Signed in";
    showToast(reply[KEYS.validated] ? "✓ " + name + " signed in" : name + " signed in. The admin will check the card.");
    await refresh();
  } catch (error) {
    showToast(error.message, true);
  }
}

// --- Wiring -----------------------------------------------------------------------

captureButton.addEventListener("click", function () { startCamera(null); });
searchInput.addEventListener("input", drawMatches);
newPersonButton.addEventListener("click", function () { openSheet(null, null, null); });
sheetTrainee.addEventListener("click", function () {
  sheet.trainee = !sheet.trainee;
  sheetTrainee.classList.toggle("on", sheet.trainee);
});
element("sheet-scan").addEventListener("click", function () {
  sheetOverlay.hidden = true;
  startCamera(sheet.official || null);
});
sheetName.addEventListener("input", function () { markNameForChecking(false); });
element("sheet-cancel").addEventListener("click", function () { sheetOverlay.hidden = true; });
element("sheet-submit").addEventListener("click", submitSheet);
element("setup-button").addEventListener("click", function () { openSetup(false); });
// --- The ☰ menu ------------------------------------------------------------------

function setMenuOpen(open) {
  if (open) {
    // Just under the top bar, wherever it is (the demo banner pushes it down).
    mainMenu.style.top = (document.querySelector("header").getBoundingClientRect().bottom + 4) + "px";
  }
  mainMenu.hidden = !open;
  element("menu-button").setAttribute("aria-expanded", open ? "true" : "false");
}

element("menu-button").addEventListener("click", function (event) {
  event.stopPropagation();
  setMenuOpen(mainMenu.hidden);
});
// Any choice in the menu, a tap elsewhere or Escape closes it.
mainMenu.addEventListener("click", function () { setMenuOpen(false); });
document.addEventListener("click", function (event) {
  if (!mainMenu.hidden && !mainMenu.contains(event.target)) { setMenuOpen(false); }
});
document.addEventListener("keydown", function (event) { if (event.key === "Escape") { setMenuOpen(false); } });
element("meet-zip-link").addEventListener("click", function () { showToast("Saving the meet as a zip file…"); });
sessionSelect.addEventListener("change", function () { chooseSession(Number(sessionSelect.value)); });

element("meets-button").addEventListener("click", function () { openMeetOverview(false); });
element("setup-meets").addEventListener("click", function () {
  closeSetup();
  openMeetOverview(false);
});
element("meets-close").addEventListener("click", function () { showDemoResetWarning(false); meetsOverlay.hidden = true; });
element("meets-new").addEventListener("click", newMeetFromOverview);
element("archived-toggle").addEventListener("click", function () {
  showArchivedMeets = !showArchivedMeets;
  openMeetOverview(false);
});
element("meet-delete-keep").addEventListener("click", closeMeetDeleteWarning);
element("meet-delete-confirm").addEventListener("click", deleteMeet);
element("demo-open").addEventListener("click", openDemo);
element("demo-reset-overview").addEventListener("click", function () { showDemoResetWarning(true); });
element("demo-reset-cancel").addEventListener("click", function () { showDemoResetWarning(false); });
element("demo-reset-confirm").addEventListener("click", resetDemo);
element("demo-reset").addEventListener("click", function () { openMeetOverview(true); });
element("demo-exit").addEventListener("click", async function () {
  await postJson(ROUTES.demoExit, {});
  window.Desk.announceChange();
  window.location.reload();
});
element("teams-button").addEventListener("click", askBeforeTeams);
element("teams-check-back").addEventListener("click", function () { element("teams-check-overlay").hidden = true; });
element("teams-check-continue").addEventListener("click", function () {
  element("teams-check-overlay").hidden = true;
  openTeams();
});
element("teams-close").addEventListener("click", closeTeams);
element("teams-rebuild").addEventListener("click", rebuildTeams);
element("teams-flip").addEventListener("change", function () {
  const body = {};
  body[KEYS.jurisdictionFlipped] = element("teams-flip").checked;
  teamsRequest(ROUTES.teamsSettings, body);
});
element("teams-fifteen").addEventListener("change", function () {
  const body = {};
  body[KEYS.fifteenMeterOnTeams] = element("teams-fifteen").checked;
  // Adjusts the current teams in place; hand changes are kept.
  teamsRequest(ROUTES.teamsSettings, body);
});
element("place-close").addEventListener("click", function () { placeOverlay.hidden = true; });
element("place-lead").addEventListener("click", function () {
  const member = findInTeamView(placeTarget.id);
  const body = {};
  body[KEYS.teamLead] = !(member && member[KEYS.teamLead]);
  postTeamChange(body);
});
element("place-fifteen").addEventListener("click", function () {
  const member = findInTeamView(placeTarget.id);
  const body = {};
  body[KEYS.assignment] = member && member[KEYS.assignment] === CONFIG.assignmentFifteenMeter ? null : CONFIG.assignmentFifteenMeter;
  postTeamChange(body);
});
element("setup-cancel").addEventListener("click", closeSetup);
element("setup-save").addEventListener("click", saveSetup);
element("session-add-row").addEventListener("click", addFollowingRow);
element("row-delete-keep").addEventListener("click", closeRowWarning);
element("row-delete-confirm").addEventListener("click", deleteSavedRow);
// The ✕ in a sheet's corner does what that sheet's own close button does.
document.querySelectorAll(".sheet-close").forEach(function (closeButton) {
  closeButton.addEventListener("click", function () { element(closeButton.dataset.closes).click(); });
});

// Name this tab, so the coaches page's "Officials sign-in" comes back to it.
window.name = CONFIG.officialsTabName;
// Stay on the same meet and session as the coaches tab (see desk_shared.js).
window.Desk.followChanges(refresh);

refresh().then(function () {
  // "Back to Teams" from the team page: open Teams straight away (and tidy the address).
  const query = new URLSearchParams(window.location.search);
  if (query.get(CONFIG.openQueryKey) === CONFIG.openTeamsValue && pageState.activeSessionId !== null) {
    window.history.replaceState(null, "", window.location.pathname);
    openTeams();
  }
  // Nothing to sign in to yet: go straight to Meet setup.
  if (pageState.activeSessionId === null) { openSetup(false); }
  // Load the OCR engine in the background so the first scan starts quickly.
  if (window.CardScanner) {
    window.CardScanner.warmUp().catch(function () { showToast("The card reader could not load", true); });
  }
});
