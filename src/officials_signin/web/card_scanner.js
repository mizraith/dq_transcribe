/**
 * Card scanner: reads a USA Swimming membership card from the tablet camera.
 *
 * The official holds up their phone (USA Swimming app, "Membership card" tab).
 * Several Tesseract.js workers run in parallel; each one takes the newest camera
 * frame as soon as it is free, cleans it up (grayscale + auto-contrast + light
 * sharpening), reads it, and posts the text to the server, which parses and
 * merges every pass so far. Scanning stops by itself as soon as every required
 * field has been read, so the common case needs no shutter tap.
 *
 * Passes alternate between Tesseract page layouts (each tends to read different
 * rows). Until a frame shows card words, each pass tries the next orientation:
 * upright, phone turned left or right (sideways fits the wide camera frame
 * better), mirrored. The orientation that works is kept, and the search starts
 * again if the phone is turned later.
 *
 * Everything runs on this device: the OCR engine is served from localhost
 * (web/vendor/tesseract) and frames are never uploaded or stored.
 *
 * This file is a string.Template: the config placeholder below is replaced by
 * officials_signin.server.render_script, so never use a literal dollar sign here.
 */
"use strict";

window.CardScanner = (function () {
  const CONFIG = ${config};
  const OCR = CONFIG.ocr;
  const KEYS = CONFIG.keys;
  const CAMERA_STORAGE_KEY = "officials_signin.camera_device";
  const FACING_FRONT = "user";
  const FACING_BACK = "environment";
  const SHARPEN_AMOUNT = 0.6; // 0 = off; weight of the 3x3 sharpening step
  const MAX_CHANNEL_VALUE = 255;
  const HISTOGRAM_SIZE = 256;
  // ITU-R BT.601 luma weights for grayscale.
  const LUMA_RED = 0.299;
  const LUMA_GREEN = 0.587;
  const LUMA_BLUE = 0.114;
  const BYTES_PER_PIXEL = 4;

  const CARD_HINT = new RegExp(OCR.cardHintPattern, "i");
  const QUARTER_TURN = 90;
  const HALF_TURN = 180;
  const THREE_QUARTER_TURN = 270;
  const FRAME_WAIT_MILLISECONDS = 200;

  let poolPromise = null;

  /** Start loading the OCR workers (engine and language data come from localhost) so the first scan is quick. */
  function warmUp() {
    if (poolPromise === null) {
      const workers = [];
      for (let index = 0; index < OCR.workerCount; index += 1) {
        workers.push(window.Tesseract.createWorker(OCR.language, 1, {
          workerPath: OCR.enginePath + OCR.workerScript,
          corePath: OCR.enginePath + OCR.coreScript,
          langPath: OCR.languageDataPath,
          workerBlobURL: false,
          gzip: true,
        }));
      }
      poolPromise = Promise.all(workers);
      poolPromise.catch(function () { poolPromise = null; });
    }
    return poolPromise;
  }

  function sleep(milliseconds) {
    return new Promise(function (resolve) { setTimeout(resolve, milliseconds); });
  }

  /** The camera the admin last picked (a device ID), or null for "front camera, please". */
  function rememberedCameraId() {
    try { return localStorage.getItem(CAMERA_STORAGE_KEY); } catch (error) { return null; }
  }

  function rememberCameraId(deviceId) {
    try { localStorage.setItem(CAMERA_STORAGE_KEY, deviceId); } catch (error) { /* private mode: fine */ }
  }

  /** Every camera on this device (labels are known once camera permission is granted). */
  async function listCameras() {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter(function (device) { return device.kind === "videoinput"; });
  }

  /** "Front camera", "Back camera" or the device's own label, for the camera window. */
  function describeCamera(track, cameras) {
    const settings = track.getSettings ? track.getSettings() : {};
    const index = cameras.findIndex(function (camera) { return camera.deviceId === settings.deviceId; });
    const position = index >= 0 ? " (" + (index + 1) + " of " + cameras.length + ")" : "";
    if (settings.facingMode === FACING_FRONT) { return "Front camera" + position; }
    if (settings.facingMode === FACING_BACK) { return "Back camera" + position; }
    return (track.label || "Camera") + position;
  }

  /**
   * Draw a video frame (or image), scaled down and turned upright, crop it to the
   * phone screen, and clean it up for OCR.
   * @param {CanvasImageSource} source  Video element or image.
   * @param {number} width  Source width in pixels.
   * @param {number} height  Source height in pixels.
   * @param {number} rotation  Clockwise turn to apply: 0, 90, 180 or 270 degrees.
   * @param {boolean} mirror  Flip left-right (after turning).
   * @returns {HTMLCanvasElement}
   */
  function prepareFrame(source, width, height, rotation, mirror) {
    const scale = Math.min(1, OCR.maxFrameWidth / Math.max(width, height));
    const scaledWidth = Math.round(width * scale);
    const scaledHeight = Math.round(height * scale);
    const sideways = rotation === QUARTER_TURN || rotation === THREE_QUARTER_TURN;
    const turned = document.createElement("canvas");
    turned.width = sideways ? scaledHeight : scaledWidth;
    turned.height = sideways ? scaledWidth : scaledHeight;
    const turnedContext = turned.getContext("2d", { willReadFrequently: true });
    turnedContext.translate(turned.width / 2, turned.height / 2);
    if (mirror) { turnedContext.scale(-1, 1); }
    turnedContext.rotate(rotation * Math.PI / HALF_TURN);
    turnedContext.drawImage(source, -scaledWidth / 2, -scaledHeight / 2, scaledWidth, scaledHeight);
    const box = findScreenBox(turnedContext.getImageData(0, 0, turned.width, turned.height));
    const canvas = document.createElement("canvas");
    canvas.width = box.width;
    canvas.height = box.height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(turned, box.left, box.top, box.width, box.height, 0, 0, box.width, box.height);
    const image = context.getImageData(0, 0, canvas.width, canvas.height);
    cleanUp(image);
    context.putImageData(image, 0, 0);
    return canvas;
  }

  /** Brightness of one pixel (ITU-R BT.601 luma). */
  function luma(pixels, offset) {
    return LUMA_RED * pixels[offset] + LUMA_GREEN * pixels[offset + 1] + LUMA_BLUE * pixels[offset + 2];
  }

  /**
   * The longest run of indexes whose share is at least ``minimum``, allowing short gaps.
   * @param {Float32Array} shares  Bright share per row (or column).
   * @param {number} minimum  Share needed to count as screen.
   * @returns {{start: number, end: number}}  Inclusive range; end < start when none.
   */
  function longestBrightRun(shares, minimum) {
    const allowedGap = Math.max(1, Math.round(shares.length * OCR.screenMarginShare));
    let best = { start: 0, end: -1 };
    let start = -1;
    let lastBright = -1;
    for (let index = 0; index < shares.length; index += 1) {
      if (shares[index] < minimum) { continue; }
      if (start < 0 || index - lastBright > allowedGap) { start = index; }
      lastBright = index;
      if (lastBright - start > best.end - best.start) { best = { start: start, end: lastBright }; }
    }
    return best;
  }

  /**
   * Find the phone screen: the largest block of bright rows and columns.
   * @param {ImageData} image  The turned frame.
   * @returns {{left: number, top: number, width: number, height: number}}  The crop
   *   (the whole frame when no convincing screen is found).
   */
  function findScreenBox(image) {
    const width = image.width;
    const height = image.height;
    const whole = { left: 0, top: 0, width: width, height: height };
    const pixels = image.data;
    const histogram = new Uint32Array(HISTOGRAM_SIZE);
    const gray = new Uint8ClampedArray(width * height);
    for (let index = 0; index < width * height; index += 1) {
      gray[index] = luma(pixels, index * BYTES_PER_PIXEL);
      histogram[gray[index]] += 1;
    }
    let threshold = 0;
    let seen = 0;
    while (threshold < MAX_CHANNEL_VALUE && seen + histogram[threshold] < width * height * OCR.screenBrightPercentile) {
      seen += histogram[threshold];
      threshold += 1;
    }
    const rowShares = new Float32Array(height);
    for (let row = 0; row < height; row += 1) {
      let bright = 0;
      for (let column = 0; column < width; column += 1) { if (gray[row * width + column] >= threshold) { bright += 1; } }
      rowShares[row] = bright / width;
    }
    const rows = longestBrightRun(rowShares, OCR.screenMinBrightShare);
    if (rows.end < rows.start) { return whole; }
    const columnShares = new Float32Array(width);
    for (let column = 0; column < width; column += 1) {
      let bright = 0;
      for (let row = rows.start; row <= rows.end; row += 1) { if (gray[row * width + column] >= threshold) { bright += 1; } }
      columnShares[column] = bright / (rows.end - rows.start + 1);
    }
    const columns = longestBrightRun(columnShares, OCR.screenMinBrightShare);
    if (columns.end < columns.start) { return whole; }
    const marginX = Math.round(width * OCR.screenMarginShare);
    const marginY = Math.round(height * OCR.screenMarginShare);
    const left = Math.max(0, columns.start - marginX);
    const top = Math.max(0, rows.start - marginY);
    const box = {
      left: left,
      top: top,
      width: Math.min(width, columns.end + marginX + 1) - left,
      height: Math.min(height, rows.end + marginY + 1) - top,
    };
    return box.width * box.height >= width * height * OCR.screenMinAreaShare ? box : whole;
  }

  /**
   * Grayscale, stretch contrast (clipping a small share of the darkest and
   * lightest pixels), then sharpen lightly. Works in place.
   * @param {ImageData} image
   */
  function cleanUp(image) {
    const pixels = image.data;
    const count = image.width * image.height;
    const gray = new Float32Array(count);
    const histogram = new Uint32Array(HISTOGRAM_SIZE);
    for (let index = 0; index < count; index += 1) {
      const offset = index * BYTES_PER_PIXEL;
      const value = luma(pixels, offset);
      gray[index] = value;
      histogram[Math.min(MAX_CHANNEL_VALUE, Math.round(value))] += 1;
    }
    const clip = count * OCR.contrastCutoffFraction;
    let low = 0;
    let seen = 0;
    while (low < MAX_CHANNEL_VALUE && seen + histogram[low] <= clip) { seen += histogram[low]; low += 1; }
    let high = MAX_CHANNEL_VALUE;
    seen = 0;
    while (high > low && seen + histogram[high] <= clip) { seen += histogram[high]; high -= 1; }
    const range = Math.max(1, high - low);
    for (let index = 0; index < count; index += 1) {
      gray[index] = Math.max(0, Math.min(MAX_CHANNEL_VALUE, (gray[index] - low) * MAX_CHANNEL_VALUE / range));
    }
    const width = image.width;
    for (let index = 0; index < count; index += 1) {
      let value = gray[index];
      const column = index % width;
      if (SHARPEN_AMOUNT > 0 && column > 0 && column < width - 1 && index >= width && index < count - width) {
        const neighbours = gray[index - 1] + gray[index + 1] + gray[index - width] + gray[index + width];
        value = value + SHARPEN_AMOUNT * (4 * value - neighbours);
      }
      const clamped = Math.max(0, Math.min(MAX_CHANNEL_VALUE, value));
      const offset = index * BYTES_PER_PIXEL;
      pixels[offset] = clamped;
      pixels[offset + 1] = clamped;
      pixels[offset + 2] = clamped;
    }
  }

  /** Post all OCR texts so far; the server parses and merges them. */
  async function parseTexts(texts) {
    const body = {};
    body[KEYS.texts] = texts.slice(-OCR.textsLimit);
    const response = await fetch(CONFIG.routes.cardReading, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error("The server could not read the card text");
    }
    return response.json();
  }

  /**
   * Scan one card.
   *
   * @param {object} options
   * @param {HTMLVideoElement} options.video  Preview element (the stream is attached to it).
   * @param {function(object):void} options.onProgress  Called with the server's reading after each pass.
   * @param {function(string):void} options.onStatus  Short status text for the admin.
   * @param {function(string, number):void} [options.onCamera]  Called with the camera in use
   *   ("Front camera (1 of 2)") and how many cameras there are, after each (re)open.
   * @param {boolean|function():boolean} options.diagnostics  Save raw frames, OCR text and
   *   timings on the device for troubleshooting (POSTed to the diagnostics route). A
   *   function is asked before every record, so ticking the box mid-scan works.
   * @returns {{result: Promise<object|null>, cancel: function():void, switchCamera: function():void}}
   *   ``result`` resolves to the last server reading (complete, or the best so far
   *   when the time limit is reached or the scan is cancelled; null if nothing was read).
   */
  function scan(options) {
    let cancelled = false;
    let stream = null;
    let cameraId = rememberedCameraId();
    let facing = null;
    let lastReading = null;
    // Orientation search: index into OCR.orientations, whether it is locked, and misses since.
    let orientationIndex = 0;
    let orientationLocked = false;
    let missesSinceLock = 0;
    const texts = [];

    function stopStream() {
      if (stream !== null) {
        stream.getTracks().forEach(function (track) { track.stop(); });
        stream = null;
      }
      options.video.srcObject = null;
    }

    async function openCamera() {
      stopStream();
      const size = { width: { ideal: 1920 }, height: { ideal: 1080 } };
      // A remembered camera is asked for exactly; otherwise prefer the front camera.
      const choice = cameraId ? { deviceId: { exact: cameraId } } : { facingMode: FACING_FRONT };
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: Object.assign(choice, size), audio: false });
      } catch (error) {
        if (!cameraId) { throw error; }
        cameraId = null; // that camera is gone: fall back to any camera
        stream = await navigator.mediaDevices.getUserMedia({ video: Object.assign({ facingMode: FACING_FRONT }, size), audio: false });
      }
      options.video.srcObject = stream;
      await options.video.play();
      const track = stream.getVideoTracks()[0];
      const trackSettings = track.getSettings ? track.getSettings() : {};
      facing = trackSettings.facingMode || null;
      cameraId = trackSettings.deviceId || cameraId;
      // Mirror the front-camera preview so it behaves like a mirror; OCR uses the raw frame.
      options.video.classList.toggle("mirrored", facing === FACING_FRONT);
      if (options.onCamera) {
        listCameras().then(function (cameras) {
          options.onCamera(describeCamera(track, cameras), cameras.length);
        }).catch(function () { /* label only */ });
      }
      // Ask for continuous autofocus where the camera supports it (many tablet front cameras do not).
      const capabilities = track.getCapabilities ? track.getCapabilities() : {};
      if (capabilities.focusMode && capabilities.focusMode.indexOf("continuous") >= 0) {
        try { await track.applyConstraints({ advanced: [{ focusMode: "continuous" }] }); } catch (error) { /* keep default */ }
      }
      cameraRecord = {
        kind: "camera",
        facing: facing,
        settings: track.getSettings ? track.getSettings() : null,
        capabilities: capabilities,
        video_size: [options.video.videoWidth, options.video.videoHeight],
        user_agent: navigator.userAgent,
        cpu_cores: navigator.hardwareConcurrency,
      };
      cameraRecordSent = false;
    }

    // --- Diagnostics (only when the admin ticked "Save frames for troubleshooting") ---
    const scanStarted = Date.now();
    const scanId = (function () {
      const now = new Date();
      const two = function (value) { return String(value).padStart(2, "0"); };
      return String(now.getFullYear()) + two(now.getMonth() + 1) + two(now.getDate()) + "T"
        + two(now.getHours()) + two(now.getMinutes()) + two(now.getSeconds());
    })();
    let diagnosticFrames = 0;
    let cameraRecord = null;
    let cameraRecordSent = false;

    /** True while diagnostics are wanted (the box can be ticked during a scan). */
    function wantDiagnostics() {
      return typeof options.diagnostics === "function" ? options.diagnostics() : Boolean(options.diagnostics);
    }

    /** Send one diagnostics record (and optionally a raw frame); never slows or breaks the scan. */
    function diagnose(record, frameSource) {
      if (!wantDiagnostics()) { return; }
      if (cameraRecord !== null && !cameraRecordSent) {
        cameraRecordSent = true;
        diagnose(cameraRecord, null);
      }
      const body = {};
      record.elapsed_ms = Date.now() - scanStarted;
      body[KEYS.scanId] = scanId;
      body[KEYS.record] = record;
      if (frameSource && diagnosticFrames < OCR.diagnosticsMaxFrames) {
        diagnosticFrames += 1;
        const video = frameSource;
        const scale = Math.min(1, OCR.maxFrameWidth / video.videoWidth);
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(video.videoWidth * scale);
        canvas.height = Math.round(video.videoHeight * scale);
        canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
        body[KEYS.image] = canvas.toDataURL("image/jpeg", OCR.diagnosticsJpegQuality);
      }
      fetch(CONFIG.routes.diagnostics, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).catch(function () { /* diagnostics are best effort */ });
    }

    async function recognize(worker, canvas, layout) {
      await worker.setParameters({ tessedit_pageseg_mode: layout });
      const output = await worker.recognize(canvas);
      return output.data.text || "";
    }

    let passCount = 0;
    let done = false;
    let parsedTextCount = 0;

    /** Post every card text so far; keep the reply if it covers the most texts yet. */
    async function mergeTexts() {
      const count = texts.length;
      const reading = await parseTexts(texts.slice());
      if (count >= parsedTextCount) {
        parsedTextCount = count;
        lastReading = reading;
        if (!done && !cancelled) { options.onProgress(reading); }
      }
      return reading;
    }

    /** One worker's loop: read the newest frame, again and again, until done. */
    async function readFrames(worker, deadline) {
      while (!done && !cancelled && Date.now() < deadline) {
        const video = options.video;
        if (!video.videoWidth) {
          await sleep(FRAME_WAIT_MILLISECONDS);
          continue;
        }
        const layout = OCR.pageSegmentationModes[passCount % OCR.pageSegmentationModes.length];
        passCount += 1;
        // Locked: keep the orientation that worked. Searching: each pass tries the next one.
        const frameOrientation = orientationIndex;
        if (!orientationLocked) { orientationIndex = (orientationIndex + 1) % OCR.orientations.length; }
        const rotation = OCR.orientations[frameOrientation][0];
        const frameMirrored = OCR.orientations[frameOrientation][1];
        const passNumber = passCount;
        const prepareStarted = performance.now();
        diagnose({ kind: "frame", pass: passNumber }, video);
        const frame = prepareFrame(video, video.videoWidth, video.videoHeight, rotation, frameMirrored);
        const ocrStarted = performance.now();
        const text = await recognize(worker, frame, layout);
        diagnose({
          kind: "pass",
          pass: passNumber,
          layout: layout,
          rotation: rotation,
          mirrored: frameMirrored,
          frame_size: [frame.width, frame.height],
          prepare_ms: Math.round(ocrStarted - prepareStarted),
          ocr_ms: Math.round(performance.now() - ocrStarted),
          card_words: CARD_HINT.test(text),
          text: text,
        }, null);
        if (done || cancelled) { return; }
        if (!CARD_HINT.test(text)) {
          // No card words: the phone is not in view yet, or held another way round.
          if (orientationLocked) {
            missesSinceLock += 1;
            if (missesSinceLock >= OCR.orientationUnlockMisses) { orientationLocked = false; }
          }
          continue;
        }
        // Card words: keep this orientation for the following frames.
        orientationIndex = frameOrientation;
        orientationLocked = true;
        missesSinceLock = 0;
        texts.push(text);
        const reading = await mergeTexts();
        diagnose({
          kind: "merged",
          pass: passNumber,
          complete: reading[KEYS.card][KEYS.complete],
          missing: reading[KEYS.card][KEYS.missing],
        }, null);
        if (reading[KEYS.card][KEYS.complete]) {
          done = true;
        }
      }
    }

    async function run() {
      options.onStatus("Starting camera…");
      await openCamera();
      options.onStatus("Loading the card reader…");
      const workers = await warmUp();
      const deadline = Date.now() + OCR.giveUpSeconds * 1000;
      options.onStatus("Hold the Membership card tab up to the camera");
      await Promise.all(workers.map(function (worker, index) {
        return sleep(index * OCR.workerStaggerMilliseconds).then(function () { return readFrames(worker, deadline); });
      }));
      diagnose({
        kind: "result",
        passes: passCount,
        card_passes: texts.length,
        complete: lastReading ? lastReading[KEYS.card][KEYS.complete] : false,
        missing: lastReading ? lastReading[KEYS.card][KEYS.missing] : null,
        cancelled: cancelled,
      }, null);
      return lastReading;
    }

    const result = run().finally(stopStream);
    return {
      result: result,
      cancel: function () { cancelled = true; },
      switchCamera: async function () {
        // Step through the device's real cameras (front/back hints are not reliable on tablets).
        try {
          const cameras = await listCameras();
          if (cameras.length < 2) {
            options.onStatus("This device has only one camera");
            return;
          }
          const index = cameras.findIndex(function (camera) { return camera.deviceId === cameraId; });
          cameraId = cameras[(index + 1) % cameras.length].deviceId;
          rememberCameraId(cameraId);
          orientationIndex = 0;
          orientationLocked = false;
          missesSinceLock = 0;
          await openCamera();
        } catch (error) {
          options.onStatus("Could not switch camera");
        }
      },
    };
  }

  /** Whether "Save frames for troubleshooting" is ticked (remembered on this device). */
  function diagnosticsEnabled() {
    try { return localStorage.getItem(OCR.diagnosticsStorageKey) === "1"; } catch (error) { return false; }
  }

  function setDiagnosticsEnabled(enabled) {
    try { localStorage.setItem(OCR.diagnosticsStorageKey, enabled ? "1" : "0"); } catch (error) { /* private mode */ }
  }

  return {
    warmUp: warmUp,
    scan: scan,
    prepareFrame: prepareFrame,
    diagnosticsEnabled: diagnosticsEnabled,
    setDiagnosticsEnabled: setDiagnosticsEnabled,
  };
})();
