/**
 * dq_transcribe web app.
 *
 * Listens to the microphone, cuts speech into clips (starting when sound
 * appears and ending after a stretch of quiet), uploads each clip to the local
 * server, and shows the transcript grouped into call/response conversations,
 * with every line editable.
 *
 * This file is a string.Template: the config placeholder below is replaced by
 * dq_transcribe.server.render_script, so never use a literal dollar sign here.
 * Clip and utterance field names (id, group_id, started_at, ...) are the
 * database column names returned by the clips API.
 */
"use strict";

const CONFIG = ${config};

// --- Page elements ----------------------------------------------------------

const capturePanel = document.getElementById("capture-panel");
const captureButton = document.getElementById("capture-button");
const levelCheckButton = document.getElementById("level-check-button");
const recLabel = document.getElementById("rec-label");
const meterBar = document.getElementById("meter-bar");
const meterThreshold = document.getElementById("meter-threshold");
const meterTarget = document.getElementById("meter-target");
const levelText = document.getElementById("level-text");
const statusText = document.getElementById("status");
const lastAudioText = document.getElementById("last-audio-text");
const queueText = document.getElementById("queue-text");
const clipsContainer = document.getElementById("clips");
const audioInputSelect = document.getElementById("audio-input");
const audioInputText = document.getElementById("audio-input-text");
const trashViewButton = document.getElementById("trash-view-button");
const viewTitle = document.getElementById("view-title");
const startInput = document.getElementById("start-dbfs");
const endInput = document.getElementById("end-dbfs");
const hangInput = document.getElementById("hang-seconds");
const startOutput = document.getElementById("start-dbfs-value");
const endOutput = document.getElementById("end-dbfs-value");
const hangOutput = document.getElementById("hang-seconds-value");

const CAPTURE_STATE_LABELS = {
  idle: "Not capturing",
  monitoring: "Level check · not recording",
  listening: "REC · listening",
  receiving: "REC · receiving audio",
};
const DEFAULT_INPUT_ID = "default";
const CONFIRM_TIMEOUT_SECONDS = 8;
// Labels for the second (refine) pass; values match the server's status names.
const REFINE_LABELS = {
  queued: "draft · refining soon",
  processing: "draft · refining…",
  done: "refined",
  failed: "draft (refine failed)",
  skipped: "no speech",
};
const LEVEL_CHECK_ON_TEXT = "Stop level check";
const LEVEL_CHECK_OFF_TEXT = "Check levels (no recording)";
const START_BUTTON_TEXT = "Start capturing";
const STOP_BUTTON_TEXT = "Stop capturing";
const BYTES_PER_SAMPLE = 2;
const WAV_HEADER_BYTES = 44;
const MILLISECONDS_PER_SECOND = 1000;

// --- Settings the user can adjust -------------------------------------------

const settings = {
  startDbfs: CONFIG.startDbfs,
  endDbfs: CONFIG.endDbfs,
  hangSeconds: CONFIG.hangSeconds,
};

/** Load saved settings (if any) into the settings object and the form fields. */
function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(CONFIG.settingsStorageKey) || "{}");
    for (const key of Object.keys(settings)) {
      if (typeof saved[key] === "number" && Number.isFinite(saved[key])) {
        settings[key] = saved[key];
      }
    }
  } catch (error) {
    // Storage unavailable or corrupted: keep the defaults.
  }
  for (const input of [startInput, endInput]) {
    configureSlider(input, CONFIG.levelSlider);
  }
  configureSlider(hangInput, CONFIG.hangSlider);
  startInput.value = settings.startDbfs;
  endInput.value = settings.endDbfs;
  hangInput.value = settings.hangSeconds;
  showSettingValues();
  positionThresholdMarker();
}

/** Apply minimum, maximum and step limits to a range slider. */
function configureSlider(input, limits) {
  input.min = limits.min;
  input.max = limits.max;
  input.step = limits.step;
}

/** Show the current value next to each slider. */
function showSettingValues() {
  startOutput.textContent = startInput.value + " dBFS";
  endOutput.textContent = endInput.value + " dBFS";
  hangOutput.textContent = hangInput.value + " s";
}

/** Read the form fields into the settings object and remember them. */
function saveSettings() {
  const fields = [
    ["startDbfs", startInput],
    ["endDbfs", endInput],
    ["hangSeconds", hangInput],
  ];
  for (const [key, input] of fields) {
    const value = parseFloat(input.value);
    if (Number.isFinite(value)) {
      settings[key] = value;
    }
  }
  showSettingValues();
  try {
    localStorage.setItem(CONFIG.settingsStorageKey, JSON.stringify(settings));
  } catch (error) {
    // Storage unavailable: settings still apply until the page is closed.
  }
  positionThresholdMarker();
}

// --- Small helpers ----------------------------------------------------------

/** Show a message under the meter. */
function setStatus(message) {
  statusText.textContent = message;
}

/** Switch the REC indicator between idle, monitoring, listening and receiving. */
function setCaptureState(state) {
  capturePanel.dataset.state = state;
  recLabel.textContent = CAPTURE_STATE_LABELS[state];
}

/** Resolve after the given number of milliseconds. */
const HTTP_CLIENT_ERROR_MIN = 400;
const HTTP_SERVER_ERROR_MIN = 500;

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

