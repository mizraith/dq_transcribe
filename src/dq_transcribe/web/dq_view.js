/**
 * DQ screens for dq_transcribe: detected calls on each conversation card, and
 * the DQ list with its tap-to-edit panel.
 *
 * Loaded after app.js and shares its globals (CONFIG, makeElement, makeButton,
 * setStatus, formatTime, ...). A DQ never copies audio: it lists evidence, time
 * ranges in existing clips, which play with a media-fragment URL ("#t=start,end").
 *
 * This file is a string.Template served by dq_transcribe.server.render_script,
 * so never use a literal dollar sign here.
 */
"use strict";

const DQ_FIELD_LABELS = {
  event: "Event", heat: "Heat", lane: "Lane", relay_leg: "Relay leg", swimmer: "Swimmer (or relay, e.g. PASA-A)",
  club: "Club", official: "Official", official_role: "Official role", chief_judge: "Chief Judge", referee: "Referee", notes: "Notes",
};
const DQ_NUMBER_FIELDS = ["event", "heat", "lane", "relay_leg"];
// Which roster roles to suggest for each people field of a DQ (null = everyone).
const ROSTER_SUGGESTIONS = {
  official: null,
  referee: ["Deck Referee", "Meet Referee"],
  chief_judge: ["Chief Judge"],
};
// How many likely codes to show as one-tap buttons under an infraction.
const MAX_CODE_CHIPS = 4;
const DQ_FILTER_ALL = "all";
const DQ_FILTER_STORAGE_KEY = "dq_transcribe.dqFilter";
const DQ_GROUP_STORAGE_KEY = "dq_transcribe.dqGroupByEvent";
const NOTIFIED_BY_STORAGE_KEY = "dq_transcribe.notifiedBy";
// Protest statuses get a filter button only once some DQ has them (fewer buttons on deck).
const DQ_STATUSES_SHOWN_WHEN_EMPTY = ["called", "incomplete", "pending_notification", "notified", "declined"];
const MINUTE_MS = 60 * 1000;
// Swipe a DQ left to reveal "Move to trash": how far it slides, and how far a finger must move first.
const SWIPE_OPEN_PX = 130;
const SWIPE_START_PX = 12;

let candidatesByGroup = new Map(); // group id -> detected calls not yet turned into DQs
let candidatesSignature = "";
let dqCodes = []; // current DQ slip codes, for the infraction picker
let expandedDqId = null; // the DQ whose edit panel is open
let dqsSignature = "";
let dqCount = 0;
let dqFilter = loadDqFilter(); // a status from CONFIG.dqStatusLabels, or DQ_FILTER_ALL
let dqGroupByEvent = loadSetting(DQ_GROUP_STORAGE_KEY, "false") === "true";
let flashDqId = null; // the DQ just changed, highlighted once when the list is redrawn
// State buttons in the editor, in order (labels say what tapping does when not current).
const DQ_STATE_BUTTONS = [
  { state: "called", label: "Called", current: "Called" },
  { state: "accepted", label: "Mark accepted", current: "\u2713 Accepted" },
  { state: "notified", label: "Mark notified", current: "\u2713 Notified" },
  { state: "declined", label: "Decline", current: "Declined" },
];
const rangePlayer = new Audio(); // plays one evidence range at a time

// --- Shared helpers --------------------------------------------------------------

/** POST JSON and return the parsed reply; throws with the server's message on failure. */
async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": CONFIG.jsonMediaType },
    body: JSON.stringify(body),
  });
  const reply = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(reply.error || "server answered " + response.status);
  }
  return reply;
}

/** Play part of a clip (no copy is made: the browser plays a time range of the clip's file). */
function playRange(clipId, startSeconds, endSeconds) {
  rangePlayer.src = CONFIG.clipsRoute + "/" + clipId + CONFIG.audioSuffix
    + "#t=" + startSeconds.toFixed(2) + "," + endSeconds.toFixed(2);
  rangePlayer.play().catch((error) => setStatus("Could not play: " + error.message));
}

/** "E 6 · H 4 · L 1" with "?" for anything missing. */
function eventHeatLane(item) {
  return "E " + (item.event || "?") + " · H " + (item.heat || "?") + " · L " + (item.lane || "?");
}

// --- Detected calls (on the transcript) ---------------------------------------------

/** Fetch the detected calls for the active meet. Returns true if they changed. */
async function loadCandidates() {
  try {
    const text = await (await fetch(CONFIG.candidatesRoute)).text();
    if (text === candidatesSignature) {
      return false;
    }
    candidatesSignature = text;
    candidatesByGroup = new Map();
    for (const candidate of JSON.parse(text)[CONFIG.candidatesKey]) {
      if (!candidatesByGroup.has(candidate.group_id)) {
        candidatesByGroup.set(candidate.group_id, []);
      }
      candidatesByGroup.get(candidate.group_id).push(candidate);
    }
    return true;
  } catch (error) {
    return false;
  }
}

