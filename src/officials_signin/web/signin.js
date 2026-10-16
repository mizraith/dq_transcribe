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
    count.textContent = String(session.signin_count);
    chip.appendChild(count);
    sessionChips.appendChild(chip);
  });
  const ready = pageState.activeSessionId !== null;
  deskPanel.hidden = !ready;
  noSessionPanel.hidden = ready;
  const session = activeSession();
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

function openSetup() {
  const today = new Date();
  const isoToday = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  element("meet-date-input").value = element("meet-date-input").value || isoToday;
  element("session-date-input").value = pageState.meet ? pageState.meet[KEYS.startDate] : isoToday;
  element("session-setup").hidden = pageState.meet === null;
  setupOverlay.hidden = false;
}

async function createMeet() {
  const body = {};
  body[KEYS.name] = element("meet-name-input").value.trim();
  body[KEYS.startDate] = element("meet-date-input").value;
  try {
    await postJson(ROUTES.meets, body);
    element("meet-name-input").value = "";
    await refresh();
    openSetup();
    showToast("Meet created. Now add its sessions.");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function addSession() {
  const body = {};
  body[KEYS.name] = element("session-name-input").value.trim();
  body[KEYS.date] = element("session-date-input").value;
  body[KEYS.startTime] = element("session-time-input").value || null;
  try {
    await postJson(ROUTES.sessions, body);
    element("session-name-input").value = "";
    element("session-time-input").value = "";
    await refresh();
    showToast("Session added");
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
  activeScan = window.CardScanner.scan({
    video: cameraVideo,
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
element("setup-button").addEventListener("click", openSetup);
element("setup-close").addEventListener("click", function () { setupOverlay.hidden = true; });
element("meet-create").addEventListener("click", createMeet);
element("session-add").addEventListener("click", addSession);

refresh().then(function () {
  if (pageState.meet === null) { openSetup(); }
  // Load the OCR engine in the background so the first scan starts quickly.
  if (window.CardScanner) {
    window.CardScanner.warmUp().catch(function () { showToast("The card reader could not load", true); });
  }
});
