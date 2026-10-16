/**
 * Admin Assistant main page: the app launcher, the current meet and the meets list.
 *
 * Loaded after desk_shared.js and meets.js, whose shared names (CONFIG, KEYS, ROUTES,
 * element, getJson, postJson, makeButton, showToast, drawMeets, openSetup...) it uses
 * as they are (classic scripts share one global scope, so they are not declared again).
 *
 * Defines ``pageState`` and ``refresh``, which meets.js calls after every change. The
 * current meet and session are the server's, shared by every app; changes made here are
 * announced to the other tabs (desk_shared.js).
 *
 * This file is a string.Template (rendered by officials_signin.server.render_script),
 * so never use a literal dollar sign here.
 */
"use strict";

let pageState = { demo: false, meet: null, sessions: [], activeSessionId: null };

// --- Loading and drawing ---------------------------------------------------------------

async function refresh() {
  const state = await getJson(ROUTES.state);
  pageState = {
    demo: Boolean(state[KEYS.demo]),
    meet: state[KEYS.meet],
    sessions: state[KEYS.sessions],
    activeSessionId: state[KEYS.activeSessionId],
  };
  drawHeader();
  drawCurrentMeet();
  await drawMeets(false);
}

function drawHeader() {
  window.Desk.drawSessionPicker(pageState.meet, pageState.sessions, pageState.activeSessionId, null);
  const session = pageState.sessions.find(function (item) { return item[KEYS.id] === pageState.activeSessionId; });
  const meetingTime = element("meeting-time");
  meetingTime.hidden = !(session && session[KEYS.meetingTime]);
  meetingTime.textContent = meetingTime.hidden ? "" : "Officials Meeting: " + window.Desk.formatTime12(session[KEYS.meetingTime]);
  element("demo-banner").hidden = !pageState.demo;
  element("meet-zip-link").href = ROUTES.meetZip;
}

/** One button per app (not the main page itself), with its one-line description. */
function drawLauncher() {
  const launcher = element("app-launcher");
  launcher.replaceChildren();
  CONFIG.suiteApps.forEach(function (app) {
    if (app.key === CONFIG.homeAppKey) { return; }
    const card = makeButton("", "app-card", function () { window.Desk.openApp(app.key); });
    card.dataset.app = app.key;
    const title = document.createElement("span");
    title.className = "app-title";
    title.textContent = app.title;
    const description = document.createElement("span");
    description.className = "app-description";
    description.textContent = app.description;
    card.append(title, description);
    launcher.appendChild(card);
  });
  const more = document.createElement("div");
  more.className = "app-card placeholder";
  more.textContent = "More apps can go here.";
  launcher.appendChild(more);
}

/** The current meet: name, start date and its sessions (times, officials meeting, length). */
function drawCurrentMeet() {
  const box = element("current-meet");
  box.replaceChildren();
  if (!pageState.meet) {
    box.textContent = "No meet yet. Start one with + New meet (or try the demo meet).";
    element("current-setup").textContent = "New meet";
    element("current-reports").hidden = true;
    return;
  }
  element("current-setup").textContent = "Meet setup";
  element("current-reports").hidden = false;
  const title = document.createElement("div");
  title.className = "current-meet-title";
  title.textContent = pageState.meet[KEYS.name] + (pageState.demo ? " (demo)" : "");
  const detail = document.createElement("div");
  detail.className = "signin-detail";
  detail.textContent = "starts " + pageState.meet[KEYS.startDate] + " · " + pageState.sessions.length + " session"
    + (pageState.sessions.length === 1 ? "" : "s");
  box.append(title, detail);
  if (!pageState.sessions.length) { return; }
  const table = document.createElement("table");
  table.className = "current-sessions";
  const head = document.createElement("tr");
  ["Session", "Date", "Start", "Officials meeting", "Length"].forEach(function (label) {
    const cell = document.createElement("th");
    cell.textContent = label;
    head.appendChild(cell);
  });
  table.appendChild(head);
  pageState.sessions.forEach(function (session) {
    const row = document.createElement("tr");
    row.classList.toggle("current", session[KEYS.id] === pageState.activeSessionId);
    const minutes = session[KEYS.estimatedMinutes] || CONFIG.defaultSessionMinutes;
    [
      session[KEYS.name],
      session[KEYS.date],
      session[KEYS.startTime] ? window.Desk.formatTime12(session[KEYS.startTime]) : "—",
      session[KEYS.meetingTime] ? window.Desk.formatTime12(session[KEYS.meetingTime]) : "—",
      (minutes / MINUTES_PER_HOUR) + " h",
    ].forEach(function (text) {
      const cell = document.createElement("td");
      cell.textContent = text;
      row.appendChild(cell);
    });
    table.appendChild(row);
  });
  box.appendChild(table);
}

/** The Reports pop-up: one link per whole-meet report (CONFIG.suiteReports), each in a new tab. */
function openReports() {
  element("reports-meet").textContent = pageState.meet ? pageState.meet[KEYS.name] + " · all sessions" : "";
  const list = element("reports-list");
  list.replaceChildren();
  CONFIG.suiteReports.forEach(function (report) {
    const link = document.createElement("a");
    link.className = "report-card";
    link.href = report.route;
    link.target = "_blank";
    link.dataset.report = report.key;
    const title = document.createElement("span");
    title.className = "app-title";
    title.textContent = report.title;
    const description = document.createElement("span");
    description.className = "app-description";
    description.textContent = report.description;
    link.append(title, description);
    link.addEventListener("click", function () { element("reports-overlay").hidden = true; });
    list.appendChild(link);
  });
  element("reports-overlay").hidden = false;
}

// --- Wiring --------------------------------------------------------------------------

element("current-reports").addEventListener("click", openReports);
element("reports-close").addEventListener("click", function () { element("reports-overlay").hidden = true; });
element("current-setup").addEventListener("click", function () { openSetup(pageState.meet === null); });
element("menu-setup").addEventListener("click", function () { openSetup(pageState.meet === null); });
element("menu-new-meet").addEventListener("click", newMeetFromOverview);
element("meet-zip-link").addEventListener("click", function () { showToast("Saving the meet as a zip file…"); });
element("demo-reset").addEventListener("click", function () {
  showDemoResetWarning(true);
  element("demo-reset-warning").scrollIntoView({ block: "nearest" });
});
element("demo-exit").addEventListener("click", async function () {
  await postJson(ROUTES.demoExit, {});
  await refresh();
  window.Desk.announceChange();
});

window.Desk.initTopBar({ app: CONFIG.homeAppKey, refresh: refresh });
window.Desk.followChanges(refresh);
drawLauncher();
// Tell the other tabs too: arriving here may follow a change made on a page that does not
// announce (the demo meet's start page).
refresh().then(window.Desk.announceChange);
