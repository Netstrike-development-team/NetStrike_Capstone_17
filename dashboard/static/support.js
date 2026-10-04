"use strict";

import {api, idempotency, token} from "./common.js";

const LIVE = new Set(["running", "paused"]);
const LEARNERS = new Set(["incident_lead", "soc_analyst", "identity_responder", "endpoint_responder", "cloud_responder"]);
export const OBJECTIVES = [
  ["LO1", "Triage the identity incident"], ["LO2", "Reconstruct the intrusion"],
  ["LO3", "Contain identity and endpoint access"],
  ["LO4", "Determine and contain cloud data exposure"], ["LO5", "Recover and communicate"],
];

// No tokens, questions, reply drafts or retry payloads are persisted by this module.
export class SupportSession {
  constructor({staff = false, observer = false, readToken = token, call = api,
    makeKey = idempotency, changed = () => {}, cleared = () => {}} = {}) {
    Object.assign(this, {staff, observer, readToken, call, makeKey, changed, cleared});
    this.credential = "";
    this.generation = 0;
    this.readSerial = 0;
    this.reset(false);
  }

  reset(notify = true) {
    this.generation += 1;
    this.readSerial += 1;
    this.snapshot = null;
    this.contextRun = null;
    this.operation = null;
    this.busy = false;
    this.message = "Connect to load exercise support.";
    if (notify) { this.cleared(); this.changed(); }
  }

  syncCredential() {
    const credential = this.readToken();
    if (credential !== this.credential) {
      this.credential = credential;
      this.reset();
    }
    return credential;
  }

  current(credential, generation) {
    return this.readToken() === credential && this.generation === generation;
  }

  async refresh() {
    const credential = this.syncCredential();
    if (!credential) return;
    const generation = this.generation;
    const serial = ++this.readSerial;
    try {
      const snapshot = await this.call(this.staff ? "/api/facilitator/support" : "/api/participant/support",
        {cache: "no-store"});
      if (!this.current(credential, generation) || serial !== this.readSerial) return;
      if (this.contextRun && this.contextRun !== snapshot.run_id) this.reset();
      this.contextRun = snapshot.run_id;
      this.snapshot = snapshot;
      this.message = this.operation ? "Delivery uncertain. Retry sends the exact same message, not a new one."
        : `${snapshot.run_id} · ${snapshot.run_state} · ${snapshot.requests.length} ${this.staff ? "requests" : "your requests"}`;
      this.changed();
    } catch (error) {
      if (!this.current(credential, generation) || serial !== this.readSerial) return;
      this.snapshot = null;
      this.message = "Support unavailable. Refresh or reconnect before continuing.";
      // Never leave another actor's transcript on screen after authorization failure.
      if (error.status === 401 || error.status === 403) this.reset();
      this.cleared();
      this.message = "Support unavailable. Refresh or reconnect before continuing.";
      this.changed();
    }
  }

  canWrite(kind = "clarification") {
    const state = this.snapshot;
    if (!state || this.observer) return false;
    if (this.staff) {
      return ["facilitator", "technical_operator"].includes(state.principal_role)
        && (state.principal_role !== "technical_operator" || kind === "platform_issue")
        && (LIVE.has(state.run_state) || state.run_state === "stopped" && kind === "platform_issue");
    }
    return LEARNERS.has(state.principal_role) && LIVE.has(state.run_state)
      && state.requests.length < 10 && !state.requests.some((request) => !request.response);
  }

  async submit(fields) {
    const credential = this.syncCredential();
    if (this.busy || !credential || !this.snapshot || this.observer) return false;
    if (!this.operation) {
      if (!this.canWrite(fields.kind)) return false;
      if (this.staff && !this.snapshot.requests.some((item) => item.request_id === fields.request_id && !item.response)) return false;
      this.operation = {
        ...fields, run_id: this.snapshot.run_id,
        idempotency_key: this.makeKey(this.staff ? "support-reply" : "support-question"),
      };
      // Freeze a copy: later form edits must never change an uncertain retry.
      this.operation = JSON.parse(JSON.stringify(this.operation));
    }
    const generation = this.generation;
    const operation = this.operation;
    this.busy = true;
    this.message = "Sending and recording the message…";
    this.changed();
    try {
      const receipt = await this.call(this.staff ? "/api/facilitator/support/replies" : "/api/participant/support", {
        method: "POST", body: JSON.stringify(operation), cache: "no-store",
      });
      if (!this.current(credential, generation) || this.contextRun !== operation.run_id) return false;
      if (receipt.run_id !== operation.run_id) throw new Error("Unexpected support receipt");
      this.operation = null;
      this.snapshot = null;
      this.cleared();
      this.message = receipt.replayed ? "Existing message confirmed; no duplicate created." : "Message recorded.";
      // Invalidate GETs issued before this successful write.
      this.readSerial += 1;
      return true;
    } catch (error) {
      if (!this.current(credential, generation) || this.contextRun !== operation.run_id) return false;
      if (error.status >= 400 && error.status < 500) {
        this.operation = null;
        if (error.status === 401 || error.status === 403) {
          this.reset();
        }
        this.message = "Message rejected. Refresh the queue and check the run, permissions or limits before trying again.";
      } else {
        this.message = "Delivery uncertain. Retry sends the exact same message, not a new one.";
      }
      return false;
    } finally {
      if (this.current(credential, generation)) {
        this.busy = false;
        this.changed();
      }
    }
  }
}

function element(tag, value, className = "") {
  const node = document.createElement(tag);
  node.textContent = value;
  node.className = className;
  return node;
}

