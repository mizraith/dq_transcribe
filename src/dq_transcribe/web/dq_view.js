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

let candidatesByGroup = new Map(); // group id -> detected calls not yet turned into DQs
let candidatesSignature = "";
let dqCodes = []; // current DQ slip codes, for the infraction picker
let expandedDqId = null; // the DQ whose edit panel is open
let dqsSignature = "";
let dqCount = 0;
let dqFilter = loadDqFilter(); // a status from CONFIG.dqStatusLabels, or DQ_FILTER_ALL
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
    addButton(status, label, dqs.filter((dq) => dq.status === status).length);
  }
  return bar;
}

/** Draw the filter bar and the DQ list, sorted by event, heat and lane (the server sorts). */
function renderDqList(dqs) {
  const shown = dqFilter === DQ_FILTER_ALL ? dqs : dqs.filter((dq) => dq.status === dqFilter);
  const cards = shown.map((dq) => buildDqCard(dq));
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
    expandedDqId = expandedDqId === dq.id ? null : dq.id;
    forceRefresh();
  });
  card.append(summary);
  if (expandedDqId === dq.id) {
    card.append(buildDqEditor(dq));
  }
  return card;
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
  const history = dq.history.map((item) => formatTime(new Date(item.at)) + " " + item.to_state + (item.by_name ? " (" + item.by_name + ")" : "")).join(" → ");
  editor.append(makeElement("p", "note", "History: " + history));

  // Save comes last and stands out: it is the action that ends an edit.
  const actions = makeElement("div", "dq-save-bar");
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
async function changeDqState(dq, state, editor) {
  const body = {};
  body[CONFIG.stateKey] = state;
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
