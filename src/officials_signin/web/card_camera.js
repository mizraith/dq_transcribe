/**
 * Card camera window: the pop-up shared by the officials and coaches pages.
 *
 * One copy of everything around the card reader (card_scanner.js): the camera
 * window itself (built here, so the pages carry no copy of its markup), the live
 * guide line and coloured frame, the "fields read" chips, Switch camera, Capture now,
 * Use what was read, Cancel and (on the officials page) "Save frames for
 * troubleshooting". Styles live in desk.css.
 *
 * Usage:
 *     CardCamera.read({ readingRoute: "/api/...", allowDiagnostics: true, onMessage: showToast })
 *       .then(function (result) { ... });
 * ``result`` is ``{ cancelled: true }`` when the admin cancelled, otherwise
 * ``{ cancelled: false, reading: <server reply or null> }`` (null: nothing was read).
 * A camera failure rejects the promise.
 *
 * This file is a string.Template: the config placeholder below is replaced by
 * officials_signin.server.render_script, so never use a literal dollar sign here.
 */
"use strict";

window.CardCamera = (function () {
  const CONFIG = ${config};
  const KEYS = CONFIG.keys;
  const OVERLAY_ID = "camera-overlay";
  const MARKUP = [
    '<div class="sheet">',
    '  <button class="sheet-close" type="button" id="camera-close" aria-label="Close">✕</button>',
    '  <h2>Show your Membership card</h2>',
    '  <div class="camera-bar">',
    '    <span id="camera-name">Camera</span>',
    '    <button id="camera-switch" type="button">⟲ Switch camera</button>',
    '  </div>',
    '  <div class="camera-holder">',
    '    <div id="camera-stage">',
    '      <video id="camera-video" playsinline muted></video>',
    '      <canvas id="camera-overlay-canvas"></canvas>',
    '    </div>',
    '  </div>',
    '  <div id="camera-guide">Starting camera…</div>',
    '  <div id="camera-status"></div>',
    '  <div id="camera-fields"></div>',
    '  <label class="check-option diagnostics-option" id="camera-diagnostics-option">',
    '    <input id="camera-diagnostics" type="checkbox"> Save frames for troubleshooting (your own card only)</label>',
    '  <div class="sheet-actions">',
    '    <button id="camera-cancel" class="grow" type="button">Cancel</button>',
    '    <button id="camera-capture" type="button">Capture now</button>',
    '    <button id="camera-done" type="button">Use what was read</button>',
    '  </div>',
    '</div>',
  ].join("\n");

  const element = function (id) { return document.getElementById(id); };
  let overlay = null;
  let activeScan = null;
  let lastReading = null;
  let finish = null; // resolves the promise of the read in progress
  let showMessage = function () {};

  /** Build the camera window once and wire its buttons. */
  function ensureOverlay() {
    if (overlay) { return; }
    overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.id = OVERLAY_ID;
    overlay.hidden = true;
    overlay.innerHTML = MARKUP;
    document.body.appendChild(overlay);
    element("camera-cancel").addEventListener("click", function () { stop({ cancelled: true }); });
    element("camera-close").addEventListener("click", function () { stop({ cancelled: true }); });
    element("camera-done").addEventListener("click", function () { stop({ cancelled: false, reading: lastReading }); });
    element("camera-capture").addEventListener("click", function () { if (activeScan) { activeScan.captureNow(); } });
    element("camera-switch").addEventListener("click", function () { if (activeScan) { activeScan.switchCamera(); } });
    element("camera-diagnostics").addEventListener("change", function () {
      const on = element("camera-diagnostics").checked;
      window.CardScanner.setDiagnosticsEnabled(on);
      showMessage(on ? "Saving frames for troubleshooting" : "Not saving frames", false);
    });
  }

  /** "✓ Name", "✓ Member ID"... for what has been read so far. */
  function drawFields(card) {
    const fields = element("camera-fields");
    fields.replaceChildren();
    CONFIG.cardFields.forEach(function (pair) {
      const chip = document.createElement("span");
      const read = card && card[pair[0]] !== null && card[pair[0]] !== undefined;
      chip.className = "field-chip" + (read ? " read" : "");
      chip.textContent = (read ? "✓ " : "") + pair[1];
      fields.appendChild(chip);
    });
  }

  /** Close the window and settle the read in progress (once). */
  function stop(result) {
    const scan = activeScan;
    activeScan = null;
    if (scan) { scan.cancel(); } // stopped by the admin while still reading
    overlay.hidden = true;
    if (finish) {
      const done = finish;
      finish = null;
      done(result);
    }
  }

  /**
   * Open the camera and read a card.
   * @param {object} options
   * @param {string} [options.readingRoute]  Where to post the OCR text (default: the officials route).
   * @param {boolean} [options.allowDiagnostics]  Offer "Save frames for troubleshooting".
   * @param {function(string, boolean):void} [options.onMessage]  Short messages for the admin.
   * @returns {Promise<{cancelled: boolean, reading: (object|null|undefined)}>}
   */
  function read(options) {
    if (!window.CardScanner) { return Promise.reject(new Error("The card reader did not load")); }
    ensureOverlay();
    if (finish) { stop({ cancelled: true }); }
    showMessage = options.onMessage || function () {};
    lastReading = null;
    element("camera-guide").textContent = "Starting camera…";
    element("camera-guide").style.background = "";
    element("camera-status").textContent = "";
    element("camera-diagnostics-option").hidden = !options.allowDiagnostics;
    element("camera-diagnostics").checked = Boolean(options.allowDiagnostics) && window.CardScanner.diagnosticsEnabled();
    drawFields(null);
    overlay.hidden = false;
    return new Promise(function (resolve, reject) {
      finish = resolve;
      activeScan = window.CardScanner.scan({
        video: element("camera-video"),
        readingRoute: options.readingRoute,
        diagnostics: options.allowDiagnostics ? window.CardScanner.diagnosticsEnabled : false,
        stage: element("camera-stage"),
        overlay: element("camera-overlay-canvas"),
        onGuide: function (state, message, colour) {
          const guide = element("camera-guide");
          guide.textContent = message;
          guide.style.background = colour;
        },
        onStatus: function (text) { element("camera-status").textContent = text; },
        onCamera: function (name, count) {
          element("camera-name").textContent = name;
          element("camera-switch").hidden = count < 2;
        },
        onProgress: function (reading) {
          lastReading = reading;
          drawFields(reading[KEYS.card]);
          element("camera-status").textContent = "";
        },
      });
      activeScan.result.then(function (reading) {
        if (activeScan) { activeScan = null; stop({ cancelled: false, reading: reading }); }
      }).catch(function (error) {
        activeScan = null;
        overlay.hidden = true;
        finish = null;
        reject(error);
      });
    });
  }

  return { read: read };
})();
