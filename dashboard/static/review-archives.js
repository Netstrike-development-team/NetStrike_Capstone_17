"use strict";

import {api, token} from "./common.js";
import {saveText} from "./staff-operations.js";

const TERMINAL = new Set(["stopped", "completed"]);
const TYPES = {"bundle.json": "application/json", "aar.md": "text/markdown", "events.jsonl": "application/x-ndjson"};

async function rawText(path, credential) {
  const response = await fetch(path, {headers: {Authorization: `Bearer ${credential}`}, cache: "no-store"});
  if (!response.ok) throw Object.assign(new Error("Archive download failed"), {status: response.status});
  // Preserve the exact server serialization, including float representations in bundle hashes.
  return response.text();
}

export class ReviewArchives {
  constructor({call = api, readToken = token, readText = rawText, changed = () => {}} = {}) {
    Object.assign(this, {call, readToken, readText, changed});
    this.credential = "";
    this.epoch = 0;
    this.listSerial = this.previewSerial = this.reportSerial = 0;
    this.clear(false);
  }

  clear(notify = true) {
    this.epoch += 1;
    this.listSerial += 1; this.previewSerial += 1; this.reportSerial += 1;
    this.page = null;
    this.candidate = null;
    this.report = null;
    this.busy = false;
    this.uncertain = false;
    this.message = "No authorized archives loaded.";
    if (notify) this.changed();
  }

  sync() {
    const credential = this.readToken();
    if (credential !== this.credential) { this.credential = credential; this.clear(); }
    return credential;
  }

  current(credential, epoch) { return this.readToken() === credential && this.epoch === epoch; }

  async list(after = 0) {
    const credential = this.sync();
    if (!credential) return;
    const epoch = this.epoch;
    const serial = ++this.listSerial;
    try {
      const page = await this.call(`/api/evaluator/archives?after_sequence=${after}&limit=10`, {cache: "no-store"});
      if (!this.current(credential, epoch) || serial !== this.listSerial) return;
      this.page = page;
      this.report = null; this.reportSerial += 1;
      this.message = page.archives.length ? "Saved captures are read-only; they never replace the current run's ratings." : "No saved captures on this page.";
      this.changed();
    } catch (error) {
      if (!this.current(credential, epoch) || serial !== this.listSerial) return;
      this.page = this.report = null;
      this.reportSerial += 1;
      if ([401, 403].includes(error.status)) this.clear();
      this.message = "Archive list unavailable or access denied. Do not treat this as an empty history.";
      this.changed();
    }
  }

  async preview({replaceUncertain = false} = {}) {
    const credential = this.sync();
    if (!credential || this.busy || this.uncertain && !replaceUncertain) return;
    const epoch = this.epoch;
    const serial = ++this.previewSerial;
    this.candidate = null; this.uncertain = false;
    this.changed();
    try {
      const bundle = await this.call("/api/evaluator/exports/bundle.json", {cache: "no-store"});
      if (!this.current(credential, epoch) || serial !== this.previewSerial) return;
      if (!TERMINAL.has(bundle.run_state)) { this.message = "Stop or complete play before capturing a review. Finish ratings before reset."; }
      else {
        this.candidate = {run_id: bundle.run_id, expected_bundle_sha256: bundle.content_sha256};
        this.message = `Capture preview: ${bundle.run_id} · ${bundle.run_state} · ${bundle.events.length} events · ${bundle.submissions.length} submissions. Capturing does not finish or calibrate ratings.`;
      }
      this.changed();
    } catch (error) {
      if (!this.current(credential, epoch) || serial !== this.previewSerial) return;
      if ([401, 403].includes(error.status)) this.clear();
      this.message = "Capture preview unavailable. No capture was requested.";
      this.changed();
    }
  }

  async capture() {
    const credential = this.sync();
    if (!credential || !this.candidate || this.busy) return null;
    const epoch = this.epoch;
    const candidate = {...this.candidate};
    this.previewSerial += 1;
    this.busy = true; this.changed();
    try {
      const result = await this.call("/api/evaluator/archives", {method: "POST", body: JSON.stringify(candidate), cache: "no-store"});
      if (!this.current(credential, epoch)) return null;
      this.candidate = null; this.uncertain = false;
      this.message = `Saved run ${result.metadata.run_id} as ${result.metadata.archive_id}${result.status === "already_captured" ? " (existing capture confirmed)" : ""}. Export outside restored VMs before rollback.`;
      this.listSerial += 1; // Do not display a list read issued before capture as current.
      return result;
    } catch (error) {
      if (!this.current(credential, epoch)) return null;
      if ([401, 403].includes(error.status)) this.clear();
      else this.uncertain = true;
      this.message = "Capture not confirmed. Inspect saved archives, then retry the same run/hash. Do not assume success or load a new capture silently.";
      return null;
    } finally {
      if (this.current(credential, epoch)) { this.busy = false; this.changed(); }
    }
  }

  async show(identifier) {
    const credential = this.sync();
    if (!credential || !this.page?.archives.some((item) => item.archive_id === identifier)) return;
    const epoch = this.epoch;
    const serial = ++this.reportSerial;
    this.report = null; this.changed();
    try {
      const report = await this.call(`/api/evaluator/archives/${encodeURIComponent(identifier)}/report`, {cache: "no-store"});
      if (!this.current(credential, epoch) || serial !== this.reportSerial) return;
      this.report = {identifier, report}; this.changed();
    } catch (error) {
      if (!this.current(credential, epoch) || serial !== this.reportSerial) return;
      if ([401, 403].includes(error.status)) this.clear();
      this.message = "Saved report unavailable. Its contents were not loaded."; this.changed();
    }
  }

