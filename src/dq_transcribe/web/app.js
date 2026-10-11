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
const recLabel = document.getElementById("rec-label");
const meterBar = document.getElementById("meter-bar");
const meterThreshold = document.getElementById("meter-threshold");
const levelText = document.getElementById("level-text");
const statusText = document.getElementById("status");
const queueText = document.getElementById("queue-text");
const clipsContainer = document.getElementById("clips");
const startInput = document.getElementById("start-dbfs");
const endInput = document.getElementById("end-dbfs");
const hangInput = document.getElementById("hang-seconds");

const CAPTURE_STATE_LABELS = {
  idle: "Not capturing",
  listening: "REC · listening",
  receiving: "REC · receiving audio",
};
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
  startInput.value = settings.startDbfs;
  endInput.value = settings.endDbfs;
  hangInput.value = settings.hangSeconds;
  positionThresholdMarker();
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

/** Switch the REC indicator and button between idle, listening and receiving. */
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
}

/** Update the meter and the level readout. */
function showLevel(dbfs) {
  meterBar.style.width = meterPercent(dbfs) + "%";
  levelText.textContent = "Level " + Math.round(dbfs) + " dBFS";
}

/** Join audio chunks into one Float32Array. */
function concatenateChunks(chunks) {
  const merged = new Float32Array(chunks.length * CONFIG.chunkSize);
  chunks.forEach((chunk, index) => merged.set(chunk, index * CONFIG.chunkSize));
  return merged;
}

/** Resample by averaging the input samples that fall into each output sample. */
function downsample(samples, inputRate, outputRate) {
  if (inputRate === outputRate) {
    return samples;
  }
  const ratio = inputRate / outputRate;
  const outputLength = Math.floor(samples.length / ratio);
  const output = new Float32Array(outputLength);
  for (let outputIndex = 0; outputIndex < outputLength; outputIndex += 1) {
    const first = Math.floor(outputIndex * ratio);
    const last = Math.min(samples.length, Math.max(first + 1, Math.floor((outputIndex + 1) * ratio)));
    let sum = 0;
    for (let inputIndex = first; inputIndex < last; inputIndex += 1) {
      sum += samples[inputIndex];
    }
    output[outputIndex] = sum / (last - first);
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

let capturing = false;
let audioContext = null;
let mediaStream = null;
let workletNode = null;
let wakeLock = null;
let lastChunkAtMs = 0;
let watchdogTimer = null;

let prerollChunks = [];
let clipChunks = null; // null while waiting for audio; an array while a clip is in progress
let loudChunkCount = 0;
let clipSilentSeconds = 0;
let clipPeakDbfs = CONFIG.dbfsFloor;
let clipStartedAtMs = 0;
let idleLevelDbfs = null; // slow running average of the level while nothing is being recorded

/** Handle one chunk of microphone audio from the worklet. */
function onChunk(samples) {
  if (!capturing) {
    return;
  }
  lastChunkAtMs = Date.now();
  const chunkSeconds = samples.length / audioContext.sampleRate;
  const level = toDbfs(rmsOf(samples));
  showLevel(level);
  if (clipChunks === null) {
    handleWaitingChunk(samples, level, chunkSeconds);
  } else {
    handleClipChunk(samples, level, chunkSeconds);
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
  loudChunkCount = 0;
  clipStartedAtMs = Date.now() - clipChunks.length * chunkSeconds * MILLISECONDS_PER_SECOND;
  setCaptureState("receiving");
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
  const startedAtMs = clipStartedAtMs;
  const sourceRate = audioContext.sampleRate;

  clipChunks = null;
  clipSilentSeconds = 0;
  loudChunkCount = 0;
  setCaptureState(capturing ? "listening" : "idle");

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
  info.idleLevelDbfs = idleLevelDbfs === null ? null : Math.round(idleLevelDbfs * 10) / 10;
  info.startDbfs = settings.startDbfs;
  info.endDbfs = settings.endDbfs;
  info.hangSeconds = settings.hangSeconds;
  info.prerollSeconds = CONFIG.prerollSeconds;
  info.trailSeconds = CONFIG.trailSeconds;
  enqueueUpload(encodeWav(resampled, CONFIG.targetSampleRate), info);
  setStatus("Captured a " + durationSeconds.toFixed(1) + " second clip.");
}

/**
 * Check periodically that audio is still flowing; resume a suspended audio
 * context and warn if the microphone stopped delivering sound.
 */
function checkCaptureHealth() {
  if (!capturing || audioContext === null) {
    return;
  }
  if (audioContext.state !== "running") {
    audioContext.resume().catch(() => {});
  }
  const trackEnded = mediaStream !== null && mediaStream.getAudioTracks().every((track) => track.readyState === "ended");
  const stalledSeconds = (Date.now() - lastChunkAtMs) / MILLISECONDS_PER_SECOND;
  if (trackEnded) {
    setStatus("WARNING: the microphone was disconnected. Tap Stop, then Start capturing again.");
  } else if (stalledSeconds >= CONFIG.stallSeconds) {
    setStatus("WARNING: no audio for " + Math.round(stalledSeconds) + " s. Keep this tab open and the screen on.");
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

/** Stop the microphone and close the audio graph. */
async function teardownAudio() {
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
    await audioContext.close();
    audioContext = null;
  }
  await releaseWakeLock();
}

/** Begin listening to the microphone. */
async function startCapturing() {
  captureButton.disabled = true;
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: CONFIG.echoCancellation,
        noiseSuppression: CONFIG.noiseSuppression,
        autoGainControl: CONFIG.autoGainControl,
      },
    });
    audioContext = new AudioContext();
    await audioContext.audioWorklet.addModule(CONFIG.workletRoute);
    await audioContext.resume();
    const source = audioContext.createMediaStreamSource(mediaStream);
    workletNode = new AudioWorkletNode(audioContext, CONFIG.processorName);
    workletNode.port.onmessage = (event) => onChunk(event.data);
    source.connect(workletNode);
    workletNode.connect(audioContext.destination); // the worklet outputs silence

    prerollChunks = [];
    clipChunks = null;
    loudChunkCount = 0;
    capturing = true;
    lastChunkAtMs = Date.now();
    watchdogTimer = setInterval(checkCaptureHealth, CONFIG.watchdogIntervalSeconds * MILLISECONDS_PER_SECOND);
    await acquireWakeLock();
    captureButton.textContent = STOP_BUTTON_TEXT;
    captureButton.classList.add("active");
    setCaptureState("listening");
    setStatus("Capturing. Waiting for audio...");
  } catch (error) {
    capturing = false;
    await teardownAudio();
    setCaptureState("idle");
    setStatus("Could not start capturing: " + error.message);
  } finally {
    captureButton.disabled = false;
  }
}