/** The "Detected calls" section for a conversation card, or null if there are none. */
function buildCandidateSection(groupId) {
  const candidates = candidatesByGroup.get(groupId);
  if (!candidates || candidates.length === 0) {
    return null;
  }
  const section = makeElement("div", "candidates");
  section.append(makeElement("div", "candidates-title", "Detected calls"));
  for (const candidate of candidates) {
    const row = makeElement("div", "candidate");
    const summary = makeElement("div", "candidate-summary");
    summary.append(makeElement("strong", "", eventHeatLane(candidate)));
    summary.append(makeElement("span", "", " " + (candidate.infractions.map((description, index) =>
      description + codeHint(candidate.codes[index], candidate.code_options[index])).join("; ") || "infraction?")));
    if (candidate.event_label) {
      summary.append(makeElement("span", "muted", " · " + candidate.event_label));
    } else if (candidate.stroke) {
      summary.append(makeElement("span", "muted", " · " + candidate.stroke));
    }
    if (candidate.phases.length) {
      summary.append(makeElement("span", "muted", " · " + candidate.phases.join(", ")));
    }
    if (candidate.turn_number) {
      summary.append(makeElement("span", "muted", " · turn " + candidate.turn_number));
    }
    summary.append(makeElement("span", "badge " + (candidate.accepted ? "done" : "queued"), candidate.accepted ? "accepted" : "not yet accepted"));
    row.append(summary);
    if (candidate.flags.length) {
      row.append(makeElement("div", "candidate-flags", candidate.flags.join(" · ")));
    }
    const actions = makeElement("div", "candidate-actions");
    const firstCall = candidate.evidence[0];
    actions.append(makeButton("", "▶ Play", () => playRange(firstCall.clip_id, firstCall.start_seconds, firstCall.end_seconds)));
    actions.append(makeButton("primary", "Create DQ", () => createDqFromCandidate(candidate)));
    actions.append(makeButton("", "Dismiss", () => dismissCandidate(candidate)));
    row.append(actions);
    section.append(row);
  }
  return section;
}

/** " (3C)" when the code is known, " (1J or 3J?)" when it depends on the stroke. */
function codeHint(code, options) {
  if (code) {
    return " (" + code + ")";
  }
  return options && options.length ? " (" + options.join(" or ") + "?)" : "";
}

/** Turn a detected call into a DQ (one tap). */
async function createDqFromCandidate(candidate) {
  const body = {
    event: candidate.event, heat: candidate.heat, lane: candidate.lane, accepted: candidate.accepted,
    infractions: candidate.infractions.map((description, index) => ({
      description: description,
      code: candidate.codes[index] || null,
      code_options: (candidate.code_options[index] || []).length ? candidate.code_options[index] : candidate.suggested_codes,
      phases: candidate.phases,
    })),
    evidence: candidate.evidence,
  };
  body[CONFIG.candidateKeyKey] = candidate.key;
  try {
    const reply = await postJson(CONFIG.dqsRoute, body);
    notify("\u2713 Created DQ #" + reply.dq_id + " (" + eventHeatLane(candidate) + "). Open the DQs view to complete it.");
  } catch (error) {
    setStatus("Could not create the DQ: " + error.message);
  }
  forceRefresh();
}

/** Make DQs by hand from a transcript line, or from the words selected in it. */
async function createDqFromLine(utterance, textarea) {
  const selected = textarea.value.substring(textarea.selectionStart, textarea.selectionEnd).trim();
  const body = {};
  body[CONFIG.utteranceIdKey] = utterance.id;
  body[CONFIG.textKey] = selected || textarea.value;
  try {
    const reply = await postJson(CONFIG.dqFromUtteranceRoute, body);
    const count = reply[CONFIG.dqIdsKey].length;
    notify("\u2713 Made " + (count === 1 ? "a DQ" : count + " DQs") + " from " + (selected ? "the selected words" : "this line") + ". Open DQs to finish.");
  } catch (error) {
    notify("Could not make the DQ: " + error.message, "error");
  }
  forceRefresh();
}

/** Hide a detected call that is not a DQ. */
async function dismissCandidate(candidate) {
  const body = {};
  body[CONFIG.candidateKeyKey] = candidate.key;
  try {
    await postJson(CONFIG.dismissRoute, body);
    notify("Dismissed the detected call " + eventHeatLane(candidate) + ".");
  } catch (error) {
    setStatus("Could not dismiss: " + error.message);
  }
  forceRefresh();
}

// --- DQ list -------------------------------------------------------------------------

/** Load the DQ slip codes once (for the infraction picker). */
async function loadDqCodes() {
  if (dqCodes.length) {
    return;
  }
  try {
    dqCodes = (await (await fetch(CONFIG.codesRoute)).json())[CONFIG.codesKey];
  } catch (error) {
    dqCodes = [];
  }
}

/**
 * True while the user is typing in the DQ editor (so a refresh must not redraw it).
 * A tapped button keeps focus but is not typing, so it does not count.
 */
function editingDq() {
  const active = document.activeElement;
  return Boolean(active && active.closest && active.closest(".dq-editor") && active.matches("input, select, textarea"));
}