/** Root-mean-square amplitude of a block of samples (0 to 1). */
function rmsOf(samples) {
  let sumOfSquares = 0;
  for (let index = 0; index < samples.length; index += 1) {
    sumOfSquares += samples[index] * samples[index];
  }
  return Math.sqrt(sumOfSquares / samples.length);
}

/** Convert an amplitude (0 to 1) to dB relative to full scale. */
function toDbfs(amplitude) {
  return Math.max(CONFIG.dbfsFloor, 20 * Math.log10(Math.max(amplitude, 1e-9)));
}

/** Meter position (0 to 100 percent) for a level in dBFS. */
function meterPercent(dbfs) {
  const fraction = (dbfs - CONFIG.meterFloorDbfs) / (0 - CONFIG.meterFloorDbfs);
  return Math.min(100, Math.max(0, fraction * 100));
}

/** Move the black marker on the meter to the start threshold. */
function positionThresholdMarker() {
  meterThreshold.style.left = meterPercent(settings.startDbfs) + "%";
  const targetLeft = meterPercent(CONFIG.levelTargetLowDbfs);
  meterTarget.style.left = targetLeft + "%";
  meterTarget.style.width = meterPercent(CONFIG.levelTargetHighDbfs) - targetLeft + "%";
}

/** Update the meter and the level readout. */
function showLevel(dbfs, clipped) {
  if (clipped || dbfs > CONFIG.levelTooHotDbfs) {
    lastClippedAtMs = Date.now();
  }
  const tooLoud = lastClippedAtMs !== null
    && Date.now() - lastClippedAtMs < CONFIG.clippingWarningSeconds * MILLISECONDS_PER_SECOND;
  meterBar.style.width = meterPercent(dbfs) + "%";
  meterBar.classList.toggle("clipping", tooLoud);
  levelText.textContent = "Level " + Math.round(dbfs) + " dBFS"
    + (tooLoud ? " - TOO LOUD: turn the radio volume down (speech belongs in the green zone)" : "");
}

/** True if any sample reaches the clipping amplitude. */
function isClipped(samples) {
  let count = 0;
  for (let index = 0; index < samples.length; index += 1) {
    if (Math.abs(samples[index]) >= CONFIG.clippingAmplitude) {
      count += 1;
      if (count >= CONFIG.clippingMinSamples) {
        return true;
      }
    }
  }
  return false;
}

/** Join audio chunks into one Float32Array. */
function concatenateChunks(chunks) {
  const merged = new Float32Array(chunks.length * CONFIG.chunkSize);
  chunks.forEach((chunk, index) => merged.set(chunk, index * CONFIG.chunkSize));
  return merged;
}

/** Resample by averaging the input samples that fall into each output sample. */
// Filter weights for downsampling, cached by sample rates and fractional position.
const downsampleKernelCache = new Map();
const KERNEL_POSITION_STEPS = 1000; // fractional input positions are rounded to 1/1000 sample

/** Normalized Blackman-windowed sinc weights for one fractional input position. */
function downsampleKernel(inputRate, outputRate, fractionStep) {
  const key = inputRate + ":" + outputRate + ":" + fractionStep;
  let kernel = downsampleKernelCache.get(key);
  if (kernel !== undefined) {
    return kernel;
  }
  const cutoff = (CONFIG.downsampleCutoffFraction * outputRate) / 2 / inputRate; // cycles per input sample
  const halfWidth = CONFIG.downsampleHalfWidth;
  const fraction = fractionStep / KERNEL_POSITION_STEPS;
  kernel = new Float32Array(2 * halfWidth + 1);
  let total = 0;
  for (let tap = 0; tap < kernel.length; tap += 1) {
    const distance = tap - halfWidth - fraction; // input sample position minus the output position
    const sinc = distance === 0 ? 1 : Math.sin(2 * Math.PI * cutoff * distance) / (2 * Math.PI * cutoff * distance);
    const window = Math.abs(distance) >= halfWidth
      ? 0
      : 0.42 + 0.5 * Math.cos((Math.PI * distance) / halfWidth) + 0.08 * Math.cos((2 * Math.PI * distance) / halfWidth);
    kernel[tap] = sinc * window;
    total += kernel[tap];
  }
  for (let tap = 0; tap < kernel.length; tap += 1) {
    kernel[tap] /= total;
  }
  downsampleKernelCache.set(key, kernel);
  return kernel;
}

/**
 * Resample to a lower rate with a band-limiting (windowed-sinc) low-pass filter.
 * Removing everything above the cutoff first keeps high-frequency noise from
 * folding into the speech band, which simple averaging did.
 */
function downsample(samples, inputRate, outputRate) {
  if (inputRate === outputRate) {
    return samples;
  }
  const ratio = inputRate / outputRate;
  const halfWidth = CONFIG.downsampleHalfWidth;
  const outputLength = Math.floor(samples.length / ratio);
  const output = new Float32Array(outputLength);
  for (let outputIndex = 0; outputIndex < outputLength; outputIndex += 1) {
    const center = outputIndex * ratio;
    const base = Math.floor(center);
    const fractionStep = Math.round((center - base) * KERNEL_POSITION_STEPS);
    const kernel = downsampleKernel(inputRate, outputRate, fractionStep);
    let sum = 0;
    for (let tap = 0; tap < kernel.length; tap += 1) {
      const inputIndex = base - halfWidth + tap;
      if (inputIndex >= 0 && inputIndex < samples.length) {
        sum += samples[inputIndex] * kernel[tap];
      }
    }
    output[outputIndex] = sum;
  }
  return output;
}

