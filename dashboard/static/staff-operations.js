"use strict";

import {api, token} from "./common.js";

const CONTROL_ROLES = new Set(["facilitator", "technical_operator"]);
const CLOCK_OK = new Set(["healthy", "unmonitored"]);
const TERMINAL = new Set(["stopped", "completed"]);

export function permitted(state, action, body = {}) {
  if (!state || !CONTROL_ROLES.has(state.principal_role)) return false;
  const phase = state.controller.state;
  if (action === "stop") return phase !== "completed";
  if (action === "reset") return TERMINAL.has(phase);
  if (action === "impact/rollback") return Boolean(state.impact.rollback_available);
  if (!CLOCK_OK.has(state.clock.status)) return false;
  if (action === "prepare") return phase === "ready" && state.readiness.ready_to_prepare;
  if (action === "start") return phase === "ready" && state.readiness.ready_to_start;
  if (action === "pause") return phase === "running";
  if (action === "resume") return phase === "paused";
  if (action === "advance") return phase === "running";
  if (action === "mfa/decision") return phase === "running" && state.principal_role === "facilitator" && Boolean(state.scheduled_mfa.pending);
  if (action.startsWith("checkpoints/")) return phase === "running" && state.controller.items[action.split("/")[1].toUpperCase()]?.status === "ready";
  if (["deliver", "skip"].includes(action)) {
    const item = state.msel.find((entry) => entry.item_id === body.item_id);
    return ["ready", "running", "paused"].includes(phase) && item && ["pending", "ready"].includes(item.status)
      && !(action === "deliver" && item.trigger === "checkpoint" && ["cloud", "impact_recovery"].includes(item.phase));
  }
  return false;
}

export class StaffOperations {
  constructor({call = api, readToken = token, changed = () => {}, cleared = () => {}} = {}) {
    Object.assign(this, {call, readToken, changed, cleared});
    this.credential = "";
    this.epoch = 0;
    this.serial = 0;
    this.activity = 0;
    this.commandSerial = 0;
    this.busy = this.stopBusy = false;
    this.invalidate("initial", false);
  }

  invalidate(reason, notify = true) {
    this.epoch += 1;
    this.serial += 1;
    this.state = null;
    this.runId = null;
    this.role = null;
    // Reconnecting is not cancellation of a request already sent to the server.
    if (notify) { this.cleared(reason); this.changed(); }
  }

  sync() {
    const credential = this.readToken();
    if (credential !== this.credential) {
      this.credential = credential;
      this.invalidate("credentials");
    }
    return credential;
  }

  current(credential, epoch) { return this.sync() === credential && this.epoch === epoch; }

  async refresh() {
    const credential = this.sync();
    if (!credential) return;
    let epoch = this.epoch;
    const activity = this.activity;
    let serial = ++this.serial;
    try {
      const state = await this.call("/api/facilitator/state", {cache: "no-store"});
      if (!this.current(credential, epoch) || serial !== this.serial || activity !== this.activity) return;
      if (state.clock.run_id !== state.controller.run_id || state.readiness.run_id !== state.controller.run_id) throw new Error("Inconsistent run snapshot");
      if (this.runId && state.controller.run_id !== this.runId) {
        this.invalidate("run");
        // This accepted snapshot owns the new context, including render failure.
        epoch = this.epoch;
        serial = this.serial;
      }
      this.runId = state.controller.run_id;
      this.role = state.principal_role;
      this.state = state;
      this.changed();
    } catch (error) {
      if (!this.current(credential, epoch) || serial !== this.serial || activity !== this.activity) return;
      if (error.status === 401 || error.status === 403) this.invalidate("credentials");
      else { this.state = null; this.cleared("unavailable"); this.changed(); }
    }
  }

  can(action, body) {
    this.sync();
    if (action === "stop") return !this.stopBusy && CONTROL_ROLES.has(this.role) && Boolean(this.runId)
      && (!this.state || this.state.controller.state !== "completed");
    return !this.busy && !this.stopBusy && permitted(this.state, action, body);
  }

