"use strict";

import {api, connect, notify, token} from "/static/common.js";
import {mountSupport} from "/static/support.js";
import {mountArchives} from "/static/review-archives.js";

const notice = document.querySelector("#notice");
const form = document.querySelector("#judgment");
let report = null;
let generation = 0;

function text(tag, value) {
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
}

function clear() {
  report = null;
  form.reset();
  form.elements.objective_id.replaceChildren(new Option("Select objective", ""));
  for (const selector of ["#objectives", "#evidence"]) document.querySelector(selector).replaceChildren();
  for (const selector of ["#save", "#bundle", "#aar"]) document.querySelector(selector).disabled = true;
  document.querySelector("#review-summary").textContent = "No authorized run loaded.";
  document.querySelector("#revision").textContent = "Select an objective.";
}

function selectObjective() {
  const item = report?.objectives.find((objective) => objective.objective_id === form.elements.objective_id.value);
  document.querySelector("#revision").textContent = item
    ? `Current revision: ${item.judgment?.revision || 0}. A saved correction requires a reason.` : "Select an objective.";
  for (const name of ["rating", "rationale", "evidence_ids", "override_reason", "platform_reason"]) form.elements[name].value = "";
  for (const name of ["description", "owner", "target_date"]) form.elements[name].value = "";
  if (item?.judgment) {
    for (const name of ["rating", "rationale", "platform_reason"]) form.elements[name].value = item.judgment[name];
    form.elements.evidence_ids.value = item.judgment.evidence_ids.join("\n");
  }
}

function render() {
  document.querySelector("#review-summary").textContent = `${report.run_id} · ${report.run_state} · ${report.reviewed_objectives}/5 objectives reviewed · ${report.status}`;
  const objectives = document.querySelector("#objectives");
  const evidence = document.querySelector("#evidence");
  objectives.replaceChildren();
  evidence.replaceChildren();
  form.elements.objective_id.replaceChildren(new Option("Select objective", ""));
  for (const item of report.objectives) {
    form.elements.objective_id.add(new Option(`${item.objective_id} · ${item.title}`, item.objective_id));
    const card = text("article", "");
    card.className = "inject";
    card.append(text("h3", `${item.objective_id} · ${item.title}`),
      text("p", `System observation: ${item.observation.status.replaceAll("_", " ")}`),
      text("p", item.observation.explanation),
      text("strong", item.judgment ? item.judgment.rating.replaceAll("_", " ") : "Awaiting evaluator review"));
    for (const criterion of item.criteria) card.append(text("p", criterion));
    card.append(text("p", `Human review: ${item.human_review.join("; ")}`));
    if (item.judgment) card.append(text("p", item.judgment.rationale),
      text("small", `${item.judgment.evaluator_id} · revision ${item.judgment.revision} · ${item.judgment.timestamp}`));
    if (item.history.length > 1) {
      const history = text("details", "");
      history.append(text("summary", "Revision history"));
      for (const entry of item.history) history.append(text("p", `Revision ${entry.revision}: ${entry.rating} by ${entry.evaluator_id}. ${entry.override_reason}`));
      card.append(history);
    }
    objectives.append(card);
  }
  for (const submission of report.submissions) {
    const card = text("article", "");
    card.className = "inject";
    card.append(text("code", `submission:${submission.submission_id}`),
      text("p", `${submission.submission_type} · ${submission.actor_id} · ${submission.submitted_at}`),
      text("pre", JSON.stringify(submission.payload, null, 2)));
    evidence.append(card);
  }
  for (const event of report.timeline) {
    const card = text("article", "");
    card.className = "inject";
    card.append(text("code", event.event_id), text("p", `#${event.sequence} · ${event.event_type} · ${event.timestamp}`), text("p", event.message));
    evidence.append(card);
  }
  document.querySelector("#save").disabled = !["completed", "stopped"].includes(report.run_state);
  document.querySelector("#bundle").disabled = false;
  document.querySelector("#aar").disabled = false;
}

async function refresh() {
  const requestGeneration = ++generation;
  const credential = token();
  if (!credential) { clear(); return; }
  try {
    const payload = await api("/api/evaluator/report");
    if (requestGeneration !== generation || token() !== credential) return;
    const priorRun = report?.run_id;
    report = payload;
    form.reset();
    render();
    if (priorRun && priorRun !== report.run_id) notify(notice, "Run changed. Review form cleared.");
  } catch (error) {
    if (requestGeneration !== generation || token() !== credential) return;
    clear();
    notify(notice, error.message, "error");
  }
}

document.querySelector("#connect").addEventListener("click", () => {
  generation += 1;
  clear();
  try { connect(document.querySelector("#token-input"), refresh); }
  catch (error) { notify(notice, error.message, "error"); }
});
document.querySelector("#refresh").addEventListener("click", refresh);
mountSupport({staff: true, observer: true});
mountArchives();
form.elements.objective_id.addEventListener("change", selectObjective);
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!report) return;
  const item = report.objectives.find((objective) => objective.objective_id === form.elements.objective_id.value);
  if (!item) return;
  const credential = token();
  const requestGeneration = generation;
  const data = new FormData(form);
  const payload = {run_id: report.run_id, objective_id: item.objective_id,
    expected_revision: item.judgment?.revision || 0,
    rating: data.get("rating"), rationale: data.get("rationale"),
    evidence_ids: data.get("evidence_ids").split("\n").map((id) => id.trim()).filter(Boolean),
    override_reason: data.get("override_reason"), platform_reason: data.get("platform_reason"),
    improvement_actions: data.get("description").trim() ? [{description: data.get("description"),
      owner: data.get("owner"), priority: data.get("priority"), target_date: data.get("target_date")}] : []};
  document.querySelector("#save").disabled = true;
  try {
    await api("/api/evaluator/judgments", {method: "POST", body: JSON.stringify(payload)});
    if (token() !== credential || generation !== requestGeneration) return;
    notify(notice, "Judgment recorded. Previous revisions remain in the audit trail.");
    await refresh();
  } catch (error) {
    if (token() !== credential || generation !== requestGeneration) return;
    notify(notice, error.message, "error");
    document.querySelector("#save").disabled = false;
  }
});

for (const [selector, path, name, type] of [
  ["#bundle", "/api/evaluator/exports/bundle.json", "run-review-bundle.json", "application/json"],
  ["#aar", "/api/evaluator/exports/aar.md", "after-action-review.md", "text/markdown"],
]) document.querySelector(selector).addEventListener("click", async () => {
  const credential = token();
  const requestGeneration = generation;
  try {
    const payload = await api(path, {rawText: true, cache: "no-store"});
    if (token() !== credential || generation !== requestGeneration) return;
    const url = URL.createObjectURL(new Blob([payload], {type}));
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    if (token() === credential && generation === requestGeneration) notify(notice, error.message, "error");
  }
});

refresh();
