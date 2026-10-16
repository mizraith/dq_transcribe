/**
 * Shared by every page of the Admin Assistant suite served here (the main page,
 * Officials Sign-In and Coaches Sign-In), so each piece exists once:
 *
 * - Small helpers: ``Desk.element``, ``Desk.getJson``, ``Desk.postJson``,
 *   ``Desk.makeButton``, ``Desk.showToast`` and the time helpers (``Desk.isoToday``,
 *   ``Desk.minutesOfDay``, ``Desk.hoursMinutesOf``, ``Desk.formatTime12``, ``Desk.addDays``).
 * - The standard top bar: ``Desk.initTopBar({...})`` wires the ☰ menu (adds "Meets & Main
 *   Page" and the "Admin Assistant ›" sub-menu of apps) and the session drop-down;
 *   ``Desk.drawSessionPicker(state, countKey)`` fills the drop-down.
 * - ``Desk.openApp(key)``: open (or switch to) another app in its own named tab, never
 *   reloading a tab that is already open (DQ Transcribe may be recording).
 * - ``Desk.fillLscSelect(select, code)`` and ``Desk.describeClub(record)``: the LSC
 *   drop-down (59 LSCs) and "PASA · Pacific Swimming" labels.
 * - ``Desk.announceChange()`` / ``Desk.followChanges(refresh)``: every open tab shows the
 *   same meet and session; a change in one tab reloads the others.
 *
 * This file is a string.Template: the config placeholder below is replaced by
 * officials_signin.server.render_script, so never use a literal dollar sign here.
 */
"use strict";

