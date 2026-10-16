/**
 * Coaches Sign-In page: sign coaches in to the session from their USA Swimming card
 * (or by name), keep the list, mark head coaches.
 *
 * Works like the officials page (signin.js) without teams, roles or years: the same
 * camera window and card reader (card_camera.js and card_scanner.js, shared with the
 * officials page; the card text goes to the coaches' own card-reading route), the
 * same session drop-down (the session is shared with the officials page), the
 * same "Looks good" / Edit / Remove on each row, plus a Head coach toggle (any number
 * per club).
 *
 * This file is a string.Template: the config placeholder below is replaced by
 * officials_signin.coaches.render_script, so never use a literal dollar sign here.
 */
"use strict";

const CONFIG = ${config};
const KEYS = CONFIG.keys;
const ROUTES = CONFIG.routes;
const MATCH_LIMIT = 8;
const REMOVE_CONFIRM_SECONDS = 3;
const HEAD_ON_LABEL = "★ Head coach";
const HEAD_OFF_LABEL = "☆ Head coach";

const element = window.Desk.element;
const getJson = window.Desk.getJson;
const postJson = window.Desk.postJson;
const makeButton = window.Desk.makeButton;
const showToast = window.Desk.showToast;
const searchInput = element("search");
const matchList = element("matches");
const newPersonButton = element("new-person");
const signinsList = element("signins");
const sheetOverlay = element("sheet-overlay");

let pageState = { demo: false, meet: null, sessions: [], activeSessionId: null, coaches: [] };
let knownCoaches = [];
let sheet = null; // the sign-in sheet's state while it is open

// --- Helpers -------------------------------------------------------------------------

function nameKey(text) {
  return text.toLowerCase().replace(/[^a-z]+/g, "");
}

function activeSession() {
  return pageState.sessions.find(function (session) { return session[KEYS.id] === pageState.activeSessionId; }) || null;
}

/** Sessions later on the same day as the active one (sign in for those too). */
function laterSessionsToday() {
  const active = activeSession();
  if (active === null) { return []; }
  const index = pageState.sessions.indexOf(active);
  return pageState.sessions.slice(index + 1).filter(function (session) { return session[KEYS.date] === active[KEYS.date]; });
}

/** "PASA · Pacific Swimming" for a coach (the shared Desk helper). */
function describeCoach(coach) {
  return window.Desk.describeClub(coach);
}

// --- Loading and drawing ---------------------------------------------------------------

async function refresh() {
  const state = await getJson(ROUTES.coachesState);
  pageState = {
    demo: Boolean(state[KEYS.demo]),
    meet: state[KEYS.meet],
    sessions: state[KEYS.sessions],
    activeSessionId: state[KEYS.activeSessionId],
    coaches: state[KEYS.coaches],
  };
  knownCoaches = (await getJson(ROUTES.coachesKnown))[KEYS.coaches];
  drawHeader();
  drawCoaches();
  drawMatches();
}

function drawHeader() {
  // The session drop-down: "Friday PM  ·  6" (6 coaches signed in); picking one makes it current everywhere.
  window.Desk.drawSessionPicker(pageState.meet, pageState.sessions, pageState.activeSessionId, KEYS.coachCount);
  const ready = pageState.activeSessionId !== null;
  element("desk-panel").hidden = !ready;
  element("print-panel").hidden = !ready;
  element("no-session-panel").hidden = ready;
  const session = activeSession();
  element("signins-title").textContent = session ? "Coaches signed in: " + session[KEYS.name] : "Coaches signed in";
  element("demo-banner").hidden = !pageState.demo;
  element("print-session-link").href = ROUTES.coachesPrintSession + "?" + KEYS.sessionId + "=" + pageState.activeSessionId;
  element("print-meet-link").href = ROUTES.coachesPrintMeet;
  element("meet-zip-link").href = ROUTES.meetZip;
  element("home-link").href = ROUTES.home;
}

function badge(text, className) {
  const span = document.createElement("span");
  span.className = "badge " + className;
  span.textContent = text;
  return span;
}

