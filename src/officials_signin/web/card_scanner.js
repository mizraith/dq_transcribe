/**
 * Card scanner: reads a USA Swimming membership card from the tablet camera.
 *
 * The official holds up their phone (USA Swimming app, "Membership card" tab).
 * This script keeps grabbing camera frames, cleans each one up (grayscale +
 * auto-contrast + light sharpening), runs Tesseract.js on it in a web worker,
 * and posts every pass's text to the server, which parses and merges them.
 * It stops by itself as soon as every required field has been read, so the
 * common case needs no shutter tap.
 *
 * Successive frames cycle through Tesseract page layouts (each tends to read
 * different rows). A frame whose text has no card labels is tried again
 * mirrored, because front cameras and some camera apps flip the image; once
 * mirroring helps, later frames are mirrored straight away.
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

  let workerPromise = null;

  /** Start loading the OCR engine (about 7 MB, from localhost) so the first scan is quick. */
  function warmUp() {
    if (workerPromise === null) {
      workerPromise = window.Tesseract.createWorker(OCR.language, 1, {
        workerPath: OCR.enginePath + OCR.workerScript,
        corePath: OCR.enginePath + OCR.coreScript,
        langPath: OCR.languageDataPath,
        workerBlobURL: false,
        gzip: true,
      });
      workerPromise.catch(function () { workerPromise = null; });
    }
    return workerPromise;
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
    }

    async function recognize(worker, canvas, layout) {
      await worker.setParameters({ tessedit_pageseg_mode: layout });
      const output = await worker.recognize(canvas);
      return output.data.text || "";
    }

    async function run() {
      options.onStatus("Starting camera…");
      await openCamera();
      options.onStatus("Loading the card reader…");
      const worker = await warmUp();
      const deadline = Date.now() + OCR.giveUpSeconds * 1000;
      let pass = 0;
      options.onStatus("Hold the Membership card tab up to the camera");
      while (!cancelled && Date.now() < deadline) {
        const video = options.video;
        if (!video.videoWidth) {
          await new Promise(function (resolve) { setTimeout(resolve, 200); });
          continue;
        }
        const layout = OCR.pageSegmentationModes[pass % OCR.pageSegmentationModes.length];
        pass += 1;
        let text = await recognize(worker, prepareFrame(video, video.videoWidth, video.videoHeight, mirrorFrames), layout);
        if (cancelled) { break; }
        let reading = await parseTexts(texts.concat([text]));
        if (reading[KEYS.card][KEYS.labelsFound] === 0 && texts.length === 0) {
          // No card labels at all: try the same frame mirrored.
          const flipped = await recognize(worker, prepareFrame(video, video.videoWidth, video.videoHeight, !mirrorFrames), layout);
          const flippedReading = await parseTexts([flipped]);
          if (flippedReading[KEYS.card][KEYS.labelsFound] > 0) {
            mirrorFrames = !mirrorFrames;
            text = flipped;
            reading = flippedReading;
          }
        }
        if (reading[KEYS.card][KEYS.labelsFound] > 0) {
          texts.push(text);
          lastReading = reading;
          options.onProgress(reading);
          if (reading[KEYS.card][KEYS.complete]) {
            return reading;
          }
        }
      }
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
        openCamera().catch(function () { options.onStatus("Could not switch camera"); });
      },
    };
  }

  return { warmUp: warmUp, scan: scan, prepareFrame: prepareFrame };
})();