/** Fetch the DQs and redraw the list (unless nothing changed or the editor is in use). */
async function refreshDqView(force) {
  await loadDqCodes();
  try {
    const text = await (await fetch(CONFIG.dqsRoute)).text();
    if (currentView !== "dqs") {
      return; // the user switched views while this was loading
    }
    const dqs = JSON.parse(text)[CONFIG.dqsKey];
    dqCount = dqs.filter((dq) => dq.state !== CONFIG.dqStates.declined).length;
    updateViewButtons();
    if ((!force && text === dqsSignature) || editingDq()) {
      return;
    }
    dqsSignature = text;
    renderDqList(dqs);
  } catch (error) {
    // Server busy or restarting: the next poll tries again.
  }
}

/** A small setting remembered on this tablet (falls back to the default if storage is unavailable). */
function loadSetting(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : value;
  } catch (error) {
    return fallback;
  }
}

/** Remember a small setting on this tablet (silently skipped if storage is unavailable). */
function saveSetting(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    // Not remembered; it still applies now.
  }
}

/** The status filter remembered on this tablet (falls back to showing all). */
function loadDqFilter() {
  try {
    const saved = localStorage.getItem(DQ_FILTER_STORAGE_KEY);
    return saved && (saved === DQ_FILTER_ALL || saved in CONFIG.dqStatusLabels) ? saved : DQ_FILTER_ALL;
  } catch (error) {
    return DQ_FILTER_ALL;
  }
}

/** Show only DQs with one status (or all), and remember the choice. */
function setDqFilter(filter) {
  dqFilter = filter;
  try {
    localStorage.setItem(DQ_FILTER_STORAGE_KEY, filter);
  } catch (error) {
    // Not remembered; it still applies now.
  }
  expandedDqId = null;
  forceRefresh();
}

/** The filter buttons: All, then each status in workflow order, with counts. */
function buildDqFilterBar(dqs) {
  const bar = makeElement("div", "dq-filter");
  const addButton = (filter, label, count) => {
    const button = makeButton("dq-filter-button status-" + filter + (dqFilter === filter ? " on" : "") + (count ? "" : " empty"), "", () => setDqFilter(filter));
    button.append(document.createTextNode(label + " "), makeElement("span", "dq-filter-count", String(count)));
    button.setAttribute("aria-pressed", dqFilter === filter ? "true" : "false");
    bar.append(button);
  };
  addButton(DQ_FILTER_ALL, "All", dqs.length);
  for (const [status, label] of Object.entries(CONFIG.dqStatusLabels)) {
    const count = dqs.filter((dq) => dq.status === status).length;
    if (count || DQ_STATUSES_SHOWN_WHEN_EMPTY.includes(status) || dqFilter === status) {
      addButton(status, label, count);
    }
  }
  const group = makeButton("dq-group-toggle" + (dqGroupByEvent ? " on" : ""), (dqGroupByEvent ? "\u2713 " : "") + "Group by event", () => {
    dqGroupByEvent = !dqGroupByEvent;
    saveSetting(DQ_GROUP_STORAGE_KEY, String(dqGroupByEvent));
    forceRefresh();
  });
  group.setAttribute("aria-pressed", dqGroupByEvent ? "true" : "false");
  bar.append(group);
  return bar;
}

/** The person or channel that notified, remembered between events. */
function buildNotifiedByPicker() {
  const select = document.createElement("select");
  select.className = "notified-by";
  CONFIG.notifiedByOptions.forEach((option) => select.append(new Option(option, option)));
  select.value = loadSetting(NOTIFIED_BY_STORAGE_KEY, CONFIG.notifiedByOptions[0]);
  select.addEventListener("change", () => saveSetting(NOTIFIED_BY_STORAGE_KEY, select.value));
  return select;
}

/**
 * How far an event is: every DQ of the event that is not declined counts.
 * Returns {ready, waiting, called, incomplete, notified, total, label, kind}.
 */
function eventReadiness(eventDqs) {
  const live = eventDqs.filter((dq) => dq.state !== CONFIG.dqStates.declined);
  const count = (status) => live.filter((dq) => dq.status === status).length;
  const result = {
    ready: count("pending_notification"),
    called: count("called"),
    incomplete: count("incomplete"),
    notified: live.filter((dq) => CONFIG.statesAfterNotification.includes(dq.state)).length,
    total: live.length,
  };
  result.waiting = result.called + result.incomplete;
  if (result.total === 0) {
    result.kind = "declined";
    result.label = "All declined";
  } else if (result.notified === result.total) {
    result.kind = "done";
    result.label = "\u2713 All notified";
  } else if (result.waiting) {
    result.kind = "waiting";
    result.label = "Waiting on " + [result.called ? result.called + " called" : "", result.incomplete ? result.incomplete + " incomplete" : ""].filter(Boolean).join(", ");
  } else {
    result.kind = "ready";
    result.label = "Ready to notify (" + result.ready + ")";
  }
  return result;
}