/** Stop listening, keeping any clip that is in progress. */
async function stopCapturing() {
  captureButton.disabled = true;
  if (clipChunks !== null) {
    finishClip(CONFIG.chunkSize / audioContext.sampleRate);
  }
  capturing = false;
  await teardownAudio();
  captureButton.textContent = START_BUTTON_TEXT;
  captureButton.classList.remove("active");
  setCaptureState("idle");
  meterBar.style.width = "0";
  levelText.textContent = "";
  setStatus("Stopped.");
  captureButton.disabled = false;
}

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
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
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

  const audio = document.createElement("audio");
  audio.controls = true;
  audio.preload = "none";
  audio.src = CONFIG.clipsRoute + "/" + clip.id + CONFIG.audioSuffix;
  meta.append(audio);

  if (clip.status === "done" || clip.status === "failed") {
    const button = makeElement("button", "", "Reprocess");
    button.type = "button";
    button.addEventListener("click", () => reprocessClip(clip));
    meta.append(button);
  }
  row.append(meta);

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
    textarea.rows = Math.max(1, Math.ceil(utterance.text.length / 55));
    textarea.addEventListener("change", () => saveUtterance(utterance, textarea));
    row.append(textarea);
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
    return; // do not disturb a line that is being edited
  }
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
    cards.push(makeElement("p", "note", "Nothing captured yet. Tap Start capturing."));
  }
  clipsContainer.replaceChildren(...cards);
}

/** Fetch the latest clips and redraw. */
async function refreshClips() {
  try {
    const response = await fetch(CONFIG.clipsRoute);
    const data = await response.json();
    renderClips(data[CONFIG.clipsKey]);
  } catch (error) {
    // Server busy or restarting: the next poll tries again.
  }
}

// --- Start up ---------------------------------------------------------------

[startInput, endInput, hangInput].forEach((input) => input.addEventListener("change", saveSettings));
loadSettings();
setCaptureState("idle");
refreshClips();
setInterval(refreshClips, CONFIG.pollSeconds * MILLISECONDS_PER_SECOND);