function drawCoaches() {
  signinsList.replaceChildren();
  const coaches = pageState.coaches;
  const heads = coaches.filter(function (coach) { return coach[KEYS.headCoach]; }).length;
  const clubs = new Set(coaches.map(function (coach) { return coach[KEYS.club]; }).filter(Boolean)).size;
  element("coach-counts").textContent = coaches.length
    ? coaches.length + " coach" + (coaches.length === 1 ? "" : "es") + " · " + heads + " head coach" + (heads === 1 ? "" : "es")
      + " · " + clubs + " club" + (clubs === 1 ? "" : "s")
    : "";
  if (!coaches.length) {
    signinsList.textContent = "Nobody yet.";
    return;
  }
  // Anyone who needs the admin goes first; then newest first.
  const ordered = coaches.slice().sort(function (first, second) {
    return Number(first[KEYS.validated]) - Number(second[KEYS.validated]);
  });
  ordered.forEach(function (coach) {
    const row = document.createElement("div");
    row.className = "signin-row";
    const info = document.createElement("div");
    const name = document.createElement("div");
    name.className = "signin-name";
    name.textContent = coach[KEYS.name];
    if (coach[KEYS.validated]) {
      name.appendChild(badge(coach[KEYS.validationMethod] === CONFIG.validationMethods.visual ? "✓ admin" : "✓ card", "ok"));
    }
    if (coach[KEYS.headCoach]) { name.appendChild(badge("★ Head coach", "head")); }
    const detail = document.createElement("div");
    detail.className = "signin-detail";
    detail.textContent = describeCoach(coach) || "Club not known";
    info.append(name, detail);
    if (!coach[KEYS.validated]) {
      row.classList.add("needs-admin");
      const problem = document.createElement("div");
      problem.className = "problem";
      problem.textContent = "Needs admin: " + coach[KEYS.problems].join("; ");
      info.appendChild(problem);
    }
    const actions = document.createElement("div");
    actions.className = "row-actions";
    const head = makeButton(coach[KEYS.headCoach] ? HEAD_ON_LABEL : HEAD_OFF_LABEL, "head-toggle", function () {
      const body = {};
      body[KEYS.headCoach] = !coach[KEYS.headCoach];
      coachAction(coach, ROUTES.headSuffix, body);
    });
    head.classList.toggle("on", Boolean(coach[KEYS.headCoach]));
    head.setAttribute("aria-pressed", coach[KEYS.headCoach] ? "true" : "false");
    actions.appendChild(head);
    if (!coach[KEYS.validated]) {
      actions.appendChild(makeButton("Looks good", "go", function () { coachAction(coach, ROUTES.validateSuffix, {}); }));
    }
    actions.appendChild(makeButton("Edit", "", function () { openEditSheet(coach); }));
    const removeButton = makeButton("Remove", "", function () {
      if (removeButton.dataset.armed) { coachAction(coach, ROUTES.removeSuffix, {}); return; }
      removeButton.dataset.armed = "1";
      removeButton.textContent = "Tap to confirm";
      setTimeout(function () { delete removeButton.dataset.armed; removeButton.textContent = "Remove"; },
        REMOVE_CONFIRM_SECONDS * MILLISECONDS_PER_SECOND);
    });
    actions.appendChild(removeButton);
    row.append(info, actions);
    signinsList.appendChild(row);
  });
}