/** The header of one event in the grouped list: readiness, Notify and Print. */
function buildEventHeader(event, eventDqs) {
  const header = makeElement("div", "event-header");
  const readiness = eventReadiness(eventDqs);
  const title = makeElement("div", "event-title");
  title.append(makeElement("strong", "", "Event " + (event || "?")));
  const label = eventDqs.find((dq) => dq.event_label);
  if (label) {
    title.append(makeElement("span", "dq-event-label", " " + label.event_label));
  }
  title.append(makeElement("span", "event-readiness " + readiness.kind, readiness.label));
  header.append(title);
  const actions = makeElement("div", "event-actions");
  if (readiness.ready && event) {
    const notifiedBy = buildNotifiedByPicker();
    actions.append(makeElement("span", "muted", "Notified by"), notifiedBy);
    if (readiness.waiting) {
      actions.append(makeButton("", "Notify the " + readiness.ready + " ready now", () => notifyEvent(event, notifiedBy.value, true)));
    } else {
      actions.append(makeButton("notify-event", "Notify event (" + readiness.ready + ")", () => notifyEvent(event, notifiedBy.value, false)));
    }
  }
  if (event && readiness.total) {
    const reprint = makeButton("event-reprint", "\ud83d\udda8", () => openSlips(CONFIG.eventQueryKey, event));
    reprint.title = "Reprint this event's slips (only when a coach asks)";
    reprint.setAttribute("aria-label", "Reprint event " + event + " slips");
    actions.append(reprint);
  }
  header.append(actions);
  return header;
}

/** Notify an event's DQs that are pending notification. */
async function notifyEvent(event, notifiedBy, includeNotReady) {
  const body = {};
  body[CONFIG.eventKey] = event;
  body[CONFIG.byKey] = notifiedBy;
  body[CONFIG.includeNotReadyKey] = includeNotReady;
  try {
    const reply = await postJson(CONFIG.notifyEventRoute, body);
    notify("\u2713 Event " + event + ": " + reply.notified.length + " DQ(s) notified (" + notifiedBy + ")");
  } catch (error) {
    notify("Could not notify event " + event + ": " + error.message, "error");
  }
  forceRefresh();
}

/** Draw the filter bar and the DQ list, sorted by event, heat and lane (the server sorts). */
function renderDqList(dqs) {
  const shown = dqFilter === DQ_FILTER_ALL ? dqs : dqs.filter((dq) => dq.status === dqFilter);
  const cards = [];
  if (dqGroupByEvent) {
    // One block per event (in event order); readiness counts all of the event's DQs, not just the filtered ones.
    const events = [...new Set(shown.map((dq) => dq.event || ""))];
    for (const event of events) {
      const block = makeElement("section", "event-group");
      block.append(buildEventHeader(event, dqs.filter((dq) => (dq.event || "") === event)));
      shown.filter((dq) => (dq.event || "") === event).forEach((dq) => block.append(buildDqCard(dq)));
      cards.push(block);
    }
  } else {
    shown.forEach((dq) => cards.push(buildDqCard(dq)));
  }
  if (dqs.length === 0) {
    cards.push(makeElement("p", "note", "No DQs yet for this meet. Create them from the detected calls in the transcript."));
  } else if (cards.length === 0) {
    cards.push(makeElement("p", "note", "No DQs are " + CONFIG.dqStatusLabels[dqFilter].toLowerCase() + ". Tap All to see every DQ."));
  }
  clipsContainer.replaceChildren(buildDqFilterBar(dqs), ...cards);
}

/** One DQ in the list: a summary row; tap to open the editor. */
function buildDqCard(dq) {
  const card = makeElement("section", "dq-card state-" + dq.state + " status-" + dq.status + (flashDqId === dq.id ? " flash" : ""));
  const summary = makeElement("button", "dq-summary");
  summary.type = "button";
  summary.append(makeElement("strong", "dq-ehl", eventHeatLane(dq)));
  if (dq.event_label) {
    summary.append(makeElement("span", "dq-event-label", " " + dq.event_label));
  }
  summary.append(makeElement("span", "", " " + (dq.infractions.map((item) => item.description).join("; ") || "no infraction yet")));
  summary.append(makeElement("span", "badge dq-status-badge status-" + dq.status, CONFIG.dqStatusLabels[dq.status] || dq.status));
  if (dq.missing.length && dq.state !== CONFIG.dqStates.declined) {
    summary.append(makeElement("span", "dq-missing", "missing: " + dq.missing.join(", ")));
  }
  if (dq.state === CONFIG.dqStates.notified) {
    const protestWindow = protestWindowText(dq);
    if (protestWindow && protestWindow.open) {
      summary.append(makeElement("span", "protest-countdown", protestWindow.text.replace("Protest window closes", "protest window:")));
    }
  }
  if (dq.swimmer || dq.club) {
    summary.append(makeElement("span", "muted", " · " + [dq.swimmer, dq.club].filter(Boolean).join(", ")));
  }
  // Chevron at the right: points right when closed, down when open.
  const expanded = expandedDqId === dq.id;
  const chevron = makeElement("span", "dq-chevron" + (expanded ? " open" : ""), "\u203A");
  chevron.setAttribute("aria-hidden", "true");
  summary.append(chevron);
  summary.setAttribute("aria-expanded", expanded ? "true" : "false");
  summary.title = expanded ? "Tap to close" : "Tap to review and edit";
  summary.addEventListener("click", () => {
    if (card.dataset.justSwiped) {
      return; // the finger was swiping, not tapping
    }
    if (card.classList.contains("swiped")) {
      card.classList.remove("swiped"); // a tap closes the revealed trash button
      return;
    }
    expandedDqId = expandedDqId === dq.id ? null : dq.id;
    forceRefresh();
  });
  // Swipe left on a closed DQ to reveal "Move to trash" (for mistakes such as a duplicate).
  const body = makeElement("div", "dq-card-body");
  body.append(summary);
  if (expandedDqId === dq.id) {
    body.append(buildDqEditor(dq));
  } else {
    const trashButton = makeButton("dq-swipe-trash", "\ud83d\uddd1 Move to trash", () => trashDq(dq));
    card.append(trashButton);
    enableSwipeToReveal(card, body, summary);
  }
  card.append(body);
  return card;
}

