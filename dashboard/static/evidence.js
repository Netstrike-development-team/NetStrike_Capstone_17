"use strict";

import {api, clearNotice, connect, formatElapsed, notify, setStatus, token} from "/static/common.js";

const signals = new Map();
let runId = null;
let actorToken = null;
let cursor = 0;
let generation = 0;
let active = null;
let backlog = false;
const notice = document.querySelector("#notice");
const labels = {identity: "Identity / helpdesk", endpoint: "Endpoint / directory", cloud: "Mock cloud", recovery: "Impact / recovery", response: "My response"};

function text(tag, value, className = "") {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
}

function render() {
  const loaded = [...signals.values()].sort((a, b) => b.sequence - a.sequence);
  const category = document.querySelector("#category").value;
  const query = document.querySelector("#search").value.trim().toLowerCase();
  const visible = loaded.filter((signal) => (category === "all" || signal.category === category)
    && (!query || JSON.stringify(signal).toLowerCase().includes(query)));
  document.querySelector("#signal-count").textContent = loaded.length;
  document.querySelector("#source-count").textContent = new Set(loaded.map((signal) => signal.source)).size;
  document.querySelector("#response-count").textContent = loaded.filter((signal) => signal.category === "response").length;
  document.querySelector("#latest-sequence").textContent = loaded[0] ? `#${loaded[0].sequence}` : "—";
  document.querySelector("#signal-summary").textContent = `${visible.length} matching signals · Up to 500 recent signals retained in this view · Read-only${backlog ? " · More evidence pages remain; refresh to continue" : ""}`;
  const container = document.querySelector("#signals");
  container.replaceChildren();
  if (!visible.length) {
    container.append(text("div", "No matching evidence received. Change the filter or advance the exercise.", "empty"));
  }
  for (const signal of visible) {
    const card = document.createElement("article");
    card.className = `signal-card signal-${signal.category}`;
    card.dataset.eventId = signal.event_id;
    const meta = document.createElement("div");
    meta.className = "signal-meta";
    meta.append(text("span", labels[signal.category] || signal.category, "signal-category"),
      text("span", `#${signal.sequence} · ${signal.source}`),
      text("span", signal.dry_run ? "PREVIEW — no execution" : signal.outcome, "signal-outcome"));
    card.append(meta, text("h3", signal.message), text("p", signal.event_type, "signal-type"));
    const facts = document.createElement("div");
    facts.className = "signal-facts";
    if (signal.actor_id) facts.append(text("span", `Actor: ${signal.actor_id}`));
    if (signal.target_id) facts.append(text("span", `${signal.target_type}: ${signal.target_id}`));
    for (const [key, value] of Object.entries(signal.facts)) {
      facts.append(text("span", `${key.replaceAll("_", " ")}: ${value}`));
    }
    const footer = document.createElement("div");
    footer.className = "signal-footer";
    const reference = document.createElement("input");
    reference.readOnly = true;
    reference.value = signal.event_id;
    reference.setAttribute("aria-label", "Evidence event ID");
    footer.append(reference, text("time", new Date(signal.timestamp).toLocaleString()));
    card.append(facts, footer);
    container.append(card);
  }
}

function clearView({filters = true} = {}) {
  signals.clear(); cursor = 0; runId = null; backlog = false;
  document.querySelector("#run-id").textContent = "No run connected";
  document.querySelector("#elapsed").textContent = "00:00:00";
  setStatus(document.querySelector("#run-state"), "disconnected");
  if (filters) {
    document.querySelector("#category").value = "all";
    document.querySelector("#search").value = "";
  }
  render();
}

function synchronize(reconnect = false) {
  if (!reconnect && actorToken === token()) return;
  generation += 1;
  actorToken = token();
  if (active) active.abort();
  active = null;
  document.querySelector("#refresh").disabled = false;
  clearView();
  clearNotice(notice);
}

function validatePage(result, after) {
  if (typeof result.run_id !== "string" || !result.run_id
      || !Array.isArray(result.signals) || result.signals.length > 100
      || typeof result.has_more !== "boolean"
      || typeof result.state !== "string"
      || !Number.isFinite(result.elapsed_seconds) || result.elapsed_seconds < 0
      || !Number.isSafeInteger(result.next_sequence) || result.next_sequence < after) {
    throw new Error("Evidence page unavailable. Refresh to inspect the current exercise.");
  }
  let sequence = after;
  for (const signal of result.signals) {
    if (!Number.isSafeInteger(signal.sequence) || signal.sequence <= sequence
        || typeof signal.event_id !== "string" || !signal.event_id) {
      throw new Error("Evidence page ordering unavailable. Refresh to inspect the current exercise.");
    }
    sequence = signal.sequence;
  }
  if (result.next_sequence !== sequence || (result.has_more && !result.signals.length)) {
    throw new Error("Evidence page cursor unavailable. Refresh to inspect the current exercise.");
  }
}

async function refresh({reconnect = false} = {}) {
  // Synchronize BEFORE the busy guard: old receipts must disappear immediately,
  // even if an obsolete fetch ignores cancellation or takes a long time to fail.
  synchronize(reconnect);
  if (!actorToken || active) return;
  const credential = actorToken;
  const epoch = generation;
  const controller = new AbortController();
  active = controller;
  const current = () => credential === token() && epoch === generation;
  const button = document.querySelector("#refresh");
  button.disabled = true;
  try {
    for (let page = 0; page < 10; page += 1) {
      const after = cursor;
      const result = await api(`/api/participant/evidence?after_sequence=${after}&limit=100`,
        {cache: "no-store", signal: controller.signal});
      if (!current()) {
        synchronize();
        return;
      }
      if (!result || typeof result.run_id !== "string" || !result.run_id) {
        throw new Error("Evidence run unavailable. Refresh to inspect the current exercise.");
      }
      if (runId && runId !== result.run_id) {
        clearView();
        runId = result.run_id;
        backlog = true;
        continue;
      }
      validatePage(result, after);
      runId = result.run_id;
      document.querySelector("#run-id").textContent = result.run_id;
      document.querySelector("#elapsed").textContent = formatElapsed(result.elapsed_seconds);
      setStatus(document.querySelector("#run-state"), result.state);
      for (const signal of result.signals) {
        signals.set(signal.event_id, signal);
      }
      cursor = result.next_sequence;
      backlog = result.has_more;
      while (signals.size > 500) signals.delete(signals.keys().next().value);
      if (!backlog) break;
    }
    render();
    clearNotice(notice);
  } catch (error) {
    if (!current()) { synchronize(); return; }
    clearView({filters: false});
    notify(notice, error.message, "error");
  } finally {
    // An obsolete finally must not unlock a new credential's in-flight request.
    if (active === controller) { active = null; button.disabled = false; }
  }
}

document.querySelector("#connect").addEventListener("click", () => {
  try { return connect(document.querySelector("#token-input"), () => refresh({reconnect: true})); }
  catch (error) { notify(notice, error.message, "error"); }
});
document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelector("#category").addEventListener("change", () => { synchronize(); render(); });
document.querySelector("#search").addEventListener("input", () => { synchronize(); render(); });
if (token()) refresh();
setInterval(refresh, 3000);
