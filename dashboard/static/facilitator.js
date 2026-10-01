"use strict";

import {api, clearNotice, connect, formatElapsed, notify, setStatus, token} from "/static/common.js";

const notice = document.querySelector("#notice");
const tokenInput = document.querySelector("#token-input");
let pendingMfa = null;

function renderMsel(items) {
  const body = document.querySelector("#msel-body");
  body.replaceChildren();
  for (const item of items) {
    const row = document.createElement("tr");
    const trigger = item.trigger_seconds === null ? item.trigger : formatElapsed(item.trigger_seconds);
    row.innerHTML = `<td><strong></strong></td><td><span></span><small class="muted"></small></td><td></td><td><b></b></td><td><div class="row-actions"></div></td>`;
    row.querySelector("strong").textContent = item.item_id;
    row.querySelector("span").textContent = item.title;
    row.querySelector("small").textContent = `${item.kind} · ${item.delivery}`;
    row.children[2].textContent = trigger;
    const status = row.querySelector("b");
    status.textContent = item.status;
    status.className = `status-text ${item.status}`;
    const actions = row.querySelector(".row-actions");
    if (["pending", "ready"].includes(item.status)) {
      for (const [label, command, className] of [["Deliver", "deliver", "small"], ["Skip", "skip", "secondary small"]]) {
        if (command === "deliver" && item.trigger === "checkpoint" && item.phase === "cloud") continue;
        const button = document.createElement("button");
        button.textContent = label;
        button.className = className;
        button.dataset.command = command;
        button.dataset.item = item.item_id;
        actions.append(button);
      }
    }
    body.append(row);
  }
}

function renderChecks(evaluation, selector = "#checks") {
  const container = document.querySelector(selector);
  container.replaceChildren();
  for (const [name, passed] of Object.entries(evaluation.checks)) {
    const item = document.createElement("div");
    item.className = "check";
    const label = document.createElement("span");
    label.textContent = name.replaceAll("_", " ");
    const result = document.createElement("b");
    result.className = passed ? "pass" : "miss";
    result.textContent = passed ? "PASS" : "MISS";
    item.append(label, result);
    container.append(item);
  }
}

function renderEvents(events) {
  const container = document.querySelector("#event-log");
  container.replaceChildren();
  for (const event of events.slice(-80).reverse()) {
    const row = document.createElement("div");
    row.className = "event";
    const sequence = document.createElement("code");
    sequence.textContent = `#${event.sequence}`;
    const detail = document.createElement("div");
    const type = document.createElement("strong");
    type.textContent = event.event_type;
    const message = document.createElement("p");
    message.textContent = event.message;
    detail.append(type, message);
    row.append(sequence, detail);
    container.append(row);
  }
}

function renderSubmissions(submissions) {
  const container = document.querySelector("#submissions");
  container.replaceChildren();
  if (!submissions.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No submissions.";
    container.append(empty);
    return;
  }
  for (const submission of submissions) {
    const card = document.createElement("article");
    card.className = "inject";
    const title = document.createElement("strong");
    title.textContent = `${submission.submission_type} · ${submission.actor_id}`;
    const result = document.createElement("p");
    result.textContent = submission.result.status === "submitted" ? "Recorded for checkpoint evaluation" : submission.result.passed ? "Passed" : submission.result.reason;
    card.append(title, result);
    container.append(card);
  }
}

async function refresh() {
  if (!token()) return;
  try {
    const state = await api("/api/facilitator/state");
    setStatus(document.querySelector("#run-state"), state.controller.state);
    document.querySelector("#elapsed").textContent = formatElapsed(state.controller.elapsed_seconds);
    document.querySelector("#event-count").textContent = state.events.length;
    document.querySelector("#run-id").textContent = state.controller.run_id;
    renderMsel(state.msel);
    renderChecks(state.dp2_preview);
    document.querySelector("#cloud-verifier").hidden = !state.cloud.enabled;
    document.querySelector("#resolve-dp3").hidden = !state.cloud.enabled;
    document.querySelector("#resolve-dp3").disabled = state.controller.items.DP3?.status !== "ready";
    if (state.cloud.enabled) renderChecks(state.cloud.dp3_preview, "#cloud-checks");
    renderEvents(state.events);
    renderSubmissions(state.submissions);
    const profiles = state.profile_initialization;
    document.querySelector("#profile-summary").textContent = `${profiles.profile_count} reviewed profiles · Catalog SHA256 ${profiles.catalog_sha256.slice(0, 12)}… · ${profiles.bindings.identity.display_name} / ${profiles.bindings.helpdesk.display_name}`;
    pendingMfa = state.scheduled_mfa.pending;
    const latest = state.scheduled_mfa.history.at(-1);
    document.querySelector("#mfa-summary").textContent = pendingMfa
      ? `${pendingMfa.msel_id} · ${pendingMfa.expires_in_seconds}s left · ${state.controller.state}`
      : latest ? `${latest.msel_id} · ${latest.outcome} · ${latest.reason}` : "No request delivered yet.";
    for (const id of ["#mfa-deny", "#mfa-approve"]) {
      document.querySelector(id).disabled = !pendingMfa || state.controller.state !== "running";
    }
  } catch (error) {
    notify(notice, error.message, "error");
  }
}

async function command(path, body) {
  clearNotice(notice);
  try {
    await api(path, {method: "POST", body: body === undefined ? undefined : JSON.stringify(body)});
    notify(notice, "Control action completed and recorded.");
    await refresh();
  } catch (error) {
    notify(notice, error.message, "error");
  }
}

document.querySelector("#connect").addEventListener("click", () => {
  clearNotice(notice);
  try { connect(tokenInput, refresh); } catch (error) { notify(notice, error.message, "error"); }
});
document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelectorAll("[data-command]").forEach((button) => button.addEventListener("click", () => command(`/api/facilitator/${button.dataset.command}`)));
document.querySelector("#advance").addEventListener("click", () => command("/api/facilitator/advance", {elapsed_seconds: Number(document.querySelector("#advance-seconds").value)}));
document.querySelector("#stop").addEventListener("click", () => command("/api/facilitator/stop", {reason: document.querySelector("#stop-reason").value}));
document.querySelector("#reset").addEventListener("click", () => command("/api/facilitator/reset", {new_run_id: document.querySelector("#new-run-id").value || null}));
document.querySelector("#resolve-dp2").addEventListener("click", () => command("/api/facilitator/checkpoints/dp2"));
document.querySelector("#resolve-dp3").addEventListener("click", () => command("/api/facilitator/checkpoints/dp3"));
for (const decision of ["approve", "deny"]) {
  document.querySelector(`#mfa-${decision}`).addEventListener("click", () => {
    if (pendingMfa) command("/api/facilitator/mfa/decision", {challenge_id: pendingMfa.id, decision});
  });
}

document.querySelector("#msel-body").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-command]");
  if (!button) return;
  if (button.dataset.command === "deliver") command("/api/facilitator/deliver", {item_id: button.dataset.item});
  else command("/api/facilitator/skip", {item_id: button.dataset.item, reason: "Skipped by facilitator from control console"});
});

async function download(format) {
  try {
    const response = await fetch(`/api/facilitator/exports/events.${format}`, {headers: {Authorization: `Bearer ${token()}`}});
    if (!response.ok) throw new Error("Evidence export failed.");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${document.querySelector("#run-id").textContent}-events.${format}`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) { notify(notice, error.message, "error"); }
}
document.querySelector("#download-jsonl").addEventListener("click", () => download("jsonl"));
document.querySelector("#download-csv").addEventListener("click", () => download("csv"));

if (token()) refresh();
setInterval(refresh, 5000);