/** Let a finger slide ``body`` left (on ``handle``) to reveal the button behind it; vertical scrolling still works. */
function enableSwipeToReveal(card, body, handle) {
  let startX = null;
  let startY = 0;
  let offset = 0;
  let swiping = false;
  handle.addEventListener("pointerdown", (event) => {
    startX = event.clientX;
    startY = event.clientY;
    offset = 0;
    swiping = false;
  });
  handle.addEventListener("pointermove", (event) => {
    if (startX === null) {
      return;
    }
    const moveX = event.clientX - startX;
    const moveY = event.clientY - startY;
    if (!swiping && Math.abs(moveX) > SWIPE_START_PX && Math.abs(moveX) > Math.abs(moveY)) {
      swiping = true;
      handle.setPointerCapture(event.pointerId);
      body.style.transition = "none";
    }
    if (swiping) {
      const base = card.classList.contains("swiped") ? -SWIPE_OPEN_PX : 0;
      offset = Math.min(0, Math.max(-SWIPE_OPEN_PX, base + moveX));
      body.style.transform = "translateX(" + offset + "px)";
    }
  });
  const finish = () => {
    if (swiping) {
      card.classList.toggle("swiped", offset < -SWIPE_OPEN_PX / 2);
      body.style.transition = "";
      body.style.transform = "";
      card.dataset.justSwiped = "1";
      setTimeout(() => { delete card.dataset.justSwiped; }, 300);
    }
    startX = null;
    swiping = false;
  };
  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
}

/** Move a DQ to the trash (with Undo in the confirmation). */
async function trashDq(dq) {
  try {
    await postJson(CONFIG.dqsRoute + "/" + dq.id + CONFIG.dqTrashSuffix, {});
    notify("\ud83d\uddd1 DQ " + eventHeatLane(dq) + " moved to trash", "ok", "Undo", () => restoreDq(dq));
  } catch (error) {
    notify("Could not move it to the trash: " + error.message, "error");
  }
  if (expandedDqId === dq.id) {
    expandedDqId = null;
  }
  forceRefresh();
}

/** Bring a DQ back from the trash. */
async function restoreDq(dq) {
  try {
    await postJson(CONFIG.dqsRoute + "/" + dq.id + CONFIG.dqRestoreSuffix, {});
    notify("\u2713 DQ " + eventHeatLane(dq) + " restored");
  } catch (error) {
    notify("Could not restore it: " + error.message, "error");
  }
  forceRefresh();
}

/** A labeled text input for a DQ field (numbers get the number keypad and +/- buttons). */
function buildField(dq, name) {
  const wrapper = makeElement("label", "dq-field" + (CONFIG.dqRequiredFields.includes(name) && !dq[name] ? " missing" : ""));
  wrapper.append(makeElement("span", "", DQ_FIELD_LABELS[name]));
  let input;
  if (name === "official_role") {
    input = document.createElement("select");
    input.append(new Option("", ""));
    CONFIG.officialRoles.forEach((role) => input.append(new Option(role, role)));
    if (dq[name] && !CONFIG.officialRoles.includes(dq[name])) {
      input.append(new Option(dq[name], dq[name])); // a role saved under an older list
    }
  } else {
    input = document.createElement("input");
    input.type = "text";
    if (DQ_NUMBER_FIELDS.includes(name)) {
      input.inputMode = "numeric";
    }
  }
  input.value = dq[name] || "";
  input.dataset.field = name;
  if (name in ROSTER_SUGGESTIONS && activeMeet !== null) {
    // Suggest names from the meet's officials roster (typing any other name still works).
    const listId = "roster-" + name;
    const datalist = document.createElement("datalist");
    datalist.id = listId;
    const roles = ROSTER_SUGGESTIONS[name];
    activeMeet.officials
      .filter((official) => roles === null || roles.includes(official.role))
      .forEach((official) => datalist.append(new Option(official.role, official.name)));
    input.setAttribute("list", listId);
    wrapper.append(datalist);
  }
  if (DQ_NUMBER_FIELDS.includes(name)) {
    const row = makeElement("div", "stepper");
    const step = (delta) => {
      const value = parseInt(input.value, 10);
      input.value = String(Math.max(1, (Number.isFinite(value) ? value : 0) + delta));
    };
    row.append(makeButton("", "−", () => step(-1)), input, makeButton("", "+", () => step(1)));
    wrapper.append(row);
  } else {
    wrapper.append(input);
  }
  return wrapper;
}