export function renderThreads(container, snapshot, staff) {
  container.replaceChildren();
  if (!snapshot?.requests.length) {
    container.append(element("p", snapshot ? "No help requests yet." : "No authorized support queue loaded.", "empty"));
    return;
  }
  for (const request of snapshot.requests) {
    const card = element("article", "", "support-thread");
    card.append(element("h3", `${request.objective_id} · ${request.response ? "Answered" : "Awaiting staff reply"}`));
    if (staff) card.append(element("p", `${request.requester_id} · ${request.requester_role.replaceAll("_", " ")}`, "muted"));
    card.append(element("p", request.question, "support-prose"),
      element("p", `Requested ${request.requested_at} · exercise ${request.elapsed_seconds}s`, "muted"));
    if (staff) card.append(element("code", request.request_id));
    if (request.response) {
      const reply = element("section", "", "support-reply");
      reply.append(element("h4", request.response.kind.replaceAll("_", " ")),
        element("p", request.response.text, "support-prose"),
        element("p", `Replied ${request.response.responded_at} · ${request.response.objective_ids.join(", ")}`, "muted"));
      if (staff) reply.append(element("p", `${request.response.responder_id} · ${request.response.responder_role.replaceAll("_", " ")}`, "muted"),
        element("code", request.response.event_id));
      card.append(reply);
    }
    container.append(card);
  }
}

export function mountSupport({staff = false, observer = false, sessionOptions = {}} = {}) {
  const form = document.querySelector("#support-form");
  const list = document.querySelector("#support-threads");
  const summary = document.querySelector("#support-summary");
  const title = document.querySelector("#support-title");
  const button = document.querySelector("#support-send");
  let rendered = "";
  let platformPolicy = false;
  const session = new SupportSession({...sessionOptions, staff, observer,
    cleared: () => { form?.reset(); rendered = ""; list.replaceChildren(); },
    changed: () => {
      summary.textContent = session.message;
      const snapshot = session.snapshot;
      const waiting = snapshot?.requests.filter((item) => !item.response).length || 0;
      if (title) title.textContent = (observer ? "Human assistance · Read-only" : staff
        ? "Participant help requests · Staff only" : "Ask exercise staff for help") + (waiting ? ` · ${waiting} awaiting reply` : "");
      const signature = JSON.stringify(snapshot);
      if (signature !== rendered) {
        renderThreads(list, snapshot, staff);
        rendered = signature;
      }
      if (!form) return;
      if (staff) {
        const select = form.elements.request_id;
        const prior = select.value;
        const pending = snapshot?.requests.filter((item) => !item.response) || [];
        const ids = pending.map((item) => item.request_id).join("|");
        if (select.dataset.requests !== ids) {
          select.replaceChildren(new Option("Select an unanswered request", ""));
          for (const item of pending) select.add(new Option(`${item.requester_id} · ${item.objective_id} · ${item.question.slice(0, 65)}`, item.request_id));
          if (pending.some((item) => item.request_id === prior)) select.value = prior;
          else if (prior && !session.operation) { form.reset(); }
          select.dataset.requests = ids;
        }
        const platformOnly = snapshot?.principal_role === "technical_operator" || snapshot?.run_state === "stopped";
        if (platformOnly && !platformPolicy && !session.operation) {
          // Never silently relabel an existing coaching draft as a platform explanation.
          const request = select.value;
          form.reset();
          select.value = request;
        }
        platformPolicy = platformOnly;
        for (const option of form.elements.kind.options) option.disabled = platformOnly && option.value !== "platform_issue";
        if (platformOnly) form.elements.kind.value = "platform_issue";
      }
      const mayWrite = session.canWrite(staff ? form.elements.kind.value : undefined);
      const retry = Boolean(session.operation);
      for (const control of form.querySelectorAll("input, select, textarea")) control.disabled = session.busy || retry || !mayWrite;
      button.disabled = session.busy || !snapshot || observer || (!retry && (!mayWrite || staff && !form.elements.request_id.value));
      button.textContent = session.busy ? "Sending…" : retry ? "Retry same message" : staff ? "Record and send reply" : "Send help request";
    },
  });
  if (form) {
    if (!staff) for (const [id, title] of OBJECTIVES) form.elements.objective_id.add(new Option(`${id} · ${title}`, id));
    form.addEventListener("change", () => session.changed());
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      let fields = {};
      if (!session.operation) {
        if (!form.reportValidity()) return;
        fields = staff ? {
          request_id: form.elements.request_id.value, kind: form.elements.kind.value,
          objective_ids: Array.from(form.querySelectorAll('input[name="objective_ids"]:checked'), (input) => input.value),
          message: form.elements.message.value.trim(),
        } : {objective_id: form.elements.objective_id.value, message: form.elements.message.value.trim()};
        if (!fields.message || staff && !fields.objective_ids.length) {
          summary.textContent = "Enter a message and select the affected learning objective(s).";
          return;
        }
      }
      const generation = session.generation;
      const credential = session.readToken();
      const succeeded = await session.submit(fields);
      if (!session.current(credential, generation)) return;
      const message = session.message;
      if (!session.operation) {
        await session.refresh();
        if (!session.current(credential, generation)) return;
        summary.textContent = message;
      }
      if (succeeded) summary.textContent = message;
    });
  }
  document.querySelector("#connect").addEventListener("click", () => { session.reset(); session.refresh(); });
  document.querySelector("#support-refresh").addEventListener("click", () => session.refresh());
  document.querySelector("#refresh").addEventListener("click", () => session.refresh());
  session.refresh();
  const interval = setInterval(() => session.refresh(), 5000);
  window.addEventListener("pagehide", () => { clearInterval(interval); session.reset(); });
  return session;
}
