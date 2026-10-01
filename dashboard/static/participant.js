"use strict";

import {api, clearNotice, connect, formatElapsed, idempotency, notify, setStatus, token} from "/static/common.js";

const notice = document.querySelector("#notice");
const tokenInput = document.querySelector("#token-input");

function renderInjects(injects) {
  const container = document.querySelector("#injects");
  container.replaceChildren();
  if (!injects.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No injects have been delivered yet.";
    container.append(empty);
    return;
  }
  for (const inject of injects) {
    const article = document.createElement("article");
    article.className = "inject";
    const id = document.createElement("strong");
    id.textContent = inject.msel_id;
    const message = document.createElement("p");
    message.textContent = inject.message;
    const time = document.createElement("time");
    time.textContent = new Date(inject.timestamp).toLocaleString();
    article.append(id, message, time);
    container.append(article);
  }
}

async function refresh() {
  if (!token()) return;
  try {
    const state = await api("/api/participant/state");
    setStatus(document.querySelector("#run-state"), state.state);
    document.querySelector("#elapsed").textContent = formatElapsed(state.elapsed_seconds);
    document.querySelector("#inject-count").textContent = state.injects.length;
    document.querySelector("#run-id").textContent = state.run_id;
    renderInjects(state.injects);
  } catch (error) {
    notify(notice, error.message, "error");
  }
}

document.querySelector("#connect").addEventListener("click", () => {
  clearNotice(notice);
  try {
    connect(tokenInput, refresh);
  } catch (error) {
    notify(notice, error.message, "error");
  }
});
document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelector("#load-directory").addEventListener("click", async () => {
  const button = document.querySelector("#load-directory");
  button.disabled = true;
  try {
    const profiles = await api("/api/participant/directory");
    const container = document.querySelector("#directory");
    container.replaceChildren();
    for (const profile of profiles) {
      const card = document.createElement("article");
      card.className = "inject";
      const title = document.createElement("strong");
      title.textContent = `${profile.display_name} · ${profile.title}`;
      const context = document.createElement("p");
      context.textContent = `${profile.department} · Account: ${profile.username} (configured) · Manager: ${profile.manager || "unknown"}`;
      const contacts = document.createElement("p");
      contacts.textContent = profile.email_candidates.length
        ? `Inferred contact candidates: ${profile.email_candidates.map((item) => `${item.address} (${item.confidence})`).join(", ")}`
        : "Contact email unknown; no verified candidate provided.";
      card.append(title, context, contacts);
      container.append(card);
    }
  } catch (error) {
    notify(notice, error.message, "error");
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#actions").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  clearNotice(notice);
  button.disabled = true;
  try {
    const target = button.parentElement.querySelector("input").value.trim();
    if (!target) throw new Error("Enter the evidence-supported target ID first.");
    const result = await api("/api/participant/actions", {
      method: "POST",
      body: JSON.stringify({
        action_id: button.dataset.action,
        target_type: button.dataset.type,
        target_id: target,
        idempotency_key: idempotency(button.dataset.action),
      }),
    });
    notify(notice, result.message || "Action completed and recorded.");
  } catch (error) {
    notify(notice, error.message, "error");
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#dp1-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearNotice(notice);
  const form = new FormData(event.currentTarget);
  const references = form.getAll("reference");
  const sources = form.getAll("source");
  try {
    const result = await api("/api/participant/checkpoints/dp1", {
      method: "POST",
      body: JSON.stringify({
        affected_identity: form.get("identity"),
        classification: form.get("classification"),
        evidence: references.map((reference, index) => ({reference_id: reference, source: sources[index]})),
      }),
    });
    notify(notice, result.passed ? "Assessment accepted. Continue containment." : result.reason, result.passed ? "success" : "error");
  } catch (error) {
    notify(notice, error.message, "error");
  }
});

if (token()) refresh();
setInterval(refresh, 10000);