/** Encode mono float samples (-1 to 1) as a 16-bit PCM WAV file. */
function encodeWav(samples, sampleRate) {
  const dataBytes = samples.length * BYTES_PER_SAMPLE;
  const buffer = new ArrayBuffer(WAV_HEADER_BYTES + dataBytes);
  const view = new DataView(buffer);
  const writeText = (offset, text) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
  writeText(0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * BYTES_PER_SAMPLE, true);
  view.setUint16(32, BYTES_PER_SAMPLE, true);
  view.setUint16(34, BYTES_PER_SAMPLE * 8, true);
  writeText(36, "data");
  view.setUint32(40, dataBytes, true);
  for (let index = 0; index < samples.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(WAV_HEADER_BYTES + index * BYTES_PER_SAMPLE, Math.round(clamped * 32767), true);
  }
  return buffer;
}

// --- Capture ----------------------------------------------------------------

let capturing = false; // cutting and uploading clips
let monitoring = false; // level check: the meter runs, nothing is recorded
let audioContext = null; // non-null while the microphone is open (monitoring or capturing)
let mediaStream = null;
let workletNode = null;
let wakeLock = null;
let lastChunkAtMs = 0;
let lastClippedAtMs = null; // when the input last clipped (too loud)
let lastAudioAtMs = null; // when sound above the start level was last heard
let watchdogTimer = null;

let prerollChunks = [];
let clipChunks = null; // null while waiting for audio; an array while a clip is in progress
let loudChunkCount = 0;
let clipSilentSeconds = 0;
let clipPeakDbfs = CONFIG.dbfsFloor;
let clipWasClipped = false; // true if any part of the current clip clipped
let clipStartedAtMs = 0;
let idleLevelDbfs = null; // slow running average of the level while nothing is being recorded

/** Handle one chunk of microphone audio from the worklet. */
function onChunk(samples) {
  if (audioContext === null) {
    return;
  }
  lastChunkAtMs = Date.now();
  const chunkSeconds = samples.length / audioContext.sampleRate;
  const level = toDbfs(rmsOf(samples));
  const clipped = isClipped(samples);
  showLevel(level, clipped);
  if (!capturing) {
    return; // level check only: show the meter, record nothing
  }
  if (level >= settings.startDbfs) {
    lastAudioAtMs = lastChunkAtMs;
  }
  if (clipChunks === null) {
    handleWaitingChunk(samples, level, chunkSeconds);
  } else {
    handleClipChunk(samples, level, chunkSeconds);
  }
  // Mark the clip in progress (if any) as clipped; this chunk may have just started it.
  if (clipped && clipChunks !== null) {
    clipWasClipped = true;
  }
}

/** While waiting: keep a short pre-roll and start a clip when sound appears. */
function handleWaitingChunk(samples, level, chunkSeconds) {
  prerollChunks.push(samples);
  const maxPrerollChunks = Math.ceil(CONFIG.prerollSeconds / chunkSeconds) + CONFIG.startChunks;
  while (prerollChunks.length > maxPrerollChunks) {
    prerollChunks.shift();
  }
  if (level >= settings.startDbfs) {
    loudChunkCount += 1;
  } else {
    loudChunkCount = 0;
    idleLevelDbfs = idleLevelDbfs === null ? level : 0.95 * idleLevelDbfs + 0.05 * level;
  }
  if (loudChunkCount >= CONFIG.startChunks) {
    beginClip(chunkSeconds);
  }
}

/** Start a clip, beginning with the pre-roll so the first syllable is not cut off. */
function beginClip(chunkSeconds) {
  clipChunks = prerollChunks;
  prerollChunks = [];
  clipSilentSeconds = 0;
  clipPeakDbfs = CONFIG.dbfsFloor;
  clipWasClipped = false;
  loudChunkCount = 0;
  clipStartedAtMs = Date.now() - clipChunks.length * chunkSeconds * MILLISECONDS_PER_SECOND;
  refreshControls();
  setStatus("Receiving audio...");
}

/** During a clip: keep the audio and end the clip after enough quiet. */
function handleClipChunk(samples, level, chunkSeconds) {
  clipChunks.push(samples);
  clipPeakDbfs = Math.max(clipPeakDbfs, level);
  clipSilentSeconds = level < settings.endDbfs ? clipSilentSeconds + chunkSeconds : 0;
  const clipSeconds = clipChunks.length * chunkSeconds;
  if (clipSilentSeconds >= settings.hangSeconds || clipSeconds >= CONFIG.maxClipSeconds) {
    finishClip(chunkSeconds);
  }
}

