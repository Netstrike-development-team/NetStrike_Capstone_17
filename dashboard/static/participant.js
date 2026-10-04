"use strict";

import {api, clearNotice, connect, formatElapsed, idempotency, notify, setStatus, token} from "/static/common.js";
import {mountSupport} from "/static/support.js";

const notice = document.querySelector("#notice");
const tokenInput = document.querySelector("#token-input");
let lastRunId = null;

function renderInjects(injects) {
  const container = document.querySelector("#injects");
  container.replaceChildren();
  if (!injects.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No injects have been delivered yet.";
    container.append(empty);
    return;
  }
  for (const inject of injects) {
    const article = document.createElement("article");
    article.className = "inject";
    const id = document.createElement("strong");
    id.textContent = inject.msel_id;
    const message = document.createElement("p");
    message.textContent = inject.message;
    const time = document.createElement("time");
    time.textContent = new Date(inject.timestamp).toLocaleString();
    article.append(id, message, time);
    container.append(article);
  }
}

async function refresh() {
  if (!token()) return;
  try {
    const state = await api("/api/participant/state");
    if (lastRunId && lastRunId !== state.run_id) {
      document.querySelector("#feedback").replaceChildren();
      document.querySelector("#intrusion-timeline").reset();
      document.querySelector("#recovery-actions").reset();
      document.querySelector("#recovery-brief").reset();
      document.querySelector("#cloud-form").reset();
      for (const id of ["#recovery-state", "#recovery-audit", "#cloud-state", "#cloud-audit"]) {
        document.querySelector(id).replaceChildren();
      }
    }
    lastRunId = state.run_id;
    setStatus(document.querySelector("#run-state"), state.state);
    document.querySelector("#elapsed").textContent = formatElapsed(state.elapsed_seconds);
    document.querySelector("#inject-count").textContent = state.injects.length;
    document.querySelector("#run-id").textContent = state.run_id;
    renderInjects(state.injects);
    document.querySelector("#feedback-panel").hidden = !["stopped", "completed"].includes(state.state);
    document.querySelector("#cloud-panel").hidden = !state.cloud_enabled;
    for (const card of document.querySelectorAll(".cloud-action")) card.hidden = !state.cloud_enabled;
    document.querySelector("#recovery-panel").hidden = !state.impact_enabled;
    for (const card of document.querySelectorAll(".impact-control")) card.hidden = !state.impact_enabled;
  } catch (error) {
    notify(notice, error.message, "error");
  }
}

document.querySelector("#connect").addEventListener("click", () => {
  clearNotice(notice);
  try {
    connect(tokenInput, refresh);
  } catch (error) {
    notify(notice, error.message, "error");
  }
});
document.querySelector("#refresh").addEventListener("click", refresh);
mountSupport();

