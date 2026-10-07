"use strict";

import {api, token} from "./common.js";

// A run header is a concurrency guard, never a replacement for server authorization.
export class ParticipantSession {
  constructor({call = api, readToken = token, cleared = () => {}} = {}) {
    Object.assign(this, {call, readToken, cleared});
    this.credential = "";
    this.epoch = this.serial = 0;
    this.runId = this.state = null;
  }

  invalidate(reason) {
    this.epoch += 1;
    this.serial += 1;
    this.runId = this.state = null;
    this.cleared(reason);
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
      const state = await this.call("/api/participant/state", {cache: "no-store"});
      if (!this.current(credential, epoch) || serial !== this.serial) return null;
      if (typeof state.run_id !== "string" || !state.run_id) throw new Error("Exercise state unavailable.");
      if (this.runId && this.runId !== state.run_id) this.invalidate("run");
      this.runId = state.run_id;
      this.state = state;
      return state;
    } catch (error) {
      if (!this.current(credential, epoch) || serial !== this.serial) return null;
      this.state = null; // Keep drafts on a transient failure, but remove write authority.
      if ([401, 403].includes(error.status)) this.invalidate("credentials");
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
    let result;
    try {
      result = await this.call(path, {cache: "no-store"});
    } catch (error) {
      if (!this.current(credential, epoch) || this.runId !== runId) return null;
      if ([401, 403].includes(error.status)) this.invalidate("credentials");
      throw error;
    }
    if (!this.current(credential, epoch) || this.runId !== runId) return null;
    if (runScoped && result.run_id !== runId) {
      this.invalidate("run");
      throw new Error("Exercise changed. Refresh and inspect the new run.");
    }
    return result;
  }

  async write(path, options = {}) {
    const {credential, epoch, runId} = this.context();
    try {
      const result = await this.call(path, {...options, method: "POST", cache: "no-store",
        headers: {...options.headers, "X-Exercise-Run-ID": runId}});
      if (!this.current(credential, epoch) || this.runId !== runId) return null;
      this.serial += 1; // Discard reads issued before this write completed.
      return result;
    } catch (error) {
      if (!this.current(credential, epoch) || this.runId !== runId) return null;
      this.serial += 1;
      this.state = null;
      if ([401, 403].includes(error.status)) this.invalidate("credentials");
      // Never repeat an uncertain mutation automatically, even if the clock advanced.
      throw new Error(`${error.message} Refresh and inspect the run before acting again; the request was not confirmed.`);
    }
  }
}