/** Option label for a slip row, e.g. "3J · Breaststroke · Touch: One hand". */
function codeLabel(row, withSection) {
  return (row.code ? row.code + " · " : "") + (withSection ? row.section + " · " : "") + (row.group ? row.group + ": " : "") + row.description;
}

/**
 * The slip codes an infraction could be, likeliest first: the ones the server
 * found for it, or else those matching everything heard in the DQ's audio.
 */
function likelyCodes(infraction, dq) {
  if (infraction.code_options && infraction.code_options.length) {
    return infraction.code_options;
  }
  return (dq && dq.suggested_codes) || [];
}

/** The picker of DQ slip codes: the most likely codes first, then all codes by stroke. */
function buildCodePicker(selectedCode, likely) {
  const select = document.createElement("select");
  select.className = "code-picker";
  select.append(new Option("Pick from DQ slip (rev. " + CONFIG.slipRevision + ")…", ""));
  const likelyRows = likely.map((code) => dqCodes.find((row) => row.code === code)).filter(Boolean); // keep the server's order
  if (likelyRows.length) {
    const top = document.createElement("optgroup");
    top.label = "Most likely";
    likelyRows.forEach((row) => top.append(new Option(codeLabel(row, true), row.code)));
    select.append(top);
  }
  const sections = new Map();
  for (const row of dqCodes) {
    if (!sections.has(row.section)) {
      const group = document.createElement("optgroup");
      group.label = row.section;
      sections.set(row.section, group);
      select.append(group);
    }
    sections.get(row.section).append(new Option(codeLabel(row, false), row.code || row.description));
  }
  select.value = selectedCode || "";
  return select;
}

/** One editable infraction: description, slip code, phases and detail. */
function buildInfractionEditor(infraction, dq, onRemove) {
  const box = makeElement("div", "infraction");
  const description = document.createElement("input");
  description.type = "text";
  description.className = "infraction-description";
  description.value = infraction.description || "";
  description.placeholder = "Short description (required)";
  const likely = likelyCodes(infraction, dq);
  box.dataset.codeOptions = JSON.stringify(likely);
  const picker = buildCodePicker(infraction.code, likely);
  // The likeliest codes as one-tap buttons (the picker still lists every code).
  const chips = makeElement("div", "code-chips");
  const markChosenChip = () => chips.querySelectorAll(".code-chip").forEach((chip) => chip.classList.toggle("on", chip.dataset.code === picker.value));
  likely
    .map((code) => dqCodes.find((row) => row.code === code))
    .filter(Boolean)
    .slice(0, MAX_CODE_CHIPS)
    .forEach((row) => {
      const chip = makeButton("code-chip", "", () => {
        picker.value = row.code;
        picker.dispatchEvent(new Event("change"));
      });
      chip.append(
        makeElement("strong", "", row.code),
        makeElement("span", "chip-stroke", CONFIG.sectionAbbreviations[row.section] || row.section),
        document.createTextNode((row.group ? row.group + ": " : "") + row.description),
      );
      chip.dataset.code = row.code;
      chips.append(chip);
    });
  picker.addEventListener("change", () => {
    const row = dqCodes.find((item) => (item.code || item.description) === picker.value);
    if (row) {
      description.value = row.section + " - " + (row.group ? row.group + ": " : "") + row.description;
    }
    markChosenChip();
  });
  markChosenChip();
  const phases = makeElement("div", "phases");
  for (const phase of CONFIG.racePhases) {
    const toggle = makeButton("phase" + ((infraction.phases || []).includes(phase) ? " on" : ""), phase, () => toggle.classList.toggle("on"));
    toggle.dataset.phase = phase;
    phases.append(toggle);
  }
  const detail = document.createElement("input");
  detail.type = "text";
  detail.className = "infraction-detail";
  detail.value = infraction.detail || "";
  detail.placeholder = "Detail (turn #, stroke, relay swimmer…)";
  box.append(description, picker);
  if (chips.childElementCount) {
    box.append(chips);
  }
  box.append(phases, detail, makeButton("", "Remove", onRemove));
  return box;
}

/** Read the infraction editors back into data. */
function readInfractions(container) {
  return Array.from(container.querySelectorAll(".infraction"))
    .map((box) => ({
      description: box.querySelector(".infraction-description").value.trim(),
      code: (() => {
        const value = box.querySelector(".code-picker").value;
        return dqCodes.some((row) => row.code === value) ? value : null;
      })(),
      phases: Array.from(box.querySelectorAll(".phase.on")).map((toggle) => toggle.dataset.phase),
      detail: box.querySelector(".infraction-detail").value.trim(),
      code_options: JSON.parse(box.dataset.codeOptions || "[]"),
    }))
    .filter((item) => item.description);
}

