/**
 * Meet setup view for dq_transcribe: the meet's name and first day, and its
 * officials roster, in the main area (a meet can have 25+ officials).
 *
 * Loaded after app.js and shares its globals (CONFIG, activeMeet, makeElement,
 * makeButton, setStatus, loadMeets, setView, ...).
 *
 * Quick entry for a long roster: type a name and pick a role; the official is
 * added at once (the role stays selected for the next name). The table is grouped by
 * role in the order of CONFIG.rosterRoles; names stay editable in place.
 *
 * This file is a string.Template served by dq_transcribe.server.render_script,
 * so never use a literal dollar sign here.
 */
"use strict";

let meetDraft = null; // {name, start_date, officials: [{name, role}]} being edited
let meetDraftDirty = false;
let quickAddRole = null; // the role the quick-add row keeps between names

/** Open the meet setup view for the active meet. */
function openMeetSetup() {
  if (activeMeet === null) {
    setStatus("Pick or create a meet first.");
    return;
  }
  meetDraft = {
    name: activeMeet.name,
    start_date: activeMeet.start_date,
    officials: activeMeet.officials.map((official) => ({ name: official.name, role: official.role })),
  };
  meetDraftDirty = false;
  setView("meet");
}

/** Draw the meet setup view from the draft. */
function renderMeetView() {
  if (meetDraft === null) {
    clipsContainer.replaceChildren(makeElement("p", "note", "Pick or create a meet first."));
    return;
  }
  const page = makeElement("div", "meet-setup");

  const details = makeElement("section", "meet-card");
  details.append(makeElement("h3", "", "Meet"));
  const nameLabel = makeElement("label", "meet-field");
  nameLabel.append(makeElement("span", "", "Meet name"));
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.maxLength = 100;
  nameInput.value = meetDraft.name;
  nameInput.addEventListener("input", () => { meetDraft.name = nameInput.value; markMeetDirty(); });
  nameLabel.append(nameInput);
  const dateLabel = makeElement("label", "meet-field");
  dateLabel.append(makeElement("span", "", "First day"));
  const dateInput = document.createElement("input");
  dateInput.type = "date";
  dateInput.value = meetDraft.start_date;
  dateInput.addEventListener("input", () => { meetDraft.start_date = dateInput.value; markMeetDirty(); });
  dateLabel.append(dateInput);
  details.append(nameLabel, dateLabel);
  page.append(details);

  const roster = makeElement("section", "meet-card");
  roster.append(makeElement("h3", "", "Officials (" + meetDraft.officials.length + ")"));
  roster.append(makeElement("p", "note", rosterCounts()));
  roster.append(buildQuickAdd());
  roster.append(buildRosterTable());
  page.append(roster);

  const actions = makeElement("div", "meet-actions");
  actions.append(makeButton("primary", "Save meet", saveMeetDraft));
  actions.append(makeButton("", meetDraftDirty ? "Discard changes" : "Back to transcript", () => {
    meetDraft = null;
    setView("transcript");
  }));
  if (meetDraftDirty) {
    actions.append(makeElement("span", "unsaved", "Unsaved changes"));
  }
  page.append(actions);
  clipsContainer.replaceChildren(page);
}

/** Note that the draft changed (shows "Unsaved changes" on the next draw). */
function markMeetDirty() {
  if (!meetDraftDirty) {
    meetDraftDirty = true;
    const actions = clipsContainer.querySelector(".meet-actions");
    if (actions && !actions.querySelector(".unsaved")) {
      actions.append(makeElement("span", "unsaved", "Unsaved changes"));
    }
  }
}

/** "Stroke & Turn Judge: 20 · Starter: 2 · ..." */
function rosterCounts() {
  const counts = CONFIG.rosterRoles
    .map((role) => [role, meetDraft.officials.filter((official) => official.role === role).length])
    .filter(([, count]) => count > 0)
    .map(([role, count]) => role + ": " + count);
  return counts.length ? counts.join(" · ") : "No officials yet. Add them below; the role stays selected for the next name.";
}