function addTimelineEntry() {
  const container = document.querySelector("#timeline-entries");
  if (container.children.length >= 12) return;
  const index = container.children.length + 1;
  const row = document.createElement("fieldset");
  row.className = "form-grid";
  const legend = document.createElement("legend");
  legend.textContent = `Event ${index}`;
  row.append(legend);
  for (const [name, label, placeholder, maximum] of [
    ["occurred_at", "Occurrence time (ISO 8601, with timezone)", "2026-10-02T14:00:00Z", 64],
    ["event_id", "Supporting event ID", "Copy the event ID from evidence", 128],
    ["summary", "What happened", "Your evidence-supported statement", 512],
  ]) {
    const wrapper = document.createElement("label");
    wrapper.className = "form-wide";
    wrapper.textContent = label;
    const input = document.createElement("input");
    input.name = `${name}-${index}`;
    input.dataset.field = name;
    input.required = true;
    input.maxLength = maximum;
    input.placeholder = placeholder;
    wrapper.append(input);
    row.append(wrapper);
  }
  const wrapper = document.createElement("label");
  wrapper.className = "form-wide";
  wrapper.textContent = "Statement type";
  const select = document.createElement("select");
  select.dataset.field = "statement_type";
  select.add(new Option("Observed fact", "fact"));
  select.add(new Option("Analyst inference", "inference"));
  wrapper.append(select);
  row.append(wrapper);
  container.append(row);
  document.querySelector("#add-timeline-entry").disabled = container.children.length >= 12;
}
for (let index = 0; index < 6; index += 1) addTimelineEntry();
document.querySelector("#add-timeline-entry").addEventListener("click", addTimelineEntry);
document.querySelector("#intrusion-timeline").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!lastRunId) { notify(notice, "Connect to the current exercise first.", "error"); return; }
  const credential = token();
  const runId = lastRunId;
  const entries = Array.from(document.querySelector("#timeline-entries").children, (row) =>
    Object.fromEntries(Array.from(row.querySelectorAll("[data-field]"), (field) => [field.dataset.field, field.value.trim()])));
  try {
    const receipt = await api("/api/participant/timeline", {method: "POST", body: JSON.stringify({run_id: runId, entries})});
    if (token() !== credential || lastRunId !== runId) return;
    notify(notice, `Timeline recorded as submission:${receipt.submission_id} for evaluator review.`);
  } catch (error) {
    if (token() === credential && lastRunId === runId) notify(notice, error.message, "error");
  }
});
document.querySelector("#load-feedback").addEventListener("click", async () => {
  const credential = token();
  const runId = lastRunId;
  const container = document.querySelector("#feedback");
  container.replaceChildren();
  try {
    const result = await api("/api/participant/feedback");
    if (token() !== credential || lastRunId !== runId || result.run_id !== runId) return;
    for (const item of result.objectives) {
      const card = document.createElement("article");
      card.className = "inject";
      const title = document.createElement("strong");
      title.textContent = `${item.title} · ${item.rating.replaceAll("_", " ")}`;
      const advice = document.createElement("p");
      advice.textContent = item.next_step;
      card.append(title, advice);
      container.append(card);
    }
  } catch (error) {
    if (token() === credential && lastRunId === runId) notify(notice, error.message, "error");
  }
});
document.querySelector("#load-directory").addEventListener("click", async () => {
  const button = document.querySelector("#load-directory");
  button.disabled = true;
  try {
    const profiles = await api("/api/participant/directory");
    const container = document.querySelector("#directory");
    container.replaceChildren();
    for (const profile of profiles) {
      const card = document.createElement("article");
      card.className = "inject";
      const title = document.createElement("strong");
      title.textContent = `${profile.display_name} · ${profile.title}`;
      const context = document.createElement("p");
      context.textContent = `${profile.department} · Account: ${profile.username} (configured) · Manager: ${profile.manager || "unknown"}`;
      const contacts = document.createElement("p");
      contacts.textContent = profile.email_candidates.length
        ? `Inferred contact candidates: ${profile.email_candidates.map((item) => `${item.address} (${item.confidence})`).join(", ")}`
        : "Contact email unknown; no verified candidate provided.";
      card.append(title, context, contacts);
      container.append(card);
    }
  } catch (error) {
    notify(notice, error.message, "error");
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#load-cloud").addEventListener("click", async () => {
  try {
    const cloud = await api("/api/participant/cloud");
    const count = Object.keys(cloud.state.objects).length;
    document.querySelector("#cloud-summary").textContent = `${count} synthetic objects · ${cloud.audit.length} audit events · Run ${cloud.run_id}`;
    document.querySelector("#cloud-state").textContent = JSON.stringify(cloud.state, null, 2);
    const container = document.querySelector("#cloud-audit");
    container.replaceChildren();
    for (const event of cloud.audit.slice().reverse()) {
      const card = document.createElement("article");
      card.className = "inject";
      const title = document.createElement("strong");
      title.textContent = `${event.event_type} · ${event.outcome.status}`;
      const facts = document.createElement("p");
      facts.textContent = JSON.stringify(event.data);
      const reference = document.createElement("input");
      reference.readOnly = true;
      reference.value = event.event_id;
      reference.setAttribute("aria-label", "Cloud audit event ID");
      card.append(title, facts, reference);
      container.append(card);
    }
  } catch (error) { notify(notice, error.message, "error"); }
});

document.querySelector("#cloud-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    await api("/api/participant/cloud/assessment", {
      method: "POST",
      body: JSON.stringify({
        principal_id: form.get("principal_id").trim(),
        confirmed_count: Number(form.get("confirmed_count")),
        conclusion: form.get("conclusion"),
        evidence_ids: form.get("evidence_ids").split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
      }),
    });
    notify(notice, "Cloud assessment recorded. Continue validating containment.");
  } catch (error) { notify(notice, error.message, "error"); }
});