/** Finish the current clip: trim the quiet tail, encode it as WAV, and queue the upload. */
function finishClip(chunkSeconds) {
  const trimChunks = Math.floor((clipSilentSeconds - CONFIG.trailSeconds) / chunkSeconds);
  if (trimChunks > 0) {
    clipChunks.splice(clipChunks.length - trimChunks, trimChunks);
  }
  const chunks = clipChunks;
  const peakDbfs = clipPeakDbfs;
  const wasClipped = clipWasClipped;
  const startedAtMs = clipStartedAtMs;
  const sourceRate = audioContext.sampleRate;

  clipChunks = null;
  clipSilentSeconds = 0;
  loudChunkCount = 0;
  refreshControls();

  const durationSeconds = (chunks.length * CONFIG.chunkSize) / sourceRate;
  if (durationSeconds < CONFIG.minClipSeconds) {
    setStatus("Ignored a very short burst of sound.");
    return;
  }

  const resampled = downsample(concatenateChunks(chunks), sourceRate, CONFIG.targetSampleRate);
  const info = {};
  info[CONFIG.infoKeyStartedAt] = new Date(startedAtMs).toISOString();
  info[CONFIG.infoKeyEndedAt] = new Date(startedAtMs + durationSeconds * MILLISECONDS_PER_SECOND).toISOString();
  info.sourceSampleRate = sourceRate;
  info.peakDbfs = Math.round(peakDbfs * 10) / 10;
  info.clipped = wasClipped;
  const inputTrack = mediaStream && mediaStream.getAudioTracks()[0];
  info.inputLabel = inputTrack ? inputTrack.label : "";
  info.idleLevelDbfs = idleLevelDbfs === null ? null : Math.round(idleLevelDbfs * 10) / 10;
  info.startDbfs = settings.startDbfs;
  info.endDbfs = settings.endDbfs;
  info.hangSeconds = settings.hangSeconds;
  info.prerollSeconds = CONFIG.prerollSeconds;
  info.trailSeconds = CONFIG.trailSeconds;
  enqueueUpload(encodeWav(resampled, CONFIG.targetSampleRate), info);
  setStatus("Captured a " + durationSeconds.toFixed(1) + " second clip.");
}

/** Show when sound was last heard, so a long silence can be told apart from a dead microphone. */
function showLastAudio() {
  if (lastAudioAtMs === null) {
    lastAudioText.textContent = "Last audio received: none yet";
    return;
  }
  const agoSeconds = Math.round((Date.now() - lastAudioAtMs) / MILLISECONDS_PER_SECOND);
  lastAudioText.textContent = "Last audio received: " + formatTime(new Date(lastAudioAtMs)) + " (" + agoSeconds + " s ago)";
}

/**
 * Check periodically that audio is still flowing; resume a suspended audio
 * context and warn if the microphone stopped delivering sound.
 */
function checkCaptureHealth() {
  showLastAudio();
  if (audioContext === null) {
    return;
  }
  if (audioContext.state !== "running") {
    audioContext.resume().catch(() => {});
  }
  const trackEnded = mediaStream !== null && mediaStream.getAudioTracks().every((track) => track.readyState === "ended");
  const stalledSeconds = (Date.now() - lastChunkAtMs) / MILLISECONDS_PER_SECOND;
  if (trackEnded) {
    setStatus("WARNING: the audio input was disconnected. Choose the input again, or tap Stop and Start.");
  } else if (stalledSeconds >= CONFIG.stallSeconds) {
    setStatus("WARNING: the audio pipeline stalled for " + Math.round(stalledSeconds) + " s (not just silence). Keep this tab open and the screen on.");
  }
}

/** Ask the browser to keep the screen on, which keeps capture running. */
async function acquireWakeLock() {
  try {
    if ("wakeLock" in navigator) {
      wakeLock = await navigator.wakeLock.request("screen");
      wakeLock.addEventListener("release", () => {
        if (capturing && document.visibilityState === "visible") {
          acquireWakeLock();
        }
      });
    }
  } catch (error) {
    // Not supported or denied: capture still works while the screen stays on.
  }
}

/** Release the screen wake lock. */
async function releaseWakeLock() {
  try {
    if (wakeLock !== null) {
      await wakeLock.release();
    }
  } catch (error) {
    // Already released.
  }
  wakeLock = null;
}

/** Stop the microphone and close the audio graph (used by both level check and capture). */
async function closeAudio() {
  if (watchdogTimer !== null) {
    clearInterval(watchdogTimer);
    watchdogTimer = null;
  }
  if (workletNode !== null) {
    workletNode.port.onmessage = null;
    workletNode.disconnect();
    workletNode = null;
  }
  if (mediaStream !== null) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
  if (audioContext !== null) {
    const closingContext = audioContext;
    audioContext = null;
    await closingContext.close();
  }
  meterBar.style.width = "0";
  levelText.textContent = "";
  audioInputText.textContent = "";
}

/** Open the chosen audio input and start the audio graph, if not already open. */
async function openAudio() {
  if (audioContext !== null) {
    return;
  }
  mediaStream = await openAudioInput(resolveChoice(loadAudioInputChoice(), await listAudioInputs()));
  showInputInUse();
  populateAudioInputs(); // device names become available once the mic is allowed
  const context = new AudioContext();
  await context.audioWorklet.addModule(CONFIG.workletRoute);
  await context.resume();
  const source = context.createMediaStreamSource(mediaStream);
  workletNode = new AudioWorkletNode(context, CONFIG.processorName);
  workletNode.port.onmessage = (event) => onChunk(event.data);
  source.connect(workletNode);
  workletNode.connect(context.destination); // the worklet outputs silence
  audioContext = context;
  lastChunkAtMs = Date.now();
  watchdogTimer = setInterval(checkCaptureHealth, CONFIG.watchdogIntervalSeconds * MILLISECONDS_PER_SECOND);
}

