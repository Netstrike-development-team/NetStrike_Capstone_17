"use strict";

import {clearNotice, connect, formatElapsed, notify, setStatus, token} from "/static/common.js";
import {mountSupport} from "/static/support.js";
import {StaffOperations, renderOperations, saveText} from "/static/staff-operations.js";

const notice = document.querySelector("#notice");
const tokenInput = document.querySelector("#token-input");
let pendingMfa = null;
const operations = new StaffOperations({
  changed: () => { renderState(operations.state); updateControls(); },
  cleared: (reason) => {
    pendingMfa = null;
    for (const selector of ["#stop-reason", "#new-run-id"]) document.querySelector(selector).value = "";
    if (["credentials", "run"].includes(reason)) clearNotice(notice);
  },
});

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
        if (command === "deliver" && item.trigger === "checkpoint" && ["cloud", "impact_recovery"].includes(item.phase)) continue;
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

function renderState(state) {
    renderOperations(state);
    if (!state) {
      setStatus(document.querySelector("#run-state"), "unavailable");
      document.querySelector("#elapsed").textContent = "—";
      document.querySelector("#event-count").textContent = "—";
      document.querySelector("#run-id").textContent = "—";
      for (const selector of ["#msel-body", "#event-log", "#submissions", "#checks", "#cloud-checks", "#impact-checks", "#recovery-checks"]) document.querySelector(selector).replaceChildren();
      document.querySelector("#profile-summary").textContent = "No authorized snapshot.";
      document.querySelector("#mfa-summary").textContent = "No authorized snapshot.";
      pendingMfa = null;
      return;
    }
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
    document.querySelector("#impact-verifier").hidden = !state.impact.enabled;
    document.querySelector("#resolve-dp4").hidden = !state.impact.enabled;
    document.querySelector("#rollback-impact").hidden = !state.impact.enabled;
    document.querySelector("#resolve-dp4").disabled = state.controller.items.DP4?.status !== "ready" || state.controller.state !== "running";
    document.querySelector("#rollback-impact").disabled = !state.impact.rollback_available;
    if (state.impact.enabled) {
      renderChecks(state.impact.dp4_preview, "#impact-checks");
      renderChecks(state.impact.recovery_preview, "#recovery-checks");
      if (state.impact.health_error) notify(notice, "Disposable fixture safety/readability failed. Stop and investigate before reset.", "error");
    }
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
}

function updateControls() {
  document.querySelector("#control-status").textContent = operations.stopBusy
    ? "Emergency stop awaiting confirmation. Ordinary controls are blocked; inspect the result and use the range emergency procedure if unreachable."
    : operations.busy ? "Control awaiting confirmation. Emergency stop remains available for the inspected run."
    : operations.state ? "Authorized snapshot loaded. The server rechecks each control."
    : "Refresh and inspect before using ordinary controls. Unconfirmed commands are never automatically repeated.";
  for (const button of document.querySelectorAll("button[data-command]")) {
    button.disabled = !operations.can(button.dataset.command, {item_id: button.dataset.item});
  }
  for (const [id, action] of [["#advance", "advance"], ["#stop", "stop"], ["#reset", "reset"],
    ["#resolve-dp2", "checkpoints/dp2"], ["#resolve-dp3", "checkpoints/dp3"], ["#resolve-dp4", "checkpoints/dp4"],
    ["#rollback-impact", "impact/rollback"], ["#mfa-deny", "mfa/decision"], ["#mfa-approve", "mfa/decision"]]) {
    document.querySelector(id).disabled = !operations.can(action);
  }
  for (const selector of ["#download-jsonl", "#download-csv"]) document.querySelector(selector).disabled = !operations.state;
}

async function refresh() { await operations.refresh(); }

