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
const sessionChips = element("session-chips");
const captureButton = element("capture-button");
const searchInput = element("search");
const matchList = element("matches");
const newPersonButton = element("new-person");
const deskPanel = element("desk-panel");
const noSessionPanel = element("no-session-panel");
const signinsTitle = element("signins-title");
const signinsList = element("signins");
const cameraOverlay = element("camera-overlay");
const cameraVideo = element("camera-video");
const cameraStatus = element("camera-status");
const cameraFields = element("camera-fields");
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
let activeScan = null;
let lastScanReading = null;
let scanForOfficial = null; // official whose sheet asked for the scan, if any
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

function describeOfficial(official) {
  const parts = [];
  if (official[KEYS.club]) { parts.push((official[KEYS.lsc] ? official[KEYS.lsc] + "-" : "") + official[KEYS.club]); }
  if (official[KEYS.zone]) { parts.push(official[KEYS.zone] + " zone"); }
  if (official[KEYS.yearsCertified] !== null && official[KEYS.yearsCertified] !== undefined) {
    parts.push(official[KEYS.yearsCertified] + " yr certified");
  }
  return parts.join(" · ");
}

// --- Loading and drawing -------------------------------------------------------

async function refresh() {
  const state = await getJson(ROUTES.state);
  pageState = {
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
  sessionChips.replaceChildren();
  pageState.sessions.forEach(function (session) {
    const chip = makeButton(session[KEYS.name], "session-chip", function () { chooseSession(session[KEYS.id]); });
    chip.classList.toggle("on", session[KEYS.id] === pageState.activeSessionId);
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = String(session[KEYS.signinCount]);
    chip.appendChild(count);
    sessionChips.appendChild(chip);
  });
  const ready = pageState.activeSessionId !== null;
  deskPanel.hidden = !ready;
  noSessionPanel.hidden = ready;
  const session = activeSession();
  const meetingTime = element("meeting-time");
  meetingTime.hidden = !(session && session[KEYS.meetingTime]);
  meetingTime.textContent = meetingTime.hidden ? "" : "Officials Meeting: " + formatTime12(session[KEYS.meetingTime]);
  signinsTitle.textContent = session ? "Signed in: " + session[KEYS.name] : "Signed in";
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
// The two session forms in Meet setup share one set of field names, with these id prefixes.
const ADD_FORM = "session-";
const FIRST_FORM = "first-session-";
const SESSION_FIELD_TYPE = "type";
const SESSION_FIELD_TYPE_OTHER = "type-other";
const SESSION_FIELD_DATE = "date";
const SESSION_FIELD_TIME = "time";
const SESSION_FIELD_MEETING = "meeting";
const SESSION_FIELD_NAME = "name";
let editingSessionId = null;

/** One field of a session form. */
function sessionField(form, fieldName) {
  return element(form + fieldName);
}

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

/** The session type chosen in a form ("" if none). */
function sessionTypeOf(form) {
  const select = sessionField(form, SESSION_FIELD_TYPE);
  if (select.value === OTHER_TYPE_VALUE) { return sessionField(form, SESSION_FIELD_TYPE_OTHER).value.trim(); }
  return select.value;
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

/**
 * Fill in whatever the admin has not set by hand: the type follows the start
 * time (AM/PM), the officials meeting is an hour before the start, and the name
 * is suggested from the date and type.
 */
function autoFillSession(form) {
  const time = sessionField(form, SESSION_FIELD_TIME).value;
  const select = sessionField(form, SESSION_FIELD_TYPE);
  if (!select.dataset.chosen && time) {
    select.value = minutesOfDay(time) < NOON_HOUR * MINUTES_PER_HOUR ? TYPE_AM : TYPE_PM;
  }
  const meeting = sessionField(form, SESSION_FIELD_MEETING);
  if (!meeting.dataset.typed) {
    meeting.value = time ? hoursMinutesOf(minutesOfDay(time) - CONFIG.meetingMinutesBeforeStart) : "";
  }
  const name = sessionField(form, SESSION_FIELD_NAME);
  if (!name.dataset.typed) {
    name.value = suggestSessionName(sessionField(form, SESSION_FIELD_DATE).value, sessionTypeOf(form));
  }
}

/** Clear a session form so everything follows the suggestions again. */
function resetSessionForm(form) {
  [SESSION_FIELD_TIME, SESSION_FIELD_MEETING, SESSION_FIELD_NAME, SESSION_FIELD_TYPE_OTHER].forEach(function (fieldName) {
    const input = sessionField(form, fieldName);
    input.value = "";
    delete input.dataset.typed;
  });
  const select = sessionField(form, SESSION_FIELD_TYPE);
  select.value = "";
  delete select.dataset.chosen;
  sessionField(form, SESSION_FIELD_TYPE_OTHER).hidden = true;
}

/** Build the type drop-down: a blank choice, the usual types, then "Other…". */
function fillTypeOptions(form) {
  const select = sessionField(form, SESSION_FIELD_TYPE);
  select.replaceChildren();
  // "|| []": a page served by an older server process still loads (without the list).
  [["", "—"]].concat((CONFIG.sessionTypes || []).map(function (type) { return [type, type]; }))
    .concat([[OTHER_TYPE_VALUE, CONFIG.sessionTypeOtherLabel]])
    .forEach(function (pair) {
      const option = document.createElement("option");
      option.value = pair[0];
      option.textContent = pair[1];
      select.appendChild(option);
    });
}

/** Wire one session form's auto-fill behaviour. */
function wireSessionForm(form) {
  fillTypeOptions(form);
  const select = sessionField(form, SESSION_FIELD_TYPE);
  const other = sessionField(form, SESSION_FIELD_TYPE_OTHER);
  select.addEventListener("change", function () {
    select.dataset.chosen = "1";
    other.hidden = select.value !== OTHER_TYPE_VALUE;
    if (!other.hidden) { other.focus(); }
    autoFillSession(form);
  });
  other.addEventListener("input", function () { autoFillSession(form); });
  [SESSION_FIELD_DATE, SESSION_FIELD_TIME].forEach(function (fieldName) {
    sessionField(form, fieldName).addEventListener("change", function () { autoFillSession(form); });
  });
  // Typing in the name or meeting time stops the suggestions for that box.
  [SESSION_FIELD_NAME, SESSION_FIELD_MEETING].forEach(function (fieldName) {
    const input = sessionField(form, fieldName);
    input.addEventListener("input", function () { input.dataset.typed = "1"; });
  });
}

/** The request body for a session form. */
function sessionBody(form) {
  const body = {};
  const sessionType = sessionTypeOf(form);
  body[KEYS.name] = sessionField(form, SESSION_FIELD_NAME).value.trim()
    || suggestSessionName(sessionField(form, SESSION_FIELD_DATE).value, sessionType);
  body[KEYS.date] = sessionField(form, SESSION_FIELD_DATE).value;
  body[KEYS.startTime] = sessionField(form, SESSION_FIELD_TIME).value || null;
  body[KEYS.sessionType] = sessionType || null;
  body[KEYS.meetingTime] = sessionField(form, SESSION_FIELD_MEETING).value || null;
  return body;
}

/** Sessions after the last one start on its date (multi-day meets add days in order). */
function nextSessionDate() {
  const sessions = pageState.sessions;
  if (sessions.length > 0) { return sessions[sessions.length - 1][KEYS.date]; }
  return pageState.meet ? pageState.meet[KEYS.startDate] : isoToday();
}

function describeSession(session) {
  const parts = [session[KEYS.date]];
  if (session[KEYS.startTime]) { parts.push("starts " + formatTime12(session[KEYS.startTime])); }
  if (session[KEYS.meetingTime]) { parts.push("officials meeting " + formatTime12(session[KEYS.meetingTime])); }
  parts.push(session[KEYS.signinCount] + " signed in");
  return parts.join(" · ");
}

function drawSetupSessions() {
  const list = element("setup-session-list");
  list.replaceChildren();
  if (pageState.sessions.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "No sessions yet. Add the first one below.";
    list.appendChild(empty);
    return;
  }
  pageState.sessions.forEach(function (session) {
    const item = document.createElement("li");
    const button = makeButton("", "", function () { editSession(session); });
    button.classList.toggle("editing", session[KEYS.id] === editingSessionId);
    const hint = document.createElement("span");
    hint.className = "edit-hint";
    hint.textContent = "Edit";
    const name = document.createElement("strong");
    name.textContent = session[KEYS.name];
    const detail = document.createElement("span");
    detail.className = "signin-detail";
    detail.textContent = "  " + describeSession(session);
    button.append(hint, name, detail);
    item.appendChild(button);
    list.appendChild(item);
  });
}

/** Load a session into the "Add a session" form to change it. */
function editSession(session) {
  editingSessionId = session[KEYS.id];
  resetSessionForm(ADD_FORM);
  const select = sessionField(ADD_FORM, SESSION_FIELD_TYPE);
  const sessionType = session[KEYS.sessionType] || "";
  if (sessionType && CONFIG.sessionTypes.indexOf(sessionType) < 0) {
    select.value = OTHER_TYPE_VALUE;
    sessionField(ADD_FORM, SESSION_FIELD_TYPE_OTHER).value = sessionType;
    sessionField(ADD_FORM, SESSION_FIELD_TYPE_OTHER).hidden = false;
  } else {
    select.value = sessionType;
  }
  select.dataset.chosen = "1";
  sessionField(ADD_FORM, SESSION_FIELD_DATE).value = session[KEYS.date];
  sessionField(ADD_FORM, SESSION_FIELD_TIME).value = session[KEYS.startTime] || "";
  // Keep the saved values; changing the start time still moves an unchanged meeting time.
  sessionField(ADD_FORM, SESSION_FIELD_MEETING).value = session[KEYS.meetingTime] || "";
  sessionField(ADD_FORM, SESSION_FIELD_MEETING).dataset.typed = "1";
  sessionField(ADD_FORM, SESSION_FIELD_NAME).value = session[KEYS.name];
  sessionField(ADD_FORM, SESSION_FIELD_NAME).dataset.typed = "1";
  showSessionFormMode();
  drawSetupSessions();
}

function stopEditingSession() {
  editingSessionId = null;
  resetSessionForm(ADD_FORM);
  sessionField(ADD_FORM, SESSION_FIELD_DATE).value = nextSessionDate();
  autoFillSession(ADD_FORM);
  showSessionFormMode();
  drawSetupSessions();
}

function showSessionFormMode() {
  const editing = editingSessionId !== null;
  element("session-form-title").textContent = editing ? "Edit session" : "Add a session";
  sessionField(ADD_FORM, "save").textContent = editing ? "Save changes" : "Add session";
  element("session-edit-actions").hidden = !editing;
  element("session-delete-warning").hidden = true;
}

/** Show the big warning before deleting the session being edited. */
function askDeleteSession() {
  const session = pageState.sessions.find(function (item) { return item[KEYS.id] === editingSessionId; });
  if (!session) { return; }
  const count = session[KEYS.signinCount];
  element("session-delete-name").textContent = session[KEYS.name];
  element("session-delete-detail").textContent = count === 0
    ? "Nobody has signed in to it yet."
    : "Its " + count + " sign-in" + (count === 1 ? "" : "s") + " and team placements will be deleted too. "
      + "The officials themselves stay in the app for next time.";
  element("session-delete-warning").hidden = false;
}

async function deleteSession() {
  const session = pageState.sessions.find(function (item) { return item[KEYS.id] === editingSessionId; });
  if (!session) { return; }
  try {
    await postJson(ROUTES.sessionPrefix + session[KEYS.id] + ROUTES.sessionDeleteSuffix, {});
    await refresh();
    stopEditingSession();
    showToast(session[KEYS.name] + " deleted");
  } catch (error) {
    showToast(error.message, true);
  }
}

/**
 * Show Meet setup. With no meet, only the "new meet + first session" form;
 * with a meet, its sessions and the "Add session" form.
 * @param {boolean} showNewMeet  Also open the "Start a different meet" form.
 */
function openSetup(showNewMeet) {
  const hasMeet = pageState.meet !== null;
  element("current-meet-block").hidden = !hasMeet;
  element("new-meet-block").hidden = hasMeet && !showNewMeet;
  element("new-meet-toggle").hidden = !hasMeet || Boolean(showNewMeet);
  element("new-meet-cancel").hidden = !hasMeet;
  element("new-meet-block").classList.toggle("separated", hasMeet);
  // With no meet there is nothing to go back to, so the only way out is "Create meet".
  element("setup-close").hidden = !hasMeet;
  if (hasMeet) {
    element("current-meet-name").textContent = pageState.meet[KEYS.name];
    element("current-meet-date").textContent = "starts " + pageState.meet[KEYS.startDate];
    if (editingSessionId === null) {
      sessionField(ADD_FORM, SESSION_FIELD_DATE).value = nextSessionDate();
      autoFillSession(ADD_FORM);
    }
    showSessionFormMode();
    drawSetupSessions();
  }
  if (!hasMeet || showNewMeet) {
    element("new-meet-date").value = element("new-meet-date").value || isoToday();
    sessionField(FIRST_FORM, SESSION_FIELD_DATE).value = element("new-meet-date").value;
    autoFillSession(FIRST_FORM);
  }
  setupOverlay.hidden = false;
}

/** Create a meet and its first session in one tap. */
async function createMeetWithSession() {
  const meetBody = {};
  meetBody[KEYS.name] = element("new-meet-name").value.trim();
  meetBody[KEYS.startDate] = element("new-meet-date").value;
  const firstSession = sessionBody(FIRST_FORM);
  if (!meetBody[KEYS.name] || !meetBody[KEYS.startDate]) {
    showToast("Enter the meet name and start date", true);
    return;
  }
  if (!firstSession[KEYS.date]) {
    showToast("Enter the first session's date", true);
    return;
  }
  try {
    await postJson(ROUTES.meets, meetBody);
    await postJson(ROUTES.sessions, firstSession);
    element("new-meet-name").value = "";
    resetSessionForm(FIRST_FORM);
    editingSessionId = null;
    await refresh();
    openSetup(false);
    showToast(meetBody[KEYS.name] + " created with " + firstSession[KEYS.name]);
  } catch (error) {
    await refresh();
    openSetup(false);
    showToast(error.message, true);
  }
}

/** Add a session, or save the one being edited. */
async function saveSession() {
  const body = sessionBody(ADD_FORM);
  const editing = editingSessionId !== null;
  try {
    await postJson(editing ? ROUTES.sessionPrefix + editingSessionId : ROUTES.sessions, body);
    await refresh();
    stopEditingSession();
    showToast(body[KEYS.name] + (editing ? " saved" : " added"));
  } catch (error) {
    showToast(error.message, true);
  }
}

// --- Camera -------------------------------------------------------------------

function drawCameraFields(card) {
  cameraFields.replaceChildren();
  CONFIG.cardFields.forEach(function (pair) {
    const chip = document.createElement("span");
    const read = card && card[pair[0]] !== null && card[pair[0]] !== undefined;
    chip.className = "field-chip" + (read ? " read" : "");
    chip.textContent = (read ? "✓ " : "") + pair[1];
    cameraFields.appendChild(chip);
  });
}

/**
 * Open the camera and read a card. When done, open (or refresh) the sign-in sheet.
 * @param {object|null} forOfficial  The official whose sheet is open, if any.
 */
function startCamera(forOfficial) {
  if (!window.CardScanner) {
    showToast("The card reader did not load", true);
    return;
  }
  lastScanReading = null;
  scanForOfficial = forOfficial;
  drawCameraFields(null);
  cameraOverlay.hidden = false;
  element("camera-diagnostics").checked = window.CardScanner.diagnosticsEnabled();
  activeScan = window.CardScanner.scan({
    video: cameraVideo,
    diagnostics: window.CardScanner.diagnosticsEnabled,
    onStatus: function (text) { cameraStatus.textContent = text; },
    onProgress: function (reading) {
      lastScanReading = reading;
      drawCameraFields(reading[KEYS.card]);
      cameraStatus.textContent = "Reading… hold still";
    },
  });
  activeScan.result.then(function (reading) {
    finishCamera(reading, forOfficial, false);
  }).catch(function (error) {
    cameraOverlay.hidden = true;
    activeScan = null;
    showToast("Camera problem: " + error.message, true);
  });
}

/** Close the camera and open the sheet with whatever was read. */
function finishCamera(reading, forOfficial, cancelled) {
  if (activeScan === null) { return; }
  activeScan = null;
  cameraOverlay.hidden = true;
  if (cancelled) { return; }
  if (reading === null) {
    showToast("Could not read the card. Sign in by name; the admin will check.", true);
    if (forOfficial) { openSheet(forOfficial, null, null); }
    return;
  }
  const match = reading[KEYS.match];
  openSheet(match || forOfficial, reading[KEYS.card], reading);
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
  };
  sheetName.value = (card && card[KEYS.cardName]) || (official ? official[KEYS.name] : typedName);
  sheetYears.value = official && official[KEYS.yearsCertified] !== null ? official[KEYS.yearsCertified] : "";
  const clubSource = card || official;
  sheetClub.textContent = clubSource ? describeOfficial(clubSource) : "";
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
  const body = {};
  body[KEYS.officialId] = sheet.officialId;
  body[KEYS.name] = sheetName.value.trim();
  const years = sheetYears.value.trim();
  body[KEYS.yearsCertified] = years === "" ? null : Math.round(Number(years));
  body[KEYS.roles] = sheet.roles;
  body[KEYS.trainee] = sheet.trainee;
  body[KEYS.sessionIds] = [pageState.activeSessionId].concat(sheet.laterSessionIds);
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
element("camera-cancel").addEventListener("click", function () {
  if (activeScan) { activeScan.cancel(); }
  finishCamera(null, null, true);
});
element("camera-done").addEventListener("click", function () {
  if (activeScan) { activeScan.cancel(); }
  finishCamera(lastScanReading, scanForOfficial, false);
});
element("camera-diagnostics").addEventListener("change", function () {
  // Takes effect at once, also during a scan.
  window.CardScanner.setDiagnosticsEnabled(element("camera-diagnostics").checked);
  showToast(element("camera-diagnostics").checked ? "Saving frames for troubleshooting" : "Not saving frames");
});
element("camera-switch").addEventListener("click", function () { if (activeScan) { activeScan.switchCamera(); } });
sheetTrainee.addEventListener("click", function () {
  sheet.trainee = !sheet.trainee;
  sheetTrainee.classList.toggle("on", sheet.trainee);
});
element("sheet-scan").addEventListener("click", function () {
  sheetOverlay.hidden = true;
  startCamera(sheet.official || null);
});
element("sheet-cancel").addEventListener("click", function () { sheetOverlay.hidden = true; });
element("sheet-submit").addEventListener("click", submitSheet);
element("setup-button").addEventListener("click", function () { openSetup(false); });
element("setup-close").addEventListener("click", function () {
  setupOverlay.hidden = true;
  if (editingSessionId !== null) { stopEditingSession(); }
});
element("new-meet-toggle").addEventListener("click", function () { openSetup(true); });
element("new-meet-cancel").addEventListener("click", function () { openSetup(false); });
element("new-meet-create").addEventListener("click", createMeetWithSession);
sessionField(ADD_FORM, "save").addEventListener("click", saveSession);
element("session-edit-cancel").addEventListener("click", stopEditingSession);
element("session-delete").addEventListener("click", askDeleteSession);
element("session-delete-keep").addEventListener("click", function () { element("session-delete-warning").hidden = true; });
element("session-delete-confirm").addEventListener("click", deleteSession);
wireSessionForm(ADD_FORM);
wireSessionForm(FIRST_FORM);
// The first session follows the meet's start date until it is changed.
element("new-meet-date").addEventListener("change", function () {
  sessionField(FIRST_FORM, SESSION_FIELD_DATE).value = element("new-meet-date").value;
  autoFillSession(FIRST_FORM);
});

refresh().then(function () {
  // Nothing to sign in to yet: go straight to Meet setup.
  if (pageState.activeSessionId === null) { openSetup(false); }
  // Load the OCR engine in the background so the first scan starts quickly.
  if (window.CardScanner) {
    window.CardScanner.warmUp().catch(function () { showToast("The card reader could not load", true); });
  }
});