/** The edit panel for one DQ. */
function buildDqEditor(dq) {
  const editor = makeElement("div", "dq-editor");
  const fields = makeElement("div", "dq-fields");
  Object.keys(DQ_FIELD_LABELS).forEach((name) => fields.append(buildField(dq, name)));
  editor.append(fields);
  if (dq.lookup_differs) {
    // A newer meet file (or a changed lane) names someone else: the admin decides.
    const warning = makeElement("div", "lookup-warning");
    warning.append(makeElement("span", "", "\u26a0 The meet file has " + dq.lookup.swimmer + (dq.lookup.club ? " (" + dq.lookup.club + ")" : "") + " in this event, heat and lane. "));
    warning.append(makeButton("", "Use " + dq.lookup.swimmer, () => {
      editor.querySelector("[data-field=swimmer]").value = dq.lookup.swimmer;
      editor.querySelector("[data-field=club]").value = dq.lookup.club || "";
      warning.remove();
    }));
    editor.append(warning);
  }
  fillRoleFromRoster(editor);

  editor.append(makeElement("div", "dq-subtitle", "Infractions"));
  const infractions = makeElement("div", "infractions");
  const addInfraction = (infraction) => {
    const box = buildInfractionEditor(infraction, dq, () => box.remove());
    infractions.append(box);
  };
  (dq.infractions.length ? dq.infractions : [{}]).forEach(addInfraction);
  editor.append(infractions, makeButton("", "+ Add infraction", () => addInfraction({})));

  editor.append(makeElement("div", "dq-subtitle", "Heard in"));
  for (const item of dq.evidence) {
    const line = makeElement("div", "evidence");
    line.append(makeButton("", "▶", () => playRange(item.clip_id, item.start_seconds, item.end_seconds)));
    line.append(makeElement("span", "", "clip #" + item.clip_id + ", " + item.start_seconds.toFixed(1) + "–" + item.end_seconds.toFixed(1) + " s · " + item.role));
    editor.append(line);
  }
  if (!dq.evidence.length) {
    editor.append(makeElement("p", "note", "No audio linked."));
  }

  // Status: one button per state; the current one is filled in.
  const status = makeElement("div", "dq-status");
  status.append(makeElement("span", "dq-status-label", "Status:"));
  for (const item of DQ_STATE_BUTTONS) {
    const isCurrent = dq.state === CONFIG.dqStates[item.state];
    const button = makeButton("state-button " + item.state + (isCurrent ? " current" : ""), isCurrent ? item.current : item.label, () => {
      if (!isCurrent) {
        changeDqState(dq, CONFIG.dqStates[item.state], editor);
      }
    });
    button.setAttribute("aria-pressed", isCurrent ? "true" : "false");
    status.append(button);
  }
  editor.append(status);
  if (CONFIG.statesAfterNotification.includes(dq.state)) {
    editor.append(buildProtestPanel(dq));
  }
  const history = dq.history.map((item) => formatTime(new Date(item.at)) + " " + item.to_state + (item.by_name ? " (" + item.by_name + ")" : "")).join(" → ");
  editor.append(makeElement("p", "note", "History: " + history));

  // Save comes last and stands out: it is the action that ends an edit.
  const actions = makeElement("div", "dq-save-bar");
  actions.append(makeButton("dq-trash-link", "\ud83d\uddd1 Move to trash", () => trashDq(dq)));
  actions.append(makeButton("dq-print", "\ud83d\udda8 Print slip", () => openSlips(CONFIG.idsQueryKey, dq.id)));
  actions.append(makeButton("dq-save", "Save changes", () => saveDq(dq, editor)));
  editor.append(actions);
  return editor;
}

/** When an official is picked from the roster, fill in their role if it is empty. */
function fillRoleFromRoster(editor) {
  const official = editor.querySelector("[data-field=official]");
  const role = editor.querySelector("[data-field=official_role]");
  official.addEventListener("change", () => {
    const entry = activeMeet && activeMeet.officials.find((item) => item.name === official.value.trim());
    if (entry) {
      role.value = entry.role;
    }
  });
}

/** "closes 5:42 PM (12 min left)" or "closed at 5:42 PM", from the DQ's protest deadline. */
function protestWindowText(dq) {
  if (!dq.protest_deadline) {
    return null;
  }
  const deadline = new Date(dq.protest_deadline);
  const minutesLeft = Math.ceil((deadline - Date.now()) / MINUTE_MS);
  return minutesLeft > 0
    ? { open: true, text: "Protest window closes " + formatTime(deadline) + " (" + minutesLeft + " min left)" }
    : { open: false, text: "Protest window closed at " + formatTime(deadline) };
}

/** "17:05" for a time input, now. */
function currentClockValue() {
  const now = new Date();
  return String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
}

/** Today's local date with a time input's value, as ISO text without a zone (the server reads it as local time). */
function localIsoFromClock(clockValue) {
  const now = new Date();
  const date = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
  return date + "T" + clockValue + ":00";
}

