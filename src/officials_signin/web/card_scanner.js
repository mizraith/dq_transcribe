/**
 * Card scanner: reads a USA Swimming membership card from the tablet camera.
 *
 * Two phases, so the slow part (OCR) only ever sees a good picture:
 *
 * 1. Live guide (no OCR). Several times a second a small preview frame is checked:
 *    is the whole phone screen in view, big enough, sharp, and held still? A frame
 *    is drawn around the phone (red: no phone; amber: move back / closer / hold
 *    still; green: good) with a hint underneath.
 * 2. Still capture. After about half a second of green, a short burst of frames is
 *    taken and the sharpest are kept. Each is cropped to the screen, turned upright
 *    (a screen wider than tall is a sideways phone), cleaned up, and read by two
 *    Tesseract.js workers in parallel. The server parses and merges the passes; the
 *    scan ends when every field is read (and a new name agrees twice). If not, the
 *    guide comes back for another capture.
 *
 * Everything runs on this device: the OCR engine is served from localhost
 * (web/vendor/tesseract) and frames are never uploaded or stored (except, when
 * "Save frames for troubleshooting" is ticked, to the local diagnostics folder).
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
  const FULL_TURN = 360;
  const GUIDE = OCR.guide;
  const STATES = GUIDE.states;
  const FRAME_WAIT_MILLISECONDS = 200;
  const LAYOUT_SPARSE = OCR.pageSegmentationModes[0];
  const LAYOUT_COLUMN = OCR.pageSegmentationModes[1 % OCR.pageSegmentationModes.length];
  const WARM_UP_CANVAS_SIZE = 32;
  const SHARPNESS_SCALE = 1000;

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
      // One tiny recognize per worker finishes the engine's lazy start-up now,
      // instead of during the first real scan (seen taking 18-35 s on the tablet).
      poolPromise = Promise.all(workers).then(async function (ready) {
        const blank = document.createElement("canvas");
        blank.width = WARM_UP_CANVAS_SIZE;
        blank.height = WARM_UP_CANVAS_SIZE;
        await Promise.all(ready.map(function (worker) { return worker.recognize(blank); }));
        return ready;
      });
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
   * Crop a still to the phone screen, turn it upright, scale it for OCR and clean it up.
   * @param {HTMLCanvasElement} still  Full-resolution camera frame.
   * @param {{left: number, top: number, width: number, height: number}} box  Screen box in
   *   still pixels (with margin).
   * @param {number} rotation  Clockwise turn: 0, 90, 180 or 270 degrees.
   * @param {boolean} mirror  Flip left-right (after turning).
   * @returns {HTMLCanvasElement}
   */
  function prepareStill(still, box, rotation, mirror) {
    const sideways = rotation === QUARTER_TURN || rotation === THREE_QUARTER_TURN;
    const uprightWidth = sideways ? box.height : box.width;
    const scale = Math.min(GUIDE.maxUpscale, GUIDE.uprightScreenWidth / uprightWidth);
    const scaledWidth = Math.round(box.width * scale);
    const scaledHeight = Math.round(box.height * scale);
    const canvas = document.createElement("canvas");
    canvas.width = sideways ? scaledHeight : scaledWidth;
    canvas.height = sideways ? scaledWidth : scaledHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.translate(canvas.width / 2, canvas.height / 2);
    if (mirror) { context.scale(-1, 1); }
    context.rotate(rotation * Math.PI / HALF_TURN);
    context.drawImage(still, box.left, box.top, box.width, box.height,
      -scaledWidth / 2, -scaledHeight / 2, scaledWidth, scaledHeight);
    context.setTransform(1, 0, 0, 1, 0, 0);
    const image = context.getImageData(0, 0, canvas.width, canvas.height);
    cleanUp(image);
    context.putImageData(image, 0, 0);
    return canvas;
  }

  /** Copy the current video frame at full resolution. */
  function grabFrame(video) {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    return canvas;
  }

  /** Grayscale values of a small copy of a frame (or canvas), for the live guide. */
  function smallGray(source, sourceWidth, sourceHeight, analysisCanvas) {
    const scale = GUIDE.analysisWidth / sourceWidth;
    analysisCanvas.width = GUIDE.analysisWidth;
    analysisCanvas.height = Math.round(sourceHeight * scale);
    const context = analysisCanvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(source, 0, 0, analysisCanvas.width, analysisCanvas.height);
    const image = context.getImageData(0, 0, analysisCanvas.width, analysisCanvas.height);
    const gray = new Uint8ClampedArray(image.width * image.height);
    for (let index = 0; index < gray.length; index += 1) { gray[index] = luma(image.data, index * BYTES_PER_PIXEL); }
    return { gray: gray, width: image.width, height: image.height };
  }

  /**
   * Sharpness of the screen area: Laplacian energy divided by the contrast squared,
   * so a dim and a bright screen score alike. Blur lowers it sharply.
   */
  function sharpness(frame, area) {
    const gray = frame.gray;
    const width = frame.width;
    let energy = 0;
    let count = 0;
    let low = MAX_CHANNEL_VALUE;
    let high = 0;
    for (let row = area.top + 1; row < area.top + area.height - 1; row += 1) {
      for (let column = area.left + 1; column < area.left + area.width - 1; column += 1) {
        const index = row * width + column;
        const value = gray[index];
        const laplacian = 4 * value - gray[index - 1] - gray[index + 1] - gray[index - width] - gray[index + width];
        energy += laplacian * laplacian;
        count += 1;
        if (value < low) { low = value; }
        if (value > high) { high = value; }
      }
    }
    const contrast = Math.max(1, high - low);
    return count ? (energy / count) / (contrast * contrast) * SHARPNESS_SCALE : 0;
  }

  /**
   * Is the text running sideways? Lines of text make the brightness change sharply
   * from one row to the next (upright) or from one column to the next (sideways).
   * @returns {number}  Column change energy divided by row change energy: above 1
   *   means the text runs up/down, so the phone is turned sideways.
   */
  function sidewaysRatio(frame, screen) {
    const trimX = Math.round(screen.width * GUIDE.sidewaysInnerTrim);
    const trimY = Math.round(screen.height * GUIDE.sidewaysInnerTrim);
    const area = {
      left: screen.left + trimX,
      top: screen.top + trimY,
      width: Math.max(2, screen.width - 2 * trimX),
      height: Math.max(2, screen.height - 2 * trimY),
    };
    const gray = frame.gray;
    const width = frame.width;
    const rowMeans = new Float32Array(area.height);
    const columnMeans = new Float32Array(area.width);
    for (let row = 0; row < area.height; row += 1) {
      for (let column = 0; column < area.width; column += 1) {
        const value = gray[(area.top + row) * width + area.left + column];
        rowMeans[row] += value / area.width;
        columnMeans[column] += value / area.height;
      }
    }
    const changeEnergy = function (means) {
      let total = 0;
      for (let index = 1; index < means.length; index += 1) {
        const change = means[index] - means[index - 1];
        total += change * change;
      }
      return total / Math.max(1, means.length - 1);
    };
    return changeEnergy(columnMeans) / Math.max(1e-6, changeEnergy(rowMeans));
  }

  /**
   * Which way to turn a sideways phone upright. The app's dark header bar is the top:
   * darker on the right means the top is on the right, so turn a quarter anticlockwise
   * (270 degrees clockwise); darker on the left means turn 90 degrees clockwise.
   */
  function sidewaysTurn(frame, screen) {
    const band = Math.max(1, Math.round(screen.width * GUIDE.headerShare));
    const meanOfColumns = function (firstColumn) {
      let total = 0;
      for (let row = screen.top; row < screen.top + screen.height; row += 1) {
        for (let column = firstColumn; column < firstColumn + band; column += 1) { total += frame.gray[row * frame.width + column]; }
      }
      return total / (band * screen.height);
    };
    return meanOfColumns(screen.left + screen.width - band) < meanOfColumns(screen.left) ? THREE_QUARTER_TURN : QUARTER_TURN;
  }

  /** Mean brightness change between two small frames of the same size. */
  function motion(previous, current) {
    if (!previous || previous.gray.length !== current.gray.length) { return 0; }
    let total = 0;
    for (let index = 0; index < current.gray.length; index += 1) {
      total += Math.abs(current.gray[index] - previous.gray[index]);
    }
    return total / current.gray.length;
  }

  /** Brightness of one pixel (ITU-R BT.601 luma). */
  function luma(pixels, offset) {
    return LUMA_RED * pixels[offset] + LUMA_GREEN * pixels[offset + 1] + LUMA_BLUE * pixels[offset + 2];
  }

  /** Value at a quantile (0-1) of an array of numbers (the array is sorted in place). */
  function quantile(values, fraction) {
    values.sort(function (first, second) { return first - second; });
    return values[Math.min(values.length - 1, Math.floor(fraction * (values.length - 1)))];
  }

  /**
   * Find the phone screen in a small gray frame.
   *
   * The frame is split into square cells. A cell is "screen" when its bright pixels
   * (the background behind any text) are nearly as bright as the brightest cells in
   * view. Touching screen cells are grouped; the group with the most text-like
   * texture wins, so a lit wall or a face (bright but smooth) loses to the card.
   *
   * @param {{gray: Uint8ClampedArray, width: number, height: number}} frame  Small gray frame.
   * @returns {{found: boolean, left: number, top: number, width: number, height: number,
   *   touchesEdge: boolean}}  The screen in frame pixels (without margin).
   */
  function findScreen(frame) {
    const size = OCR.screenCellPixels;
    const columns = Math.floor(frame.width / size);
    const rows = Math.floor(frame.height / size);
    const none = { found: false, left: 0, top: 0, width: frame.width, height: frame.height, touchesEdge: false };
    if (columns < 2 || rows < 2) { return none; }
    const backgrounds = new Float32Array(columns * rows);
    const spreads = new Float32Array(columns * rows);
    const cellValues = new Array(size * size);
    for (let cellRow = 0; cellRow < rows; cellRow += 1) {
      for (let cellColumn = 0; cellColumn < columns; cellColumn += 1) {
        let sum = 0;
        let sumSquares = 0;
        let count = 0;
        for (let y = 0; y < size; y += 1) {
          const offset = (cellRow * size + y) * frame.width + cellColumn * size;
          for (let x = 0; x < size; x += 1) {
            const value = frame.gray[offset + x];
            cellValues[count] = value;
            sum += value;
            sumSquares += value * value;
            count += 1;
          }
        }
        const cell = cellRow * columns + cellColumn;
        const mean = sum / count;
        spreads[cell] = Math.sqrt(Math.max(0, sumSquares / count - mean * mean));
        backgrounds[cell] = quantile(cellValues, OCR.screenCellBrightQuantile);
      }
    }
    const threshold = OCR.screenBrightRatio * quantile(Array.from(backgrounds), OCR.screenReferenceQuantile);
    const visited = new Uint8Array(columns * rows);
    let best = null;
    for (let start = 0; start < columns * rows; start += 1) {
      if (visited[start] || backgrounds[start] < threshold) { continue; }
      // Flood-fill one group of touching screen cells.
      const queue = [start];
      visited[start] = 1;
      let cells = 0;
      let textured = 0;
      let minColumn = columns;
      let maxColumn = -1;
      let minRow = rows;
      let maxRow = -1;
      while (queue.length) {
        const cell = queue.pop();
        const cellRow = Math.floor(cell / columns);
        const cellColumn = cell % columns;
        cells += 1;
        if (spreads[cell] >= OCR.screenTextureSpread) { textured += 1; }
        minColumn = Math.min(minColumn, cellColumn);
        maxColumn = Math.max(maxColumn, cellColumn);
        minRow = Math.min(minRow, cellRow);
        maxRow = Math.max(maxRow, cellRow);
        const neighbours = [
          cellColumn > 0 ? cell - 1 : -1,
          cellColumn < columns - 1 ? cell + 1 : -1,
          cellRow > 0 ? cell - columns : -1,
          cellRow < rows - 1 ? cell + columns : -1,
        ];
        neighbours.forEach(function (next) {
          if (next >= 0 && !visited[next] && backgrounds[next] >= threshold) {
            visited[next] = 1;
            queue.push(next);
          }
        });
      }
      const score = textured + OCR.screenPlainCellWeight * cells;
      if (best === null || score > best.score) {
        best = { score: score, minColumn: minColumn, maxColumn: maxColumn, minRow: minRow, maxRow: maxRow };
      }
    }
    if (best === null) { return none; }
    const screen = {
      found: true,
      left: best.minColumn * size,
      top: best.minRow * size,
      width: (best.maxColumn - best.minColumn + 1) * size,
      height: (best.maxRow - best.minRow + 1) * size,
    };
    if (screen.width * screen.height < frame.width * frame.height * OCR.screenMinAreaShare) { return none; }
    // Cells cover the frame only up to a whole number of cells; measure edges against that.
    const coveredWidth = columns * size;
    const coveredHeight = rows * size;
    const edgeX = Math.max(1, Math.round(coveredWidth * GUIDE.edgeMarginShare));
    const edgeY = Math.max(1, Math.round(coveredHeight * GUIDE.edgeMarginShare));
    screen.touchesTopOrBottom = screen.top < edgeY || screen.top + screen.height > coveredHeight - edgeY;
    screen.touchesSide = screen.left < edgeX || screen.left + screen.width > coveredWidth - edgeX;
    screen.touchesEdge = screen.touchesTopOrBottom || screen.touchesSide;
    return screen;
  }

  /** A screen box grown by the crop margin and scaled to another frame size. */
  function scaleBox(screen, fromWidth, fromHeight, toWidth, toHeight) {
    const scaleX = toWidth / fromWidth;
    const scaleY = toHeight / fromHeight;
    const marginX = Math.round(toWidth * OCR.screenMarginShare);
    const marginY = Math.round(toHeight * OCR.screenMarginShare);
    const left = Math.max(0, Math.round(screen.left * scaleX) - marginX);
    const top = Math.max(0, Math.round(screen.top * scaleY) - marginY);
    return {
      left: left,
      top: top,
      width: Math.min(toWidth, Math.round((screen.left + screen.width) * scaleX) + marginX) - left,
      height: Math.min(toHeight, Math.round((screen.top + screen.height) * scaleY) + marginY) - top,
    };
  }

  /**
   * Judge one small frame for the live guide.
   * @returns {{state: string, screen: object, sharpness: number, motion: number}}
   */
  function judgeFrame(frame, previous) {
    const screen = findScreen(frame);
    const moved = motion(previous, frame);
    if (!screen.found) { return { state: STATES.noScreen, screen: screen, sharpness: 0, motion: moved }; }
    const score = sharpness(frame, screen);
    const longSide = Math.max(screen.width, screen.height);
    const upright = screen.height > screen.width;
    let state = STATES.good;
    if (upright && screen.touchesTopOrBottom) {
      // An upright phone close enough to read rarely fits a wide camera view.
      state = STATES.turnSideways;
    } else if (screen.touchesEdge) {
      state = STATES.edge;
    } else if (longSide < Math.min(frame.width, frame.height) * GUIDE.minScreenShare
      || screen.width * screen.height < frame.width * frame.height * GUIDE.minScreenAreaShare) {
      state = STATES.small;
    } else if (moved > GUIDE.maxMotion) {
      state = STATES.moving;
    } else if (score < GUIDE.minSharpness) {
      state = STATES.blurry;
    }
    return { state: state, screen: screen, sharpness: score, motion: moved };
  }

  /**
   * Turn an image into black text on white for OCR, in place (adaptive threshold):
   * a pixel is ink when it is darker than the mean of the square around it by more
   * than ``OCR.thresholdOffset``. Grey text next to dark phone edges survives, which a
   * single threshold for the whole image would lose.
   * @param {ImageData} image
   */
  function cleanUp(image) {
    const width = image.width;
    const height = image.height;
    const pixels = image.data;
    const gray = new Float32Array(width * height);
    for (let index = 0; index < gray.length; index += 1) { gray[index] = luma(pixels, index * BYTES_PER_PIXEL); }
    // Summed-area table, one extra row and column of zeros.
    const stride = width + 1;
    const sums = new Float64Array(stride * (height + 1));
    for (let row = 0; row < height; row += 1) {
      let rowSum = 0;
      for (let column = 0; column < width; column += 1) {
        rowSum += gray[row * width + column];
        sums[(row + 1) * stride + column + 1] = sums[row * stride + column + 1] + rowSum;
      }
    }
    const half = Math.floor(OCR.thresholdWindow / 2);
    for (let row = 0; row < height; row += 1) {
      const top = Math.max(0, row - half);
      const bottom = Math.min(height, row + half + 1);
      for (let column = 0; column < width; column += 1) {
        const left = Math.max(0, column - half);
        const right = Math.min(width, column + half + 1);
        const area = (bottom - top) * (right - left);
        const total = sums[bottom * stride + right] - sums[top * stride + right]
          - sums[bottom * stride + left] + sums[top * stride + left];
        const index = row * width + column;
        const value = gray[index] < total / area - OCR.thresholdOffset ? 0 : MAX_CHANNEL_VALUE;
        const offset = index * BYTES_PER_PIXEL;
        pixels[offset] = value;
        pixels[offset + 1] = value;
        pixels[offset + 2] = value;
      }
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
   * @param {HTMLElement} [options.stage]  Element holding the video and overlay (mirrored together).
   * @param {HTMLCanvasElement} [options.overlay]  Canvas over the video for the guide frame.
   * @param {function(string, string, string):void} [options.onGuide]  Called with the guide
   *   state, its hint text and colour after every check.
   * @param {function(string, number):void} [options.onCamera]  Called with the camera in use
   *   ("Front camera (1 of 2)") and how many cameras there are, after each (re)open.
   * @param {boolean|function():boolean} options.diagnostics  Save raw frames, OCR text and
   *   timings on the device for troubleshooting (POSTed to the diagnostics route). A
   *   function is asked before every record, so ticking the box mid-scan works.
   * @returns {{result: Promise<object|null>, cancel: function():void, captureNow: function():void,
   *   switchCamera: function():void}}
   *   ``result`` resolves to the last server reading (complete, or the best so far
   *   when the time limit is reached or the scan is cancelled; null if nothing was read).
   */
  function scan(options) {
    let cancelled = false;
    let stream = null;
    let cameraId = rememberedCameraId();
    let facing = null;
    let lastReading = null;
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
      (options.stage || options.video).classList.toggle("mirrored", facing === FACING_FRONT);
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
        // A video element or a canvas (stills).
        const sourceWidth = frameSource.videoWidth || frameSource.width;
        const sourceHeight = frameSource.videoHeight || frameSource.height;
        const scale = Math.min(1, OCR.maxFrameWidth / Math.max(sourceWidth, sourceHeight));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(sourceWidth * scale);
        canvas.height = Math.round(sourceHeight * scale);
        canvas.getContext("2d").drawImage(frameSource, 0, 0, canvas.width, canvas.height);
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

    // --- Live guide ------------------------------------------------------------

    const analysisCanvas = document.createElement("canvas");
    const overlay = options.overlay || null;
    let captureRequested = false;

    /** Draw the coloured frame around the screen (or around the whole view) on the overlay. */
    function drawGuide(judgement, frame) {
      if (!overlay) { return; }
      overlay.width = frame.width;
      overlay.height = frame.height;
      const context = overlay.getContext("2d");
      context.clearRect(0, 0, overlay.width, overlay.height);
      context.strokeStyle = GUIDE.colours[judgement.state];
      context.lineWidth = GUIDE.lineWidth;
      const screen = judgement.screen;
      const area = screen.found ? screen : { left: 0, top: 0, width: frame.width, height: frame.height };
      context.strokeRect(area.left, area.top, area.width, area.height);
    }

    /** Freeze the preview on a captured still while it is read. */
    function showStill(still) {
      if (!overlay) { return; }
      const context = overlay.getContext("2d");
      context.drawImage(still, 0, 0, overlay.width, overlay.height);
      context.strokeStyle = GUIDE.colours[STATES.reading];
      context.lineWidth = GUIDE.lineWidth;
      context.strokeRect(0, 0, overlay.width, overlay.height);
    }

    function guide(state) {
      if (options.onGuide) { options.onGuide(state, GUIDE.messages[state], GUIDE.colours[state]); }
    }

    /**
     * Watch the preview until the phone has been in view, sharp and still for a moment
     * (or the admin taps "Capture now").
     * @returns {Promise<object|null>}  The last good judgement (screen in small-frame
     *   pixels), or null if cancelled / out of time.
     */
    async function waitForGoodView(deadline) {
      let previous = null;
      let goodChecks = 0;
      let checks = 0;
      let lastJudgement = null;
      while (!cancelled && Date.now() < deadline) {
        const video = options.video;
        if (!video.videoWidth) { await sleep(FRAME_WAIT_MILLISECONDS); continue; }
        const frame = smallGray(video, video.videoWidth, video.videoHeight, analysisCanvas);
        const judgement = judgeFrame(frame, previous);
        previous = frame;
        checks += 1;
        drawGuide(judgement, frame);
        guide(judgement.state);
        if (checks % GUIDE.diagnosticsEveryChecks === 0) {
          diagnose({
            kind: "guide",
            state: judgement.state,
            sharpness: Math.round(judgement.sharpness * 10) / 10,
            motion: Math.round(judgement.motion * 10) / 10,
            screen: judgement.screen.found
              ? [judgement.screen.left, judgement.screen.top, judgement.screen.width, judgement.screen.height] : null,
            frame: [frame.width, frame.height],
          }, null);
        }
        if (judgement.screen.found) { lastJudgement = { judgement: judgement, frame: frame }; }
        goodChecks = judgement.state === STATES.good ? goodChecks + 1 : 0;
        if (goodChecks >= GUIDE.goodChecksToCapture) { return lastJudgement; }
        if (captureRequested) {
          captureRequested = false;
          return lastJudgement || { judgement: judgement, frame: frame };
        }
        await sleep(GUIDE.intervalMilliseconds);
      }
      return null;
    }

    /**
     * Take a short burst of full-resolution frames and keep the sharpest.
     * @returns {Promise<{stills: HTMLCanvasElement[], box: object, sideways: boolean}>}
     */
    /**
     * Take a full-resolution photo with the camera (ImageCapture), or null where the
     * browser cannot, it fails, or it takes too long.
     */
    async function takePhoto() {
      const track = stream ? stream.getVideoTracks()[0] : null;
      if (!track || typeof window.ImageCapture === "undefined") { return null; }
      try {
        const imageCapture = new window.ImageCapture(track);
        const timeout = new Promise(function (resolve) {
          setTimeout(function () { resolve(null); }, GUIDE.photoTimeoutMilliseconds);
        });
        const blob = await Promise.race([imageCapture.takePhoto(), timeout]);
        if (!blob) { return null; }
        const bitmap = await createImageBitmap(blob, { imageOrientation: "from-image" });
        const canvas = document.createElement("canvas");
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        canvas.getContext("2d").drawImage(bitmap, 0, 0);
        return canvas;
      } catch (error) {
        diagnose({ kind: "photo_failed", error: String(error) }, null);
        return null;
      }
    }

    /** Measure one still: its own screen box (stills may differ in size and framing) and sharpness. */
    function measureStill(canvas, fallbackScreen, source) {
      const small = smallGray(canvas, canvas.width, canvas.height, analysisCanvas);
      const found = findScreen(small);
      const screen = found.found ? found : fallbackScreen;
      const ratio = sidewaysRatio(small, screen);
      const sideways = ratio > GUIDE.sidewaysRatio;
      return {
        canvas: canvas,
        small: small,
        screen: screen,
        score: sharpness(small, screen),
        box: scaleBox(screen, small.width, small.height, canvas.width, canvas.height),
        source: source,
        found: found.found,
        sidewaysRatio: ratio,
        // Best guess at the turn that makes this still upright (each still may differ:
        // a camera photo can come out turned relative to the video).
        rotation: sideways ? sidewaysTurn(small, screen) : 0,
        mirror: false,
      };
    }

    /**
     * Take the stills to read: a full-resolution photo (where supported) plus a short
     * burst of video frames, keeping the photo and the sharpest frame (or the two
     * sharpest frames when there is no photo).
     * @returns {Promise<{stills: object[], sideways: boolean, rotation: number}>}
     *   Each still has ``canvas`` and ``box`` (the screen in that still's pixels).
     */
    async function captureStills(view) {
      const video = options.video;
      const photoPromise = takePhoto();
      const frames = [];
      for (let index = 0; index < GUIDE.burstFrames; index += 1) {
        frames.push(measureStill(grabFrame(video), view.judgement.screen, "video"));
        if (index < GUIDE.burstFrames - 1) { await sleep(GUIDE.burstIntervalMilliseconds); }
      }
      frames.sort(function (first, second) { return second.score - first.score; });
      const photoCanvas = await photoPromise;
      const photo = photoCanvas ? measureStill(photoCanvas, null, "photo") : null;
      const stills = photo && photo.found
        ? [photo].concat(frames.slice(0, GUIDE.stillsKept - 1))
        : frames.slice(0, GUIDE.stillsKept);
      stills.forEach(function (still, index) {
        diagnose({
          kind: "still", rank: index + 1, source: still.source, size: [still.canvas.width, still.canvas.height],
          sharpness: Math.round(still.score * 10) / 10, box: [still.box.left, still.box.top, still.box.width, still.box.height],
          sideways_ratio: Math.round(still.sidewaysRatio * 100) / 100, rotation: still.rotation,
        }, still.canvas);
      });
      return { stills: stills };
    }

    /** OCR one prepared still on one worker and merge the result; returns the text. */
    async function readStill(worker, still, rotation, mirror, layout) {
      passCount += 1;
      const passNumber = passCount;
      const started = performance.now();
      const prepared = prepareStill(still.canvas, still.box, rotation, mirror);
      const ocrStarted = performance.now();
      const text = await recognize(worker, prepared, layout);
      diagnose({
        kind: "pass", pass: passNumber, source: still.source, layout: layout, rotation: rotation, mirrored: mirror,
        frame_size: [prepared.width, prepared.height], prepare_ms: Math.round(ocrStarted - started),
        ocr_ms: Math.round(performance.now() - ocrStarted), card_words: CARD_HINT.test(text), text: text,
      }, null);
      return text;
    }

    /** Merge a batch of new texts (those with card words) and report progress. */
    async function mergeNew(newTexts) {
      newTexts.filter(function (text) { return CARD_HINT.test(text); }).forEach(function (text) { texts.push(text); });
      if (texts.length === 0) { return null; }
      const reading = await parseTexts(texts.slice());
      lastReading = reading;
      if (!cancelled) { options.onProgress(reading); }
      diagnose({ kind: "merged", passes: texts.length, complete: reading[KEYS.card][KEYS.complete], missing: reading[KEYS.card][KEYS.missing] }, null);
      if (reading[KEYS.card][KEYS.complete]) { done = true; }
      return reading;
    }

    /**
     * Read the captured stills with both workers in parallel, stopping as soon as the
     * card is complete. Sideways screens are tried turned both ways first.
     */
    async function readCapture(workers, capture) {
      const stills = capture.stills;
      const first = stills[0];
      const second = stills[1] || first;
      const worker = function (index) { return workers[index % workers.length]; };

      /** Read each still once (in parallel) with its current orientation; keep orientations that worked. */
      async function readRound(items) {
        const results = await Promise.all(items.map(function (item, index) {
          return readStill(worker(index), item.still, item.still.rotation, item.still.mirror, item.layout);
        }));
        await mergeNew(results);
        return results.map(function (text) { return CARD_HINT.test(text); });
      }

      // Round 1: each still the way its own measurements say is up.
      let found = await readRound([{ still: first, layout: LAYOUT_SPARSE }, { still: second, layout: LAYOUT_COLUMN }]);
      if (done || cancelled) { return; }
      // No card words: turn those stills half round (wrong guess of which end is up).
      const retry = [first, second].filter(function (still, index) { return !found[index]; });
      if (retry.length === 2 || (retry.length === 1 && texts.length === 0)) {
        retry.forEach(function (still) { still.rotation = (still.rotation + HALF_TURN) % FULL_TURN; });
        found = await readRound(retry.map(function (still, index) {
          return { still: still, layout: index === 0 ? LAYOUT_SPARSE : LAYOUT_COLUMN };
        }));
        if (done || cancelled) { return; }
      }
      if (texts.length === 0) {
        // Still nothing: maybe a mirrored image.
        first.rotation = (first.rotation + HALF_TURN) % FULL_TURN;
        first.mirror = true;
        await readRound([{ still: first, layout: LAYOUT_SPARSE }]);
        if (done || cancelled || texts.length === 0) { return; }
      }
      // Follow-ups: the other layout on each still.
      await readRound([{ still: first, layout: LAYOUT_COLUMN }, { still: second, layout: LAYOUT_SPARSE }]);
    }

    async function run() {
      options.onStatus("Starting camera…");
      await openCamera();
      options.onStatus("");
      const workersReady = warmUp();
      const deadline = Date.now() + OCR.giveUpSeconds * 1000;
      while (!done && !cancelled && Date.now() < deadline) {
        const view = await waitForGoodView(deadline);
        if (view === null) { break; }
        const capture = await captureStills(view);
        showStill(capture.stills[0].canvas);
        guide(STATES.reading);
        const workers = await workersReady;
        await readCapture(workers, capture);
        if (!done && !cancelled) { guide(STATES.retry); await sleep(GUIDE.intervalMilliseconds * GUIDE.goodChecksToCapture); }
      }
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
      captureNow: function () { captureRequested = true; },
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
    prepareStill: prepareStill,
    smallGray: smallGray,
    sidewaysRatio: sidewaysRatio,
    sidewaysTurn: sidewaysTurn,
    judgeFrame: judgeFrame,
    diagnosticsEnabled: diagnosticsEnabled,
    setDiagnosticsEnabled: setDiagnosticsEnabled,
  };
})();