  async command(action, body) {
    const credential = this.sync();
    if (!credential || !this.can(action, body)) return null;
    const runId = this.runId;
    const epoch = this.epoch;
    const emergency = action === "stop";
    const commandSerial = ++this.commandSerial;
    this.activity += 1;
    this.serial += 1;
    this.state = null;
    if (emergency) this.stopBusy = true; else this.busy = true;
    this.changed();
    try {
      const result = await this.call(`/api/facilitator/${action}`, {method: "POST", cache: "no-store",
        headers: {"X-Exercise-Run-ID": runId}, body: body === undefined ? undefined : JSON.stringify(body)});
      if (!this.current(credential, epoch) || this.runId !== runId || commandSerial !== this.commandSerial) return null;
      return result;
    } catch (error) {
      if (!this.current(credential, epoch) || this.runId !== runId || commandSerial !== this.commandSerial) return null;
      this.cleared("unavailable");
      if (error.status === 401 || error.status === 403) this.invalidate("credentials");
      // These controls are not idempotent: inspect, never automatically repeat them.
      throw new Error("Control not confirmed. Refresh and inspect the run before acting again; preserve evidence for faults.");
    } finally {
      // Release the actual request's slot even if its actor/run is now obsolete.
      // A GET issued before either overlapping request settles is not authority.
      this.sync();
      if (emergency) this.stopBusy = false; else this.busy = false;
      this.activity += 1;
      this.serial += 1;
      this.state = null;
      this.changed();
    }
  }

  async exportEvents(format) {
    const credential = this.sync();
    if (!this.state || !["jsonl", "csv"].includes(format)) return null;
    const runId = this.runId;
    const epoch = this.epoch;
    try {
      const payload = await this.call(`/api/facilitator/exports/events.${format}`, {
        cache: "no-store", rawText: true, headers: {"X-Exercise-Run-ID": runId},
      });
      return this.current(credential, epoch) && this.runId === runId ? {runId, payload} : null;
    } catch (error) {
      if (!this.current(credential, epoch)) return null;
      if ([401, 403].includes(error.status)) this.invalidate("credentials");
      throw new Error("Event export failed. Refresh and inspect the run; no file was saved.");
    }
  }
}

function text(tag, value, className = "") {
  const node = document.createElement(tag);
  node.textContent = value;
  node.className = className;
  return node;
}

export function renderOperations(state) {
  const readiness = document.querySelector("#local-readiness");
  const clock = document.querySelector("#clock-health");
  readiness.replaceChildren(); clock.replaceChildren();
  if (!state) {
    readiness.append(text("p", "No authorized local readiness snapshot. Refresh or reconnect.", "empty"));
    clock.append(text("p", "Clock status unavailable. Do not assume automatic delivery is healthy.", "empty"));
    return;
  }
  const report = state.readiness;
  const preplay = state.controller.state === "ready";
  readiness.append(text("h3", preplay ? report.ready_to_start ? "Locally prepared" : report.ready_to_prepare ? "Local baselines match · Prepare next" : "Local preparation blocked"
    : "Pre-play gate is not applicable during or after play"));
  if (preplay) {
    for (const check of report.checks) readiness.append(text("p", `${check.check_id.replaceAll("_", " ")}: ${check.passed ? "matched" : check.code.replaceAll("_", " ")}`, check.passed ? "muted" : "ops-blocker"));
  }
  readiness.append(text("p", "Local checks only. VM targets, Splunk, DNS/NTP, snapshots, staff access and admission sign-off are not verified here.", "ops-warning"));
  const health = state.clock;
  clock.append(text("h3", `Delivery clock: ${health.status.replaceAll("_", " ")}`),
    text("p", `Heartbeat age: ${health.heartbeat_age_seconds === null ? "not available" : `${health.heartbeat_age_seconds}s`} · stale after ${health.stale_after_seconds}s · ${health.successful_ticks} successful ticks`, "muted"));
  if (!CLOCK_OK.has(health.status)) clock.append(text("p", "Keep play stopped. Preserve evidence before reset/VM restoration; repair the cause and recheck local and external readiness. Inspection alone does not stop or repair the clock.", "ops-warning"));
  if (health.status === "unmonitored") clock.append(text("p", "Manual developer/CLI mode, not proof of supervised delivery.", "ops-warning"));
  if (health.fault_code) clock.append(text("p", `Fault: ${health.fault_code} · cleanup ${health.cleanup_complete === true ? "completed" : "not confirmed"} · audit ${health.fault_audit_persisted === true ? "persisted" : "not confirmed"}`, "ops-blocker"));
}

export function saveText(payload, filename, type) {
  const url = URL.createObjectURL(new Blob([payload], {type}));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename.replace(/[^a-zA-Z0-9._-]/g, "_");
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