document.querySelector("#actions").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  clearNotice(notice);
  button.disabled = true;
  try {
    const target = button.parentElement.querySelector("input").value.trim();
    if (!target) throw new Error("Enter the evidence-supported target ID first.");
    const result = await api("/api/participant/actions", {
      method: "POST",
      body: JSON.stringify({
        action_id: button.dataset.action,
        target_type: button.dataset.type,
        target_id: target,
        idempotency_key: idempotency(button.dataset.action),
      }),
    });
    notify(notice, result.message || "Action completed and recorded.");
  } catch (error) {
    notify(notice, error.message, "error");
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#load-recovery").addEventListener("click", async () => {
  try {
    const state = await api("/api/participant/recovery");
    document.querySelector("#recovery-summary").textContent = `${state.fixture.available_originals}/5 originals available · ${state.fixture.marker_count} harmless markers · Originals unchanged: ${state.fixture.originals_unchanged} · Run ${state.run_id}`;
    document.querySelector("#recovery-state").textContent = JSON.stringify({fixture: state.fixture, endpoint: state.endpoint}, null, 2);
    const container = document.querySelector("#recovery-audit");
    container.replaceChildren();
    for (const event of state.audit.slice().reverse()) {
      const card = document.createElement("article");
      card.className = "inject";
      const title = document.createElement("strong");
      title.textContent = event.event_type;
      const reference = document.createElement("input");
      reference.readOnly = true;
      reference.value = event.event_id;
      reference.setAttribute("aria-label", "Recovery audit event ID");
      card.append(title, reference);
      container.append(card);
    }
  } catch (error) { notify(notice, error.message, "error"); }
});

document.querySelector("#recovery-actions").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-recovery]");
  if (!button) return;
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  button.disabled = true;
  try {
    const result = await api("/api/participant/recovery/action", {
      method: "POST", body: JSON.stringify({
        action_id: button.dataset.recovery,
        fixture_id: new FormData(form).get("fixture_id").trim(),
        key: idempotency(button.dataset.recovery),
        dry_run: document.querySelector("#recovery-preview").checked,
      }),
    });
    notify(notice, result.status === "dry_run" ? "Preview passed. No files changed and no health validation was recorded." : "Action recorded. Refresh evidence to inspect the result.");
  } catch (error) { notify(notice, error.message, "error"); }
  finally { button.disabled = false; }
});

document.querySelector("#recovery-brief").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const lines = (key) => form.get(key).split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
  try {
    await api("/api/participant/recovery/brief", {
      method: "POST", body: JSON.stringify({
        confirmed_scope: form.get("confirmed_scope").trim(),
        confirmed_cloud_records: Number(form.get("confirmed_cloud_records")),
        business_impact: form.get("business_impact").trim(),
        actions_taken: form.get("actions_taken").trim(),
        remaining_risk: form.get("remaining_risk").trim(),
        recommendations: lines("recommendations"), evidence_ids: lines("evidence_ids"),
      }),
    });
    notify(notice, "Incident brief recorded for evaluator review.");
  } catch (error) { notify(notice, error.message, "error"); }
});

document.querySelector("#dp1-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearNotice(notice);
  const form = new FormData(event.currentTarget);
  const references = form.getAll("reference");
  const sources = form.getAll("source");
  try {
    const result = await api("/api/participant/checkpoints/dp1", {
      method: "POST",
      body: JSON.stringify({
        affected_identity: form.get("identity"),
        classification: form.get("classification"),
        evidence: references.map((reference, index) => ({reference_id: reference, source: sources[index]})),
      }),
    });
    notify(notice, result.passed ? "Assessment accepted. Continue containment." : result.reason, result.passed ? "success" : "error");
  } catch (error) {
    notify(notice, error.message, "error");
  }
});

if (token()) refresh();
setInterval(refresh, 10000);