window.Desk = (function () {
  const CONFIG = ${config};
  const KEYS = CONFIG.keys;
  const ROUTES = CONFIG.routes;
  const TOAST_SECONDS = 2.5;
  const MILLISECONDS_PER_SECOND = 1000;
  const MILLISECONDS_PER_MINUTE = 60000;
  const MINUTES_PER_HOUR = 60;
  const MINUTES_PER_DAY = 24 * MINUTES_PER_HOUR;
  const NOON_HOUR = 12;
  const ISO_DATE_LENGTH = 10;
  const MENU_GAP_PX = 4;
  const BLANK_PAGE = "about:blank";
  let toastTimer = null;

  // --- Small helpers ---------------------------------------------------------------

  function element(id) { return document.getElementById(id); }

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
    if (!response.ok) { throw new Error(payload[KEYS.error] || "Something went wrong"); }
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

  /** A short message at the bottom of the page (red when ``isError``). Needs a ``#toast`` element. */
  function showToast(message, isError) {
    const toast = element("toast");
    if (!toast) { return; }
    toast.textContent = message;
    toast.classList.toggle("error", Boolean(isError));
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.classList.remove("show"); }, TOAST_SECONDS * MILLISECONDS_PER_SECOND);
  }

  // --- Time helpers ------------------------------------------------------------------

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
    return new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + days)).toISOString().slice(0, ISO_DATE_LENGTH);
  }

  // --- Apps of the suite ---------------------------------------------------------------

  /** The address of one app (the main page, a sign-in page, or DQ Transcribe on its own port). */
  function appUrl(app) {
    if (!app.port) { return app.path; }
    return window.location.protocol + "//" + window.location.hostname + ":" + app.port + app.path;
  }

  function findApp(key) {
    return CONFIG.suiteApps.find(function (app) { return app.key === key; });
  }

  /**
   * Open an app in its own named tab, or switch to that tab when it is already open.
   * An open tab is never reloaded (DQ Transcribe may be recording).
   * @param {string} key  An app key from the suite config (home, officials, coaches, dq).
   */
  function openApp(key) {
    const app = findApp(key);
    if (!app) { return; }
    if (app.tab === window.name) {
      window.location.href = appUrl(app);
      return;
    }
    const tab = window.open("", app.tab);
    if (!tab) {
      window.location.href = appUrl(app);  // pop-ups blocked: go there in this tab
      return;
    }
    let isNew = false;
    try { isNew = tab.location.href === BLANK_PAGE; } catch (error) { isNew = false; }  // another app's page: leave it
    if (isNew) { tab.location.href = appUrl(app); }
    tab.focus();
  }

  // --- The standard top bar ------------------------------------------------------------

  function setMenuOpen(menu, button, open) {
    if (open) { menu.style.top = (document.querySelector("header").getBoundingClientRect().bottom + MENU_GAP_PX) + "px"; }
    menu.hidden = !open;
    button.setAttribute("aria-expanded", open ? "true" : "false");
  }

  /** A menu entry that opens an app (in its own tab). */
  function appMenuButton(app, label) {
    const button = makeButton(label || app.title, "menu-item", function () { openApp(app.key); });
    button.dataset.app = app.key;
    return button;
  }

  /**
   * Wire the standard top bar: the ☰ menu (gets "Meets & Main Page" first and the
   * "Admin Assistant ›" sub-menu last, around the page's own items) and the session
   * drop-down (picking a session makes it current for every app).
   * @param {object} options
   * @param {string} options.app  This page's app key (its own entry is marked).
   * @param {function(): Promise} options.refresh  Reloads this page's data.
   */
  function initTopBar(options) {
    const menu = element("main-menu");
    const button = element("menu-button");
    if (menu && button) {
      const home = findApp(CONFIG.homeAppKey);
      if (options.app !== CONFIG.homeAppKey) {
        menu.insertBefore(appMenuButton(home, CONFIG.meetsMenuLabel), menu.firstChild);
      }
      const toggle = makeButton(CONFIG.suiteTitle + " ›", "menu-item submenu-toggle", function (event) {
        event.stopPropagation();
        submenu.hidden = !submenu.hidden;
        toggle.setAttribute("aria-expanded", submenu.hidden ? "false" : "true");
      });
      toggle.setAttribute("aria-expanded", "false");
      const submenu = document.createElement("div");
      submenu.className = "submenu";
      submenu.hidden = true;
      CONFIG.suiteApps.forEach(function (app) {
        const entry = appMenuButton(app, app.key === CONFIG.homeAppKey ? CONFIG.meetsMenuLabel : app.title);
        if (app.key === options.app) { entry.classList.add("current"); }
        submenu.appendChild(entry);
      });
      menu.append(toggle, submenu);
      button.addEventListener("click", function (event) {
        event.stopPropagation();
        setMenuOpen(menu, button, menu.hidden);
      });
      // A choice in the menu, a tap elsewhere or Escape closes it (the sub-menu toggle does not).
      menu.addEventListener("click", function () { setMenuOpen(menu, button, false); });
      document.addEventListener("click", function (event) {
        if (!menu.hidden && !menu.contains(event.target)) { setMenuOpen(menu, button, false); }
      });
      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") { setMenuOpen(menu, button, false); }
      });
    }
    const select = element("session-select");
    if (select) {
      select.addEventListener("change", async function () {
        const body = {};
        body[KEYS.sessionId] = Number(select.value);
        try {
          await postJson(ROUTES.activeSession, body);
          await options.refresh();
          announceChange();
        } catch (error) {
          showToast(error.message, true);
        }
      });
    }
    // The ✕ in a sheet's corner does what that sheet's own close button does.
    document.querySelectorAll(".sheet-close[data-closes]").forEach(function (closeButton) {
      closeButton.addEventListener("click", function () { element(closeButton.dataset.closes).click(); });
    });
    window.name = findApp(options.app).tab;
  }

  /**
   * Fill the top bar's meet name and session drop-down.
   * @param {object|null} meet  The current meet.
   * @param {object[]} sessions  Its sessions.
   * @param {number|null} activeSessionId  The current session.
   * @param {string|null} countKey  Key of a per-session count to show ("Friday PM · 18"), or null.
   */
  function drawSessionPicker(meet, sessions, activeSessionId, countKey) {
    const name = element("meet-name");
    if (name) { name.textContent = meet ? meet[KEYS.name] : "No meet yet"; }
    const select = element("session-select");
    if (!select) { return; }
    select.replaceChildren();
    sessions.forEach(function (session) {
      const option = document.createElement("option");
      option.value = String(session[KEYS.id]);
      option.textContent = session[KEYS.name] + (countKey ? "  ·  " + session[countKey] : "");
      option.selected = session[KEYS.id] === activeSessionId;
      select.appendChild(option);
    });
    element("session-picker").hidden = sessions.length === 0;
  }

  // --- LSC and club --------------------------------------------------------------------

  /**
   * Fill an LSC drop-down and select a code.
   * @param {HTMLSelectElement} select  The drop-down.
   * @param {string|null} code  LSC code to select; empty or unknown selects the desk's own LSC.
   */
  function fillLscSelect(select, code) {
    if (!select.options.length) {
      const none = document.createElement("option");
      none.value = "";
      none.textContent = "—";
      select.appendChild(none);
      CONFIG.lscChoices.forEach(function (pair) {
        const option = document.createElement("option");
        option.value = pair[0];
        option.textContent = pair[1] + " (" + pair[0] + ")";
        select.appendChild(option);
      });
    }
    select.value = code && CONFIG.lscNames[code] ? code : CONFIG.defaultLsc;
  }

  /** "PASA · Pacific Swimming" (club, then the LSC's name); "" when neither is known. */
  function describeClub(record) {
    const parts = [];
    if (record[KEYS.club]) { parts.push(record[KEYS.club]); }
    const lsc = record[KEYS.lsc];
    if (lsc) { parts.push(CONFIG.lscNames[lsc] || lsc); }
    return parts.join(" · ");
  }

  // --- Keeping every tab on the same meet and session ------------------------------------
  // All pages here show the server's current meet and session. When one tab changes them
  // (session drop-down, Meets, Meet setup, demo), it tells the others through a
  // BroadcastChannel (same browser, same address), which then reload their data. A slow
  // background refresh catches anything missed (another device, an old browser).
  let channel = null;
  try { channel = new BroadcastChannel(CONFIG.deskChannelName); } catch (error) { channel = null; }

  /** Tell the other tabs that the meet, session or demo changed. */
  function announceChange() {
    if (channel) { try { channel.postMessage(CONFIG.deskChangedMessage); } catch (error) { /* tab closing */ } }
  }

  /**
   * Reload this tab's data when another tab changed something, when this tab comes back
   * into view, and every so often while it is in view.
   * @param {function(): Promise} reload  The page's own refresh.
   */
  function followChanges(reload) {
    const quietly = function () { reload().catch(function () { /* next time */ }); };
    if (channel) {
      channel.addEventListener("message", function (event) {
        if (event.data === CONFIG.deskChangedMessage) { quietly(); }
      });
    }
    document.addEventListener("visibilitychange", function () { if (!document.hidden) { quietly(); } });
    setInterval(function () { if (!document.hidden) { quietly(); } }, CONFIG.deskRefreshSeconds * MILLISECONDS_PER_SECOND);
  }

  return {
    element: element, getJson: getJson, postJson: postJson, makeButton: makeButton, showToast: showToast,
    isoToday: isoToday, minutesOfDay: minutesOfDay, hoursMinutesOf: hoursMinutesOf, formatTime12: formatTime12,
    addDays: addDays, appUrl: appUrl, openApp: openApp, initTopBar: initTopBar, drawSessionPicker: drawSessionPicker,
    fillLscSelect: fillLscSelect, describeClub: describeClub,
    announceChange: announceChange, followChanges: followChanges,
  };
})();