/**
 * Protest controls for a notified DQ: record a protest (with the time it came in),
 * then the ruling (Upheld / Overturned, and who ruled). A late protest or one past
 * the cycle limit asks for a reason instead of being refused.
 */
function buildProtestPanel(dq) {
  const panel = makeElement("div", "protest-panel");
  const protestWindow = protestWindowText(dq);
  const count = dq.protest_count || 0;
  if (dq.state === CONFIG.dqStates.protested) {
    panel.append(makeElement("div", "protest-line", "Protested at " + formatTime(new Date(dq.protested_at)) + " (protest " + count + " of " + CONFIG.maxProtestCycles + "). Ruling:"));
    const row = makeElement("div", "protest-row");
    const ruledBy = document.createElement("select");
    CONFIG.protestRuledByOptions.forEach((option) => ruledBy.append(new Option(option, option)));
    ruledBy.value = CONFIG.protestRuledByOptions[Math.min(count, CONFIG.protestRuledByOptions.length) - 1] || CONFIG.protestRuledByOptions[0];
    row.append(makeElement("span", "muted", "by"), ruledBy);
    row.append(makeButton("ruling upheld", "Upheld (DQ stands)", () => changeDqState(dq, CONFIG.dqStates.upheld, null, ruledBy.value)));
    row.append(makeButton("ruling overturned", "Overturned", () => changeDqState(dq, CONFIG.dqStates.overturned, null, ruledBy.value)));
    panel.append(row);
    return panel;
  }
  if (protestWindow) {
    panel.append(makeElement("div", "protest-window " + (protestWindow.open ? "open" : "closed"), protestWindow.text));
  }
  const row = makeElement("div", "protest-row");
  const time = document.createElement("input");
  time.type = "time";
  time.value = currentClockValue();
  const needsReason = count >= CONFIG.maxProtestCycles || (protestWindow && !protestWindow.open);
  const reason = document.createElement("input");
  reason.type = "text";
  reason.className = "protest-reason";
  reason.placeholder = count >= CONFIG.maxProtestCycles ? "Reason to accept another protest (required)" : "Reason to accept a late protest (required)";
  row.append(makeElement("span", "", count ? "Another protest at" : "Coach protested at"), time);
  if (needsReason) {
    row.append(reason);
  }
  row.append(makeButton("protest-button", "Record protest", () => {
    if (needsReason && !reason.value.trim()) {
      notify("Add a reason first (the protest is late or past the limit).", "error");
      reason.focus();
      return;
    }
    changeDqState(dq, CONFIG.dqStates.protested, null, null, reason.value.trim(), localIsoFromClock(time.value));
  }));
  panel.append(row);
  return panel;
}

/** Open printable slips in a new tab (``key`` is the ids or event query key). */
function openSlips(key, value) {
  window.open(CONFIG.slipsRoute + "?" + key + "=" + encodeURIComponent(value), "_blank");
}

/** The editor's fields and infractions as a request body. */
function readDqEditor(editor) {
  const body = {};
  editor.querySelectorAll("[data-field]").forEach((input) => {
    body[input.dataset.field] = input.value;
  });
  body.infractions = readInfractions(editor);
  return body;
}

/** Redraw the DQ list now, highlighting the DQ that just changed. */
function redrawAfterChange(dq) {
  if (document.activeElement) {
    document.activeElement.blur();
  }
  flashDqId = dq.id;
  forceRefresh();
  setTimeout(() => { flashDqId = null; }, 2000);
}

/** Save the editor's fields and infractions. */
async function saveDq(dq, editor) {
  const body = readDqEditor(editor);
  try {
    await postJson(CONFIG.dqsRoute + "/" + dq.id, body);
    notify("\u2713 Saved DQ " + eventHeatLane(body));
  } catch (error) {
    notify("Could not save: " + error.message, "error");
  }
  redrawAfterChange(dq);
}

/**
 * Change a DQ's state (recorded in its history). Edits in the open editor are
 * saved first, so tapping "Mark accepted" after editing does not lose them.
 */
async function changeDqState(dq, state, editor, by, note, at) {
  const body = {};
  body[CONFIG.stateKey] = state;
  if (state === CONFIG.dqStates.notified && !by) {
    by = loadSetting(NOTIFIED_BY_STORAGE_KEY, CONFIG.notifiedByOptions[0]);
  }
  if (by) {
    body[CONFIG.byKey] = by;
  }
  if (note) {
    body[CONFIG.noteKey] = note;
  }
  if (at) {
    body[CONFIG.atKey] = at;
  }
  const label = eventHeatLane(dq);
  try {
    if (editor) {
      await postJson(CONFIG.dqsRoute + "/" + dq.id, readDqEditor(editor));
    }
    await postJson(CONFIG.dqsRoute + "/" + dq.id + CONFIG.dqStateSuffix, body);
    notify((state === CONFIG.dqStates.declined ? "" : "\u2713 ") + "DQ " + label + " " + state);
  } catch (error) {
    notify("Could not change the status: " + error.message, "error");
  }
  redrawAfterChange(dq);
}