/** Show the right state on the REC light and buttons. */
function refreshControls() {
  if (capturing) {
    setCaptureState(clipChunks === null ? "listening" : "receiving");
  } else {
    setCaptureState(monitoring ? "monitoring" : "idle");
  }
  captureButton.textContent = capturing ? STOP_BUTTON_TEXT : START_BUTTON_TEXT;
  captureButton.classList.toggle("active", capturing);
  levelCheckButton.textContent = monitoring ? LEVEL_CHECK_ON_TEXT : LEVEL_CHECK_OFF_TEXT;
  levelCheckButton.classList.toggle("active", monitoring);
  levelCheckButton.disabled = capturing; // while capturing, the meter is always live
}

/** Turn the level check (live meter, no recording) on or off. */
async function toggleLevelCheck() {
  levelCheckButton.disabled = true;
  try {
    if (monitoring) {
      monitoring = false;
      if (!capturing) {
        await closeAudio();
      }
      setStatus("");
    } else {
      await openAudio();
      monitoring = true;
      setStatus("Level check on. Nothing is being recorded.");
    }
  } catch (error) {
    monitoring = false;
    await closeAudio();
    setStatus("Could not open the audio input: " + error.message);
  }
  refreshControls();
}

/** Begin listening to the microphone. */
async function startCapturing() {
  captureButton.disabled = true;
  try {
    await openAudio(); // reuses the open input if the level check is on
    prerollChunks = [];
    clipChunks = null;
    loudChunkCount = 0;
    capturing = true;
    await acquireWakeLock();
    setStatus("Capturing. Waiting for audio...");
  } catch (error) {
    capturing = false;
    monitoring = false;
    await closeAudio();
    setStatus("Could not start capturing: " + error.message);
  } finally {
    captureButton.disabled = false;
    refreshControls();
  }
}

/** Stop listening, keeping any clip that is in progress. */
async function stopCapturing() {
  captureButton.disabled = true;
  if (clipChunks !== null) {
    finishClip(CONFIG.chunkSize / audioContext.sampleRate);
  }
  capturing = false;
  await releaseWakeLock();
  if (!monitoring) {
    await closeAudio();
  }
  setStatus(monitoring ? "Stopped recording. Level check still on." : "Stopped.");
  captureButton.disabled = false;
  refreshControls();
}

levelCheckButton.addEventListener("click", toggleLevelCheck);
captureButton.addEventListener("click", () => {
  if (capturing) {
    stopCapturing();
  } else {
    startCapturing();
  }
});

document.addEventListener("visibilitychange", () => {
  if (capturing && document.visibilityState === "visible") {
    acquireWakeLock();
  }
});

// --- Audio input choice -----------------------------------------------------

/**
 * The saved audio input as {id, label}, or the default input. The label is kept
 * because browsers may give a device a new id later (after a reload or replug).
 */
function loadAudioInputChoice() {
  try {
    const saved = JSON.parse(localStorage.getItem(CONFIG.audioInputStorageKey) || "null");
    if (saved && typeof saved.id === "string") {
      return { id: saved.id, label: typeof saved.label === "string" ? saved.label : "" };
    }
  } catch (error) {
    // Storage unavailable or an older format: use the default input.
  }
  return { id: DEFAULT_INPUT_ID, label: "" };
}

/** Remember the chosen audio input. */
function saveAudioInputChoice(id, label) {
  try {
    localStorage.setItem(CONFIG.audioInputStorageKey, JSON.stringify({ id: id, label: label }));
  } catch (error) {
    // Storage unavailable: the choice applies until the page is closed.
  }
}

/** List the audio inputs the browser can see (not counting the "default" alias). */
async function listAudioInputs() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((device) => device.kind === "audioinput" && device.deviceId !== DEFAULT_INPUT_ID);
  } catch (error) {
    return [];
  }
}

/** Find the current device id for a saved choice: by id first, then by name. */
function resolveChoice(choice, inputs) {
  if (choice.id === DEFAULT_INPUT_ID) {
    return DEFAULT_INPUT_ID;
  }
  const byId = inputs.find((device) => device.deviceId === choice.id);
  if (byId) {
    return byId.deviceId;
  }
  const byLabel = choice.label && inputs.find((device) => device.label === choice.label);
  return byLabel ? byLabel.deviceId : choice.id;
}

/** Build the getUserMedia audio settings for a device id. */
function audioConstraints(deviceId) {
  const constraints = {
    echoCancellation: CONFIG.echoCancellation,
    noiseSuppression: CONFIG.noiseSuppression,
    autoGainControl: CONFIG.autoGainControl,
  };
  if (deviceId && deviceId !== DEFAULT_INPUT_ID) {
    constraints.deviceId = { exact: deviceId };
  }
  return { audio: constraints };
}

