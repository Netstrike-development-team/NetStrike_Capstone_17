"use strict";

import {api, clearNotice, connect, formatElapsed, notify, setStatus, token} from "/static/common.js";

const signals = new Map();
let runId = null;
let actorToken = null;
let cursor = 0;
let busy = false;
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
  document.querySelector("#signal-summary").textContent = `${visible.length} matching signals · Up to 500 recent signals retained in this view · Read-only`;
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

async function refresh() {
  if (!token() || busy) return;
  busy = true;
  const button = document.querySelector("#refresh");
  button.disabled = true;
  try {
    if (actorToken !== token()) {
      actorToken = token();
      signals.clear(); cursor = 0; runId = null;
      render();
    }
    let changed = false;
    for (let page = 0; page < 10; page += 1) {
      const result = await api(`/api/participant/evidence?after_sequence=${cursor}&limit=100`);
      if (actorToken !== token()) {
        signals.clear(); cursor = 0; render();
        break;
      }
      if (runId && runId !== result.run_id) {
        signals.clear(); cursor = 0; runId = result.run_id; changed = true;
        continue;
      }
      runId = result.run_id;
      document.querySelector("#run-id").textContent = result.run_id;
      document.querySelector("#elapsed").textContent = formatElapsed(result.elapsed_seconds);
      setStatus(document.querySelector("#run-state"), result.state);
      for (const signal of result.signals) {
        if (!signals.has(signal.event_id)) changed = true;
        signals.set(signal.event_id, signal);
      }
      cursor = result.next_sequence;
      if (!result.has_more) break;
    }
    while (signals.size > 500) signals.delete(signals.keys().next().value);
    if (changed || signals.size === 0) render();
    clearNotice(notice);
  } catch (error) {
    signals.clear(); cursor = 0; render();
    notify(notice, error.message, "error");
  } finally { busy = false; button.disabled = false; }
}

document.querySelector("#connect").addEventListener("click", () => {
  try { connect(document.querySelector("#token-input"), refresh); }
  catch (error) { notify(notice, error.message, "error"); }
});
document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelector("#category").addEventListener("change", render);
document.querySelector("#search").addEventListener("input", render);
if (token()) refresh();
setInterval(refresh, 3000);
