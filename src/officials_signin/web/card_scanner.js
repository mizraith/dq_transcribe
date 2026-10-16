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
 * rows). A frame with plenty of text but no card words is probably mirrored
 * (front cameras and some camera apps flip the image), so the next frames are
 * flipped. Frames with little text (phone not in view yet) cost one pass only.
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
  const CAMERA_STORAGE_KEY = "officials_signin.camera_facing";
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
  const LETTER = /[A-Za-z]/g;
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

  /** The camera the admin last used (front by default: officials face the tablet). */
  function preferredFacing() {
    try {
      return localStorage.getItem(CAMERA_STORAGE_KEY) || FACING_FRONT;
    } catch (error) {
      return FACING_FRONT;
    }
  }

  function rememberFacing(facing) {
    try { localStorage.setItem(CAMERA_STORAGE_KEY, facing); } catch (error) { /* private mode: fine */ }
  }

  /**
   * Draw a video frame (or image) onto a canvas, scaled down, cleaned up for OCR.
   * @param {CanvasImageSource} source  Video element or image.
   * @param {number} width  Source width in pixels.
   * @param {number} height  Source height in pixels.
   * @param {boolean} mirror  Flip left-right.
   * @returns {HTMLCanvasElement}
   */
  function prepareFrame(source, width, height, mirror) {
    const scale = Math.min(1, OCR.maxFrameWidth / width);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (mirror) {
      context.translate(canvas.width, 0);
      context.scale(-1, 1);
    }
    context.drawImage(source, 0, 0, canvas.width, canvas.height);
    const image = context.getImageData(0, 0, canvas.width, canvas.height);
    cleanUp(image);
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.putImageData(image, 0, 0);
    return canvas;
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
      const value = LUMA_RED * pixels[offset] + LUMA_GREEN * pixels[offset + 1] + LUMA_BLUE * pixels[offset + 2];
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
    let facing = preferredFacing();
    let lastReading = null;
    let mirrorFrames = false;
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
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: facing, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
      options.video.srcObject = stream;
      // Mirror the front-camera preview so it behaves like a mirror; OCR uses the raw frame.
      options.video.classList.toggle("mirrored", facing === FACING_FRONT);
      await options.video.play();
      const track = stream.getVideoTracks()[0];
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
    let orientationFixed = false;
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
        const frameMirrored = mirrorFrames;
        const passNumber = passCount;
        const prepareStarted = performance.now();
        diagnose({ kind: "frame", pass: passNumber }, video);
        const frame = prepareFrame(video, video.videoWidth, video.videoHeight, frameMirrored);
        const ocrStarted = performance.now();
        const text = await recognize(worker, frame, layout);
        diagnose({
          kind: "pass",
          pass: passNumber,
          layout: layout,
          mirrored: frameMirrored,
          frame_size: [frame.width, frame.height],
          prepare_ms: Math.round(ocrStarted - prepareStarted),
          ocr_ms: Math.round(performance.now() - ocrStarted),
          card_words: CARD_HINT.test(text),
          text: text,
        }, null);
        if (done || cancelled) { return; }
        if (!CARD_HINT.test(text)) {
          // Lots of text but no card words: probably mirrored, so flip the next frames.
          // Little text: the phone is not in view yet. Only the orientation this frame
          // used is flipped (another worker may already have flipped it), and never
          // after a card frame has fixed the orientation.
          const letterCount = (text.match(LETTER) || []).length;
          if (!orientationFixed && letterCount >= OCR.mirrorMinLetters && frameMirrored === mirrorFrames) {
            mirrorFrames = !frameMirrored;
          }
          continue;
        }
        orientationFixed = true;
        mirrorFrames = frameMirrored;
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
      switchCamera: function () {
        facing = facing === FACING_FRONT ? FACING_BACK : FACING_FRONT;
        rememberFacing(facing);
        mirrorFrames = false;
        orientationFixed = false;
        openCamera().catch(function () { options.onStatus("Could not switch camera"); });
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