  async download(identifier, suffix) {
    const credential = this.sync();
    if (!credential || !Object.hasOwn(TYPES, suffix) || !this.page?.archives.some((item) => item.archive_id === identifier)) return null;
    const epoch = this.epoch;
    try {
      const payload = await this.readText(`/api/evaluator/archives/${encodeURIComponent(identifier)}/${suffix}`, credential);
      return this.current(credential, epoch) ? {payload, filename: `${identifier}-${suffix}`, type: TYPES[suffix]} : null;
    } catch (error) {
      if (!this.current(credential, epoch)) return null;
      if ([401, 403].includes(error.status)) this.clear();
      throw new Error("Archive download failed. No file was saved.");
    }
  }
}

function text(tag, value, className = "") {
  const node = document.createElement(tag); node.textContent = value; node.className = className; return node;
}

export function renderArchivePage(container, page) {
  container.replaceChildren();
  if (!page?.archives.length) { container.append(text("p", page ? "No saved captures on this page." : "No authorized archive list loaded.", "empty")); return; }
  for (const record of page.archives) {
    const card = text("article", "", "support-thread");
    card.append(text("h3", `${record.run_id} · ${record.run_state}`),
      text("p", `${record.captured_at} · ${record.capture_reason.replaceAll("_", " ")} · ${record.reviewed_objectives}/5 objectives reviewed · ${record.review_status}`),
      text("p", `${record.event_count} events through sequence ${record.last_sequence} · ${record.submission_count} submissions · captured by ${record.captured_by.actor_id} (${record.captured_by.role})`, "muted"),
      text("code", record.archive_id), text("p", "Frozen before its archive audit, later cleanup and later corrections. Not a VM backup.", "muted"));
    const buttons = text("div", "", "controls space-top");
    for (const [label, suffix] of [["Show saved review", "report"], ["Download bundle", "bundle.json"], ["Download AAR", "aar.md"], ["Download events", "events.jsonl"]]) {
      const button = text("button", label, "secondary");
      button.type = "button"; button.dataset.archive = record.archive_id; button.dataset.suffix = suffix;
      buttons.append(button);
    }
    card.append(buttons); container.append(card);
  }
}

export function renderSavedReview(container, snapshot) {
  container.replaceChildren();
  if (!snapshot) return;
  const {report, identifier} = snapshot;
  container.append(text("h3", `Read-only saved review · ${report.run_id}`), text("code", identifier),
    text("p", `${report.reviewed_objectives}/5 objectives reviewed · ${report.status}. This does not load or edit the current judgment form.`, "ops-warning"));
  for (const item of report.objectives) {
    const card = text("article", "", "support-thread");
    card.append(text("h4", `${item.objective_id} · ${item.title}`), text("p", item.judgment ? item.judgment.rating.replaceAll("_", " ") : "Awaiting human review"));
    if (item.judgment) card.append(text("p", item.judgment.rationale, "support-prose"));
    container.append(card);
  }
}

export function mountArchives({sessionOptions = {}} = {}) {
  const summary = document.querySelector("#archive-summary");
  const list = document.querySelector("#archive-list");
  const report = document.querySelector("#saved-review");
  const capture = document.querySelector("#archive-capture");
  const next = document.querySelector("#archive-next");
  const prepare = document.querySelector("#archive-prepare");
  const session = new ReviewArchives({...sessionOptions, changed: () => {
    summary.textContent = session.message;
    renderArchivePage(list, session.page); renderSavedReview(report, session.report);
    capture.disabled = !session.candidate || session.busy;
    capture.textContent = session.busy ? "Capturing…" : session.uncertain ? "Retry same capture" : "Capture reviewed run";
    prepare.disabled = session.busy;
    next.disabled = !session.page?.has_more;
  }});
  prepare.addEventListener("click", () => {
    const replaceUncertain = session.uncertain && window.confirm("Replace an unconfirmed capture preview? Inspect the archive list first. A fresh hash may create another capture rather than confirm the earlier one.");
    session.preview({replaceUncertain});
  });
  capture.addEventListener("click", async () => {
    const result = await session.capture();
    if (result) {
      const message = session.message;
      const credential = session.readToken(); const epoch = session.epoch;
      await session.list();
      if (session.current(credential, epoch)) summary.textContent = message;
    }
  });
  document.querySelector("#archive-refresh").addEventListener("click", () => session.list());
  next.addEventListener("click", () => session.list(session.page?.next_sequence || 0));
  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-archive]");
    if (!button) return;
    const credential = session.readToken(); const epoch = session.epoch;
    button.disabled = true;
    try {
      if (button.dataset.suffix === "report") await session.show(button.dataset.archive);
      else {
        const result = await session.download(button.dataset.archive, button.dataset.suffix);
        if (result) saveText(result.payload, result.filename, result.type);
      }
    } catch (error) {
      if (session.current(credential, epoch)) summary.textContent = "Archive download failed. No file was saved.";
    } finally { if (session.current(credential, epoch)) button.disabled = false; }
  });
  document.querySelector("#connect").addEventListener("click", () => { session.clear(); session.list(); });
  window.addEventListener("pagehide", () => session.clear());
  session.changed(); session.list();
  return session;
}