/** Open the chosen input; if it is gone (unplugged), fall back to the default input. */
async function openAudioInput(deviceId) {
  try {
    return await navigator.mediaDevices.getUserMedia(audioConstraints(deviceId));
  } catch (error) {
    const inputMissing = error.name === "OverconstrainedError" || error.name === "NotFoundError";
    if (deviceId === DEFAULT_INPUT_ID || !inputMissing) {
      throw error;
    }
    setStatus("The chosen audio input was not found; using the default input instead.");
    return navigator.mediaDevices.getUserMedia(audioConstraints(DEFAULT_INPUT_ID));
  }
}

/** Show which input the browser actually opened. */
function showInputInUse() {
  const track = mediaStream && mediaStream.getAudioTracks()[0];
  audioInputText.textContent = track ? "Recording from: " + (track.label || "default input") : "";
}

/** Fill the audio input list with the inputs the browser can see. */
async function populateAudioInputs() {
  const inputs = await listAudioInputs();
  const chosen = resolveChoice(loadAudioInputChoice(), inputs);
  const options = [new Option("Default input (let Android choose)", DEFAULT_INPUT_ID)];
  inputs.forEach((device, index) => {
    options.push(new Option(device.label || "Audio input " + (index + 1), device.deviceId));
  });
  audioInputSelect.replaceChildren(...options);
  const chosenStillPresent = options.some((option) => option.value === chosen);
  audioInputSelect.value = chosenStillPresent ? chosen : DEFAULT_INPUT_ID;
  if (inputs.length > 0 && inputs.every((device) => !device.label)) {
    audioInputText.textContent = "Tap Check levels once to allow the microphone; then input names appear here.";
  }
}

/** Switch inputs; if capturing, restart capture on the new input. */
async function onAudioInputChange() {
  const selected = audioInputSelect.options[audioInputSelect.selectedIndex];
  const label = audioInputSelect.value === DEFAULT_INPUT_ID ? "" : selected.text;
  saveAudioInputChoice(audioInputSelect.value, label);
  if (audioContext === null) {
    return;
  }
  // Reopen the input that is running (level check and/or capture) on the new device.
  const wasCapturing = capturing;
  if (wasCapturing) {
    await stopCapturing();
  }
  await closeAudio();
  try {
    await openAudio();
  } catch (error) {
    monitoring = false;
    setStatus("Could not open the audio input: " + error.message);
  }
  if (wasCapturing) {
    await startCapturing();
  }
  refreshControls();
}

// --- Uploading --------------------------------------------------------------

const uploadQueue = [];
let uploading = false;

/** Show how many clips are waiting to be sent. */
function showQueue() {
  queueText.textContent = uploadQueue.length > 0 ? uploadQueue.length + " clip(s) waiting to upload" : "";
}

/** Add a clip to the upload queue and start sending. */
function enqueueUpload(wavBuffer, info) {
  uploadQueue.push({ wavBuffer: wavBuffer, info: info, attempts: 0 });
  showQueue();
  pumpUploads();
}

/** Send one clip to the server. */
async function uploadClip(item) {
  const headers = { "Content-Type": CONFIG.wavMediaType };
  headers[CONFIG.captureInfoHeader] = JSON.stringify(item.info);
  const response = await fetch(CONFIG.clipsRoute, {
    method: "POST",
    headers: headers,
    body: new Blob([item.wavBuffer], { type: CONFIG.wavMediaType }),
  });
  if (!response.ok) {
    const error = new Error("server answered " + response.status);
    error.permanent = response.status >= HTTP_CLIENT_ERROR_MIN && response.status < HTTP_SERVER_ERROR_MIN;
    throw error;
  }
}

/** Send queued clips one at a time, retrying a few times if the server is unreachable. */
async function pumpUploads() {
  if (uploading) {
    return;
  }
  uploading = true;
  while (uploadQueue.length > 0) {
    const item = uploadQueue[0];
    try {
      await uploadClip(item);
      uploadQueue.shift();
      refreshClips();
    } catch (error) {
      item.attempts += 1;
      if (error.permanent) {
        // The server rejected this clip itself; retrying cannot help.
        uploadQueue.shift();
        setStatus("A clip was rejected and dropped: " + error.message);
      } else {
        // Server unreachable or failing: keep the clip and keep trying, so no audio is lost.
        setStatus("Upload failing (" + error.message + "); will keep retrying.");
        await sleep(CONFIG.uploadRetrySeconds * MILLISECONDS_PER_SECOND);
      }
    }
    showQueue();
  }
  uploading = false;
}

// --- Transcript view --------------------------------------------------------

/** Create an element with optional class and text. */
function makeElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

/** Format a Date as a local clock time with seconds. */
function formatTime(date) {
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit", hour12: CONFIG.hour12 });
}

/** When a clip began (falls back to its upload time). */
function clipStartDate(clip) {
  return new Date(clip.started_at || clip.created_at);
}

/** When a clip ended (falls back to its start plus its duration). */
function clipEndDate(clip) {
  if (clip.ended_at) {
    return new Date(clip.ended_at);
  }
  return new Date(clipStartDate(clip).getTime() + (clip.duration_seconds || 0) * MILLISECONDS_PER_SECOND);
}