/** Head coach on/off, "Looks good" or Remove for one coach, then redraw. */
async function coachAction(coach, suffix, body) {
  try {
    await postJson(ROUTES.coachSigninPrefix + coach[KEYS.id] + suffix, body);
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
  if (!query) { return; }
  const queryKey = nameKey(query);
  const queryWords = query.toLowerCase().split(/\s+/).filter(Boolean);
  knownCoaches.filter(function (coach) {
    const words = coach[KEYS.name].toLowerCase().replace(/["']/g, "").split(/\s+/);
    const everyWordMatches = queryWords.every(function (queryWord) {
      return words.some(function (word) { return word.indexOf(queryWord) === 0; });
    });
    return everyWordMatches || nameKey(coach[KEYS.name]).indexOf(queryKey) >= 0;
  }).slice(0, MATCH_LIMIT).forEach(function (coach) {
    const item = document.createElement("li");
    const button = makeButton("", "", function () { openSheet(coach, null, null); });
    const label = document.createElement("span");
    label.textContent = coach[KEYS.name];
    const detail = document.createElement("span");
    detail.className = "match-detail";
    detail.textContent = describeCoach(coach);
    button.append(label, detail);
    item.appendChild(button);
    matchList.appendChild(item);
  });
}

// --- Camera --------------------------------------------------------------------------

/**
 * Open the shared camera window (card_camera.js, the same as the officials page) and
 * read a card with the coaches' card-reading route; then open the sign-in sheet.
 * @param {object|null} forCoach  The coach whose sheet asked for the scan, if any.
 */
function startCamera(forCoach) {
  window.CardCamera.read({ readingRoute: ROUTES.coachesCardReading, allowDiagnostics: false, onMessage: showToast })
    .then(function (result) {
      if (result.cancelled) { return; }
      if (result.reading === null) {
        showToast("Could not read the card. Sign in by name; the admin will check.", true);
        if (forCoach) { openSheet(forCoach, null, null); }
        return;
      }
      openSheet(result.reading[KEYS.match] || forCoach, result.reading[KEYS.card], result.reading);
    })
    .catch(function (error) { showToast("Camera problem: " + error.message, true); });
}

// --- Sign-in sheet -------------------------------------------------------------------

/**
 * Open the sign-in sheet.
 * @param {object|null} coach  A known coach (search or card match), or null for someone new.
 * @param {object|null} card  Card reading, if the card was scanned.
 * @param {object|null} cardResult  Server reply for the card (validated, problems).
 */
function openSheet(coach, card, cardResult) {
  sheet = { coachId: coach ? coach[KEYS.id] : null, coach: coach, card: card, cardResult: cardResult,
    headCoach: false, laterSessionIds: [], editSigninId: null };
  element("sheet-name").value = coach ? coach[KEYS.name] : ((card && card[KEYS.cardName]) || searchInput.value.trim());
  const needsCheck = !coach && Boolean(card && card[KEYS.cardName]);
  element("sheet-name").classList.toggle("check", needsCheck);
  element("sheet-name-hint").hidden = !needsCheck;
  element("sheet-club").value = (card && card[KEYS.club]) || (coach && coach[KEYS.club]) || "";
  window.Desk.fillLscSelect(element("sheet-lsc"), (card && card[KEYS.lsc]) || (coach && coach[KEYS.lsc]));
  drawHeadToggle();
  drawSheetCheck();
  element("sheet-submit").textContent = "Sign in";
  element("sheet-scan").hidden = false;
  const later = laterSessionsToday();
  element("sheet-later-block").hidden = later.length === 0;
  const chips = element("sheet-later");
  chips.replaceChildren();
  later.forEach(function (session) {
    const chip = makeButton(session[KEYS.name], "chip", function () {
      const index = sheet.laterSessionIds.indexOf(session[KEYS.id]);
      if (index >= 0) { sheet.laterSessionIds.splice(index, 1); } else { sheet.laterSessionIds.push(session[KEYS.id]); }
      chip.classList.toggle("on", index < 0);
    });
    chips.appendChild(chip);
  });
  sheetOverlay.hidden = false;
}

/** Edit a coach already in the list: name, club (everywhere) and head coach. */
function openEditSheet(coach) {
  sheet = { coachId: coach[KEYS.coachId], coach: coach, card: null, cardResult: null,
    headCoach: Boolean(coach[KEYS.headCoach]), laterSessionIds: [], editSigninId: coach[KEYS.id] };
  element("sheet-name").value = coach[KEYS.name];
  element("sheet-name").classList.remove("check");
  element("sheet-name-hint").hidden = true;
  element("sheet-club").value = coach[KEYS.club] || "";
  window.Desk.fillLscSelect(element("sheet-lsc"), coach[KEYS.lsc]);
  drawHeadToggle();
  element("sheet-check").textContent = "";
  element("sheet-submit").textContent = "Save changes";
  element("sheet-scan").hidden = true;
  element("sheet-later-block").hidden = true;
  sheetOverlay.hidden = false;
}

function drawHeadToggle() {
  const button = element("sheet-head");
  button.textContent = sheet.headCoach ? HEAD_ON_LABEL : HEAD_OFF_LABEL;
  button.classList.toggle("on", sheet.headCoach);
  button.setAttribute("aria-pressed", sheet.headCoach ? "true" : "false");
}

function drawSheetCheck() {
  const line = element("sheet-check");
  line.className = "check-line";
  if (sheet.cardResult) {
    const ok = sheet.cardResult[KEYS.validated];
    line.classList.add(ok ? "ok" : "warn");
    line.textContent = ok ? "✓ Card checked: registration current"
      : "Needs admin: " + sheet.cardResult[KEYS.problems].join("; ");
  } else if (sheet.coach && sheet.coach[KEYS.cardMeetId] === (pageState.meet && pageState.meet[KEYS.id])) {
    line.classList.add("ok");
    line.textContent = "✓ Card already checked at this meet";
  } else {
    line.classList.add("warn");
    line.textContent = "Card not checked: scan it, or the admin checks it by eye";
  }
}

async function submitSheet() {
  const body = {};
  body[KEYS.name] = element("sheet-name").value.trim();
  body[KEYS.club] = element("sheet-club").value.trim();
  body[KEYS.lsc] = element("sheet-lsc").value;
  body[KEYS.headCoach] = sheet.headCoach;
  if (!body[KEYS.name]) { showToast("Enter the coach's name", true); return; }
  try {
    if (sheet.editSigninId !== null) {
      await postJson(ROUTES.coachSigninPrefix + sheet.editSigninId + ROUTES.editSuffix, body);
      sheetOverlay.hidden = true;
      showToast("✓ " + body[KEYS.name] + " saved");
    } else {
      body[KEYS.coachId] = sheet.coachId;
      body[KEYS.card] = sheet.card;
      body[KEYS.sessionIds] = [pageState.activeSessionId].concat(sheet.laterSessionIds);
      const reply = await postJson(ROUTES.coachesSignins, body);
      sheetOverlay.hidden = true;
      showToast(reply[KEYS.validated] ? "✓ " + body[KEYS.name] + " signed in" : body[KEYS.name] + " signed in: needs the admin",
        !reply[KEYS.validated]);
    }
    searchInput.value = "";
    await refresh();
  } catch (error) {
    showToast(error.message, true);
  }
}

// --- Wiring --------------------------------------------------------------------------

element("capture-button").addEventListener("click", function () { startCamera(null); });
searchInput.addEventListener("input", drawMatches);
newPersonButton.addEventListener("click", function () { openSheet(null, null, null); });
element("sheet-head").addEventListener("click", function () { sheet.headCoach = !sheet.headCoach; drawHeadToggle(); });
element("sheet-scan").addEventListener("click", function () {
  sheetOverlay.hidden = true;
  startCamera(sheet ? sheet.coach : null);
});
element("sheet-cancel").addEventListener("click", function () { sheetOverlay.hidden = true; });
element("sheet-submit").addEventListener("click", submitSheet);
element("demo-exit").addEventListener("click", async function () {
  await postJson(ROUTES.demoExit, {});
  window.Desk.announceChange();
  window.location.reload();
});
// The standard top bar (☰ menu, session drop-down); names this tab. Stay on the same
// meet and session as the other apps (see desk_shared.js).
window.Desk.initTopBar({ app: CONFIG.coachesAppKey, refresh: refresh });
window.Desk.followChanges(refresh);

refresh().then(function () {
  if (window.CardScanner) {
    window.CardScanner.warmUp().catch(function () { showToast("The card reader could not load", true); });
  }
});
