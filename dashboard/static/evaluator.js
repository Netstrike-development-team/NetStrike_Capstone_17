"use strict";

import {clearNotice, connect, notify} from "/static/common.js";
import {mountSupport} from "/static/support.js";
import {mountArchives} from "/static/review-archives.js";
import {EvaluatorReview, revision} from "/static/evaluator-review.js";
import {saveText} from "/static/staff-operations.js";

const notice = document.querySelector("#notice");
const form = document.querySelector("#judgment");
let report = null;
const review = new EvaluatorReview({cleared: (reason) => {
  clear();
  clearNotice(notice);
  if (reason === "run") notify(notice, "Run changed. Previous-run review drafts were cleared. Inspect the new report.");
}, changed: updateControls});

function updateControls() {
  document.querySelector("#save").disabled = !review.canSave(form.elements.objective_id.value);
  for (const selector of ["#bundle", "#aar"]) document.querySelector(selector).disabled = !review.canExport();
  for (const field of form.querySelectorAll("input, select, textarea")) {
    field.disabled = review.busy || review.inspectRequired || !review.report
      || !["completed", "stopped"].includes(review.report.run_state);
  }
  if (!review.report && report) document.querySelector("#review-summary").textContent = "Current review unavailable. Draft retained; refresh before saving or exporting.";
}

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
  updateControls();
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
  updateControls();
}

async function refresh() {
  try {
    const payload = await review.refresh();
    if (!payload) return;
    const selected = form.elements.objective_id.value;
    const previousRevision = revision(report, selected);
    const nextRevision = revision(payload, selected);
    const preserve = report?.run_id === payload.run_id && previousRevision !== null
      && previousRevision === nextRevision;
    report = payload;
    render();
    if (preserve) {
      form.elements.objective_id.value = selected;
    } else {
      form.reset();
      if (nextRevision !== null) {
        form.elements.objective_id.value = selected;
        selectObjective();
        notify(notice, "Saved objective revision changed. Stale draft cleared; inspect the recorded judgment before editing.");
      }
    }
    updateControls();
  } catch (error) {
    updateControls();
    notify(notice, error.message, "error");
  }
}

document.querySelector("#connect").addEventListener("click", () => {
  try { connect(document.querySelector("#token-input"), refresh); }
  catch (error) { notify(notice, error.message, "error"); }
});
document.querySelector("#refresh").addEventListener("click", refresh);
mountSupport({staff: true, observer: true});
mountArchives();
form.elements.objective_id.addEventListener("change", selectObjective);
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const objectiveId = form.elements.objective_id.value;
  if (!review.canSave(objectiveId)) return;
  const data = new FormData(form);
  const payload = {rating: data.get("rating"), rationale: data.get("rationale"),
    evidence_ids: data.get("evidence_ids").split("\n").map((id) => id.trim()).filter(Boolean),
    override_reason: data.get("override_reason"), platform_reason: data.get("platform_reason"),
    improvement_actions: data.get("description").trim() ? [{description: data.get("description"),
      owner: data.get("owner"), priority: data.get("priority"), target_date: data.get("target_date")}] : []};
  try {
    const receipt = await review.submit(objectiveId, payload);
    if (!receipt) return;
    form.reset();
    notify(notice, "Judgment recorded. Previous revisions remain in the audit trail.");
    await refresh();
  } catch (error) {
    notify(notice, error.message, "error");
    updateControls();
  }
});

for (const [selector, kind] of [
  ["#bundle", "bundle"], ["#aar", "aar"],
]) document.querySelector(selector).addEventListener("click", async () => {
  try {
    const download = await review.download(kind);
    if (download) saveText(download.payload, download.filename, download.type);
  } catch (error) {
    notify(notice, error.message, "error");
  }
});

updateControls();
refresh();
