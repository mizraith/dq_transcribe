/**
 * Small pieces shared by the officials and coaches sign-in pages.
 *
 * - ``Desk.fillLscSelect(select, code)``: the LSC drop-down (USA Swimming's 59 Local
 *   Swimming Committees, by name), for when the camera did not read the LSC.
 * - ``Desk.describeClub(record)``: "PASA · Pacific Swimming" for a list row or search match.
 * - ``Desk.announceChange()`` / ``Desk.followChanges(refresh)``: keep the officials and
 *   coaches tabs on the same meet and session.
 *
 * This file is a string.Template: the config placeholder below is replaced by
 * officials_signin.server.render_script, so never use a literal dollar sign here.
 */
"use strict";

window.Desk = (function () {
  const CONFIG = ${config};
  const KEYS = CONFIG.keys;

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

  // --- Keeping the officials and coaches tabs in step ----------------------------
  // Both tabs show the same server's open meet and session. When one tab changes them
  // (session drop-down, Meets, Meet setup, demo), it tells the other through a
  // BroadcastChannel (same browser, same address), which then reloads its data. A
  // slow background refresh catches anything missed (another device, an old browser).
  let channel = null;
  try { channel = new BroadcastChannel(CONFIG.deskChannelName); } catch (error) { channel = null; }

  /** Tell the other desk tab that the meet, session or demo changed. */
  function announceChange() {
    if (channel) { try { channel.postMessage(CONFIG.deskChangedMessage); } catch (error) { /* tab closing */ } }
  }

  /**
   * Reload this tab's data when the other tab changed something, when this tab comes
   * back into view, and every so often while it is in view.
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
    setInterval(function () { if (!document.hidden) { quietly(); } }, CONFIG.deskRefreshSeconds * 1000);
  }

  return {
    fillLscSelect: fillLscSelect, describeClub: describeClub,
    announceChange: announceChange, followChanges: followChanges,
  };
})();