async function command(path, body) {
  const action = path.replace("/api/facilitator/", "");
  if (!operations.can(action, body)) { notify(notice, "Refresh the run and check its state before using this control.", "error"); return; }
  if (action === "start" && !window.confirm("Start play only after the external range checks and facilitator admission decision are complete. Local readiness is not range approval. Continue?")) return;
  if (action === "reset" && !window.confirm(`Reset application run ${operations.runId}? A terminal review is archived first, but ratings must be finished before reset. Export evidence outside the VM before snapshot restoration. This is not a VM restore.`)) return;
  if (action === "stop" && !body?.reason.trim()) { notify(notice, "Enter a safety or platform reason for the stop.", "error"); return; }
  const credential = token();
  const epoch = operations.epoch;
  const runId = operations.runId;
  clearNotice(notice);
  try {
    const result = await operations.command(action, body);
    if (!operations.current(credential, epoch) || operations.runId !== runId || !result) return;
    notify(notice, result.reset ? `Application reset completed. Prior run ${result.reset.prior_run_id} saved as archive ${result.reset.review_archive_id}. Use evaluator archives to download it; VM restoration still requires external export.` : "Control action completed and recorded.");
    await refresh();
  } catch (error) {
    if (operations.current(credential, epoch) && operations.runId === runId) {
      notify(notice, error.message, "error"); await refresh();
    }
  }
}

document.querySelector("#connect").addEventListener("click", () => {
  clearNotice(notice);
  operations.invalidate("credentials");
  try { connect(tokenInput, refresh); } catch (error) { notify(notice, error.message, "error"); }
});
document.querySelector("#refresh").addEventListener("click", refresh);
mountSupport({staff: true});
document.querySelectorAll("[data-command]").forEach((button) => button.addEventListener("click", () => command(`/api/facilitator/${button.dataset.command}`)));
document.querySelector("#advance").addEventListener("click", () => command("/api/facilitator/advance", {elapsed_seconds: Number(document.querySelector("#advance-seconds").value)}));
document.querySelector("#stop").addEventListener("click", () => command("/api/facilitator/stop", {reason: document.querySelector("#stop-reason").value}));
document.querySelector("#reset").addEventListener("click", () => command("/api/facilitator/reset", {new_run_id: document.querySelector("#new-run-id").value || null}));
document.querySelector("#resolve-dp2").addEventListener("click", () => command("/api/facilitator/checkpoints/dp2"));
document.querySelector("#resolve-dp3").addEventListener("click", () => command("/api/facilitator/checkpoints/dp3"));
document.querySelector("#resolve-dp4").addEventListener("click", () => command("/api/facilitator/checkpoints/dp4"));
document.querySelector("#rollback-impact").addEventListener("click", () => command("/api/facilitator/impact/rollback"));
for (const decision of ["approve", "deny"]) {
  document.querySelector(`#mfa-${decision}`).addEventListener("click", () => {
    if (pendingMfa) return command("/api/facilitator/mfa/decision", {challenge_id: pendingMfa.id, decision});
  });
}

document.querySelector("#msel-body").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-command]");
  if (!button) return;
  if (button.dataset.command === "deliver") return command("/api/facilitator/deliver", {item_id: button.dataset.item});
  return command("/api/facilitator/skip", {item_id: button.dataset.item, reason: "Skipped by facilitator from control console"});
});

async function download(format) {
  const credential = token();
  const epoch = operations.epoch;
  try {
    const result = await operations.exportEvents(format);
    if (result) saveText(result.payload, `${result.runId}-events.${format}`, format === "csv" ? "text/csv" : "application/x-ndjson");
  } catch (error) { if (operations.current(credential, epoch)) notify(notice, "Evidence export failed. Refresh the current run before retrying.", "error"); }
}
document.querySelector("#download-jsonl").addEventListener("click", () => download("jsonl"));
document.querySelector("#download-csv").addEventListener("click", () => download("csv"));

renderState(null); updateControls();
refresh();
const interval = setInterval(refresh, 5000);
window.addEventListener("pagehide", () => { clearInterval(interval); operations.invalidate("credentials"); });
