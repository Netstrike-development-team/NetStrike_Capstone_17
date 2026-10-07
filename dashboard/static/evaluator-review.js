"use strict";

import {api, token} from "./common.js";

const TERMINAL = new Set(["stopped", "completed"]);
const EXPORTS = {bundle: ["bundle.json", "run-review-bundle.json", "application/json"],
  aar: ["aar.md", "after-action-review.md", "text/markdown"]};

export function revision(report, objectiveId) {
  const item = report?.objectives.find((objective) => objective.objective_id === objectiveId);
  return item ? item.judgment?.revision || 0 : null;
}

export class EvaluatorReview {
  constructor({call = api, readToken = token, cleared = () => {}, changed = () => {}} = {}) {
    Object.assign(this, {call, readToken, cleared, changed});
    this.credential = "";
    this.epoch = this.serial = 0;
    this.runId = this.report = null;
    this.busy = this.inspectRequired = false;
  }

  invalidate(reason) {
    this.epoch += 1;
    this.serial += 1;
    this.runId = this.report = null;
    this.busy = this.inspectRequired = false;
    this.cleared(reason);
    this.changed();
  }

  sync() {
    const credential = this.readToken();
    if (credential !== this.credential) {
      this.credential = credential;
      this.invalidate("credentials");
    }
    return credential;
  }

  current(credential, epoch) {
    return Boolean(credential) && this.readToken() === credential && this.epoch === epoch;
  }

  async refresh() {
    const credential = this.sync();
    if (!credential) return null;
    const epoch = this.epoch;
    const serial = ++this.serial;
    try {
      const report = await this.call("/api/evaluator/report", {cache: "no-store"});
      if (!this.current(credential, epoch) || serial !== this.serial) return null;
      if (!report.run_id || !/^[0-9a-f]{64}$/.test(report.bundle_sha256)
          || !Array.isArray(report.objectives)) throw new Error("Review snapshot unavailable.");
      if (this.runId && this.runId !== report.run_id) this.invalidate("run");
      this.runId = report.run_id;
      this.report = report;
      this.inspectRequired = this.busy;
      this.changed();
      return report;
    } catch (error) {
      if (!this.current(credential, epoch) || serial !== this.serial) return null;
      this.report = null;
      this.inspectRequired = true;
      if ([401, 403].includes(error.status)) this.invalidate("credentials");
      this.changed();
      throw error;
    }
  }

  canSave(objectiveId) {
    return !this.busy && !this.inspectRequired && Boolean(this.report)
      && TERMINAL.has(this.report.run_state) && revision(this.report, objectiveId) !== null;
  }

  canExport() { return !this.busy && !this.inspectRequired && Boolean(this.report); }

  async submit(objectiveId, fields) {
    const credential = this.sync();
    if (!credential || !this.canSave(objectiveId)) return null;
    const epoch = this.epoch;
    const runId = this.runId;
    const expected = revision(this.report, objectiveId);
    // Freeze before awaiting; subsequent draft edits never change this request.
    const body = JSON.stringify({...fields, objective_id: objectiveId, run_id: runId,
      expected_revision: expected});
    this.serial += 1;
    this.busy = this.inspectRequired = true;
    this.changed();
    try {
      const receipt = await this.call("/api/evaluator/judgments", {method: "POST", cache: "no-store", body});
      if (!this.current(credential, epoch) || this.runId !== runId) return null;
      if (receipt?.run_id !== runId || receipt.revision !== expected + 1
          || receipt.status !== "recorded" || !receipt.event_id) throw new Error("Invalid review acknowledgment.");
      this.serial += 1;
      return receipt;
    } catch (error) {
      if (!this.current(credential, epoch) || this.runId !== runId) return null;
      this.serial += 1;
      this.inspectRequired = true;
      if ([401, 403].includes(error.status)) this.invalidate("credentials");
      throw new Error("Judgment not confirmed. Refresh and inspect the saved revision before editing or submitting again; do not assume the write failed.");
    } finally {
      if (this.current(credential, epoch)) { this.busy = false; this.changed(); }
    }
  }

  async download(kind) {
    const credential = this.sync();
    if (!credential || !Object.hasOwn(EXPORTS, kind) || !this.canExport()) return null;
    const epoch = this.epoch;
    const {runId, report} = this;
    const sha256 = report.bundle_sha256;
    const [suffix, filename, type] = EXPORTS[kind];
    try {
      const payload = await this.call(`/api/evaluator/exports/${suffix}`, {rawText: true, cache: "no-store",
        headers: {"X-Exercise-Run-ID": runId, "X-Review-Bundle-SHA256": sha256}});
      if (!this.current(credential, epoch) || this.runId !== runId
          || this.report?.bundle_sha256 !== sha256 || this.inspectRequired) return null;
      const safeRun = runId.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 128);
      return {payload, filename: `${safeRun}-${sha256.slice(0, 12)}-${filename}`, type};
    } catch (error) {
      if (!this.current(credential, epoch) || this.runId !== runId
          || this.report?.bundle_sha256 !== sha256) return null;
      this.inspectRequired = true;
      if ([401, 403].includes(error.status)) this.invalidate("credentials");
      this.changed();
      throw new Error("Export not confirmed. Refresh the current review before downloading again. No file was saved.");
    }
  }
}