/** Save an edited utterance to the server. */
async function saveUtterance(utterance, textarea) {
  const body = {};
  body[CONFIG.textKey] = textarea.value;
  try {
    const response = await fetch(CONFIG.utterancesRoute + "/" + utterance.id, {
      method: "POST",
      headers: { "Content-Type": CONFIG.jsonMediaType },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error("server answered " + response.status);
    }
    textarea.classList.add("saved");
    setTimeout(() => textarea.classList.remove("saved"), 1500);
  } catch (error) {
    setStatus("Could not save an edit: " + error.message);
  }
}

/** Send a finished or failed clip back through transcription. */
async function reprocessClip(clip) {
  const edited = clip.utterances.some((utterance) => utterance.edited_at);
  if (edited && !window.confirm("Reprocess this clip? Your edits to it will be replaced.")) {
    return;
  }
  try {
    await fetch(CONFIG.clipsRoute + "/" + clip.id + CONFIG.reprocessSuffix, { method: "POST" });
  } catch (error) {
    setStatus("Could not reprocess: " + error.message);
  }
  refreshClips();
}

/** Create a button with a click handler. */
function makeButton(className, text, onClick) {
  const button = makeElement("button", className, text);
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}

// A trash or delete waiting for confirmation: {clipId, kind}. Only one at a time.
let pendingConfirm = null;
let pendingConfirmTimer = null;

const CONFIRM_KINDS = {
  trash: {
    question: (clip) => "Move clip #" + clip.id + " to the trash?",
    confirmText: "Move to trash",
    suffix: () => CONFIG.trashSuffix,
    done: (clip) => "Moved clip #" + clip.id + " to the trash. Restore it from Trash.",
  },
  delete: {
    question: (clip) => "Delete clip #" + clip.id + " forever? This cannot be undone.",
    confirmText: "Delete forever",
    suffix: () => CONFIG.deleteSuffix,
    done: (clip) => "Deleted clip #" + clip.id + " permanently.",
  },
};

/** Ask for confirmation of a trash or delete (shown in the clip's row). */
function askToConfirm(clip, kind) {
  clearTimeout(pendingConfirmTimer);
  pendingConfirm = { clipId: clip.id, kind: kind };
  pendingConfirmTimer = setTimeout(cancelConfirm, CONFIRM_TIMEOUT_SECONDS * MILLISECONDS_PER_SECOND);
  redrawLastClips();
}

/** Drop the pending confirmation without doing anything. */
function cancelConfirm() {
  clearTimeout(pendingConfirmTimer);
  pendingConfirm = null;
  redrawLastClips();
}

/** The confirmation bar for a clip, or null if none is pending for it. */
function buildConfirmBar(clip) {
  if (pendingConfirm === null || pendingConfirm.clipId !== clip.id) {
    return null;
  }
  const kind = CONFIRM_KINDS[pendingConfirm.kind];
  const bar = makeElement("div", "confirm-bar");
  bar.append(makeElement("span", "", kind.question(clip)));
  bar.append(makeButton("", "Cancel", cancelConfirm));
  bar.append(makeButton("danger", kind.confirmText, () => {
    clearTimeout(pendingConfirmTimer);
    pendingConfirm = null;
    clipAction(clip, kind.suffix(), kind.done(clip));
  }));
  return bar;
}

/** Run a clip action (trash, restore, delete) and refresh the list. */
async function clipAction(clip, suffix, doneMessage) {
  try {
    const response = await fetch(CONFIG.clipsRoute + "/" + clip.id + suffix, { method: "POST" });
    if (!response.ok) {
      throw new Error("server answered " + response.status);
    }
    setStatus(doneMessage);
  } catch (error) {
    setStatus("Could not update clip #" + clip.id + ": " + error.message);
  }
  refreshClips();
}

/** Switch between the transcript and the trash bin. */
function toggleTrashView() {
  showingTrash = !showingTrash;
  trashViewButton.textContent = showingTrash ? "Back to transcript" : "\u{1F5D1} Trash";
  viewTitle.textContent = showingTrash ? "Trash" : "Transcript";
  clipsContainer.replaceChildren();
  lastClipsSignature = "";
  pendingConfirm = null;
  refreshClips();
}

/** Build the row for one clip: details, audio player, and editable lines. */
function buildClipRow(clip) {
  const row = makeElement("div", "clip");
  const meta = makeElement("div", "clip-meta");
  meta.append(makeElement("span", "", "#" + clip.id + " · " + formatTime(clipStartDate(clip))));
  if (clip.duration_seconds) {
    meta.append(makeElement("span", "", clip.duration_seconds.toFixed(1) + " s"));
  }
  const statusLabels = { queued: "waiting", processing: "transcribing", done: "done", failed: "failed" };
  meta.append(makeElement("span", "badge " + clip.status, statusLabels[clip.status] || clip.status));
  if (clip.status === "done" && clip.refine_status) {
    meta.append(makeElement("span", "badge refine-" + clip.refine_status, REFINE_LABELS[clip.refine_status] || clip.refine_status));
  }

  const audio = document.createElement("audio");
  audio.controls = true;
  audio.preload = "none";
  audio.src = CONFIG.clipsRoute + "/" + clip.id + CONFIG.audioSuffix;
  meta.append(audio);

  if (showingTrash) {
    meta.append(makeButton("", "Restore", () => clipAction(clip, CONFIG.restoreSuffix, "Restored clip #" + clip.id + ".")));
    meta.append(makeButton("trash", "Delete forever", () => askToConfirm(clip, "delete")));
  } else {
    if (clip.status === "done" || clip.status === "failed") {
      meta.append(makeButton("", "Reprocess", () => reprocessClip(clip)));
    }
    const trashButton = makeButton("trash", "\u{1F5D1}", () => askToConfirm(clip, "trash"));
    trashButton.title = "Move to trash";
    trashButton.setAttribute("aria-label", "Move clip " + clip.id + " to trash");
    meta.append(trashButton);
  }
  row.append(meta);
  const confirmBar = buildConfirmBar(clip);
  if (confirmBar !== null) {
    row.append(confirmBar);
  }

  if (clip.status === "failed") {
    row.append(makeElement("p", "note error", clip.error_message || "Transcription failed."));
  } else if (clip.status === "done" && clip.utterances.length === 0) {
    row.append(makeElement("p", "note", "No speech detected."));
  } else if (clip.status === "queued" || clip.status === "processing") {
    row.append(makeElement("p", "note", "Waiting to be transcribed..."));
  }

  for (const utterance of clip.utterances) {
    const textarea = makeElement("textarea", "utterance-text");
    textarea.value = utterance.text;
    textarea.placeholder = "(no speech)";
    textarea.rows = Math.max(1, Math.ceil(utterance.text.length / 55));
    textarea.addEventListener("change", () => saveUtterance(utterance, textarea));
    row.append(textarea);
    // A hand-edited line keeps the edit; show the refined text beside it for comparison.
    if (utterance.edited_at && utterance.refined_text && utterance.refined_text !== utterance.text) {
      row.append(makeElement("p", "note", "Refined pass heard: " + utterance.refined_text));
    }
  }
  return row;
}

/** Build the card for one call/response group of clips. */
function buildGroupCard(groupClips) {
  const card = makeElement("section", "group");
  const first = groupClips[0];
  const last = groupClips[groupClips.length - 1];
  const header = makeElement("div", "group-header", formatTime(clipStartDate(first)) + " – " + formatTime(clipEndDate(last)));
  header.append(makeElement("span", "", " · " + groupClips.length + " clip" + (groupClips.length === 1 ? "" : "s")));
  card.append(header);
  groupClips.forEach((clip) => card.append(buildClipRow(clip)));
  return card;
}

/** Redraw the transcript, newest conversation first. */
function renderClips(clips) {
  const active = document.activeElement;
  if (active && active.classList && active.classList.contains("utterance-text")) {
    return false; // do not disturb a line that is being edited
  }
  const playing = Array.from(clipsContainer.querySelectorAll("audio")).some((audio) => !audio.paused);
  if (playing) {
    return false; // do not stop a clip that is playing; the next poll redraws
  }
  lastClips = clips;
  const groups = new Map();
  for (const clip of clips) {
    if (!groups.has(clip.group_id)) {
      groups.set(clip.group_id, []);
    }
    groups.get(clip.group_id).push(clip);
  }
  const newestFirst = Array.from(groups.values()).sort((a, b) => b[0].group_id - a[0].group_id);
  const cards = newestFirst.map((groupClips) => {
    groupClips.sort((a, b) => clipStartDate(a) - clipStartDate(b) || a.id - b.id);
    return buildGroupCard(groupClips);
  });
  if (cards.length === 0) {
    const emptyText = showingTrash ? "The trash is empty." : "Nothing captured yet. Tap Start capturing.";
    cards.push(makeElement("p", "note", emptyText));
  }
  clipsContainer.replaceChildren(...cards);
  return true;
}

let showingTrash = false;
let lastClips = []; // the clips last drawn, for redrawing after a local change
let lastClipsSignature = "";

/** Redraw the last fetched clips (after a local change such as a confirmation). */
function redrawLastClips() {
  renderClips(lastClips);
}

/** Fetch the latest clips and redraw. */
async function refreshClips() {
  try {
    const url = showingTrash ? CONFIG.clipsRoute + "?" + CONFIG.viewQueryKey + "=" + CONFIG.viewTrash : CONFIG.clipsRoute;
    const response = await fetch(url);
    const text = await response.text();
    if (text === lastClipsSignature) {
      return; // nothing changed: keep the page (and any playing audio) as it is
    }
    const data = JSON.parse(text);
    const rendered = renderClips(data[CONFIG.clipsKey]);
    if (rendered) {
      lastClipsSignature = text;
    }
  } catch (error) {
    // Server busy or restarting: the next poll tries again.
  }
}

// --- Start up ---------------------------------------------------------------

[startInput, endInput, hangInput].forEach((input) => input.addEventListener("input", saveSettings));
trashViewButton.addEventListener("click", toggleTrashView);
audioInputSelect.addEventListener("change", onAudioInputChange);
if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
  navigator.mediaDevices.addEventListener("devicechange", populateAudioInputs);
}
loadSettings();
populateAudioInputs();
refreshControls();
refreshClips();
setInterval(refreshClips, CONFIG.pollSeconds * MILLISECONDS_PER_SECOND);
