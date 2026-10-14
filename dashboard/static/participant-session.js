"use strict";

import {api, token} from "./common.js";

// A run header is a concurrency guard, never a replacement for server authorization.
export class ParticipantSession {
  constructor({call = api, readToken = token, cleared = () => {}, changed = () => {}} = {}) {
    Object.assign(this, {call, readToken, cleared, changed});
    this.credential = "";
    this.epoch = this.serial = 0;
    this.runId = this.state = null;
    this.pendingWrite = null;
    this.activity = 0;
    this.reads = new Map();
  }

  invalidate(reason) {
    this.epoch += 1;
    this.serial += 1;
    this.runId = this.state = null;
    this.activity += 1;
    this.reads.clear();
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
    return Boolean(credential) && this.sync() === credential && this.epoch === epoch;
  }

  canWrite() {
    return !this.pendingWrite && Boolean(this.state && this.runId && this.credential);
  }

  async refresh() {
    const credential = this.sync();
    if (!credential) return null;
    const epoch = this.epoch;
    const serial = ++this.serial;
    try {
      const state = await this.call("/api/participant/state", {cache: "no-store"});
      if (!this.current(credential, epoch) || serial !== this.serial) return null;
      if (!state || typeof state.run_id !== "string" || !state.run_id.trim() ||
          state.run_id !== state.run_id.trim() || state.run_id.length > 128 || /[\x00-\x1f]/.test(state.run_id) ||
          !["ready", "running", "paused", "stopped", "completed"].includes(state.state) ||
          !Number.isFinite(state.elapsed_seconds) || state.elapsed_seconds < 0 || !Array.isArray(state.injects) ||
          typeof state.cloud_enabled !== "boolean" || typeof state.impact_enabled !== "boolean") {
        throw new Error("Exercise state unavailable.");
      }
      if (this.runId && this.runId !== state.run_id) this.invalidate("run");
      this.runId = state.run_id;
      this.state = state;
      this.changed();
      return state;
    } catch (error) {
      if (!this.current(credential, epoch) || serial !== this.serial) return null;
      this.state = null; // Keep drafts on a transient failure, but remove write authority.
      if ([401, 403].includes(error.status)) this.invalidate("credentials");
      this.changed();
      throw error;
    }
  }

  context() {
    const credential = this.sync();
    if (!credential || !this.state || !this.runId) {
      throw new Error("Refresh the current exercise before acting.");
    }
    return {credential, epoch: this.epoch, runId: this.runId};
  }

  async read(path, {runScoped = true} = {}) {
    const {credential, epoch, runId} = this.context();
    const owner = {activity: this.activity};
    this.reads.set(path, owner);
    const current = () => this.current(credential, epoch) && this.runId === runId &&
      this.activity === owner.activity && this.reads.get(path) === owner;
    let result;
    try {
      result = await this.call(path, {cache: "no-store"});
    } catch (error) {
      if (!current()) return null;
      if ([401, 403].includes(error.status)) this.invalidate("credentials");
      throw error;
    }
    if (!current()) return null;
    if (runScoped && (!result || result.run_id !== runId)) {
      this.invalidate("run");
      throw new Error("Exercise changed. Refresh and inspect the new run.");
    }
    return result;
  }

  async write(path, options = {}) {
    this.sync();
    if (this.pendingWrite) throw new Error("Another action is pending. Wait for its result and inspect before submitting again.");
    const {credential, epoch, runId} = this.context();
    this.pendingWrite = {credential, epoch, runId};
    this.serial += 1;
    this.activity += 1;
    this.reads.clear();
    this.state = null;
    this.changed();
    try {
      const result = await this.call(path, {...options, method: "POST", cache: "no-store",
        headers: {...options.headers, "X-Exercise-Run-ID": runId}});
      if (!this.current(credential, epoch) || this.runId !== runId) return null;
      if (result && Object.hasOwn(result, "run_id") && result.run_id !== runId) {
        this.invalidate("run");
        throw new Error("Exercise changed; response did not confirm the inspected run.");
      }
      return result;
    } catch (error) {
      if (!this.current(credential, epoch) || this.runId !== runId) return null;
      if ([401, 403].includes(error.status)) this.invalidate("credentials");
      // Never repeat an uncertain mutation automatically, even if the clock advanced.
      throw new Error(`${error.message} Refresh and inspect the run before acting again; the request was not confirmed.`);
    } finally {
      // Invalidation never frees a still-pending server request, even across accounts/runs.
      this.pendingWrite = null;
      this.serial += 1;
      this.activity += 1;
      this.reads.clear();
      this.state = null;
      this.changed();
    }
  }
}