/** A role picker. */
function buildRolePicker(selected) {
  const select = document.createElement("select");
  CONFIG.rosterRoles.forEach((role) => select.append(new Option(role, role)));
  select.value = selected || CONFIG.rosterRoles[0];
  return select;
}

/**
 * The quick-add row: name + role. An official is added as soon as both are
 * given: picking a role after typing a name adds them, and so does finishing
 * the name (Enter, or tapping elsewhere) while a role is selected. The role
 * stays selected for the next name, and the name box is ready for it.
 */
function buildQuickAdd() {
  const row = makeElement("div", "quick-add");
  const name = document.createElement("input");
  name.type = "text";
  name.placeholder = "Official's name (added when a role is picked)";
  name.enterKeyHint = "next";
  const role = buildRolePicker(quickAddRole);
  let added = false; // this row is redrawn after each add; never add the same name twice
  const add = (refocus) => {
    const value = name.value.trim();
    if (!value || added) {
      return;
    }
    added = true;
    meetDraft.officials.push({ name: value, role: role.value });
    quickAddRole = role.value;
    meetDraftDirty = true;
    renderMeetView();
    setStatus("Added " + value + " (" + role.value + ").");
    if (refocus) {
      const next = clipsContainer.querySelector(".quick-add input");
      if (next) {
        next.focus(); // ready for the next name
      }
    }
  };
  role.addEventListener("change", () => {
    quickAddRole = role.value;
    add(true);
  });
  name.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      add(true);
    }
  });
  // Finishing the name by tapping away also adds it, unless the tap was on the
  // role picker (then picking the role adds it).
  name.addEventListener("blur", (event) => {
    if (event.relatedTarget !== role) {
      add(false);
    }
  });
  // Picking the role that was already selected fires no "change": add on leaving the picker too.
  role.addEventListener("blur", () => add(false));
  row.append(name, role);
  return row;
}

/** The roster, grouped by role, with editable names and roles. */
function buildRosterTable() {
  const table = makeElement("div", "roster-table");
  for (const role of CONFIG.rosterRoles) {
    const members = meetDraft.officials.filter((official) => official.role === role);
    if (!members.length) {
      continue;
    }
    table.append(makeElement("div", "roster-role", role + " (" + members.length + ")"));
    members
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }))
      .forEach((official) => table.append(buildRosterLine(official)));
  }
  return table;
}

/** One official: name (editable), role (changeable), remove. */
function buildRosterLine(official) {
  const line = makeElement("div", "roster-line");
  const name = document.createElement("input");
  name.type = "text";
  name.value = official.name;
  name.addEventListener("input", () => { official.name = name.value; markMeetDirty(); });
  const role = buildRolePicker(official.role);
  role.addEventListener("change", () => {
    official.role = role.value;
    meetDraftDirty = true;
    renderMeetView(); // regroup under the new role
  });
  const remove = makeButton("", "✕", () => {
    meetDraft.officials = meetDraft.officials.filter((item) => item !== official);
    meetDraftDirty = true;
    renderMeetView();
  });
  remove.title = "Remove " + official.name;
  line.append(name, role, remove);
  return line;
}

/** Save the meet's name, first day and roster. */
async function saveMeetDraft() {
  if (activeMeet === null || meetDraft === null) {
    return;
  }
  const body = {};
  body[CONFIG.meetNameKey] = meetDraft.name.trim();
  body[CONFIG.meetStartDateKey] = meetDraft.start_date;
  body[CONFIG.officialsKey] = meetDraft.officials.filter((official) => official.name.trim());
  try {
    const response = await fetch(CONFIG.meetsRoute + "/" + activeMeet.id, {
      method: "POST",
      headers: { "Content-Type": CONFIG.jsonMediaType },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error((await response.json()).error || "server answered " + response.status);
    }
    meetDraftDirty = false;
    setStatus("Saved meet " + body[CONFIG.meetNameKey] + " (" + body[CONFIG.officialsKey].length + " officials).");
  } catch (error) {
    setStatus("Could not save the meet: " + error.message);
  }
  await loadMeets();
  renderMeetView();
}
