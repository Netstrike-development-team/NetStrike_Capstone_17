"use strict";

const views = new Map(
  ["sign_in", "failure", "locked", "mfa", "success", "suspicious_session"]
    .map((name) => [name, document.querySelector(`#view-${name}`)])
);
const liveStatus = document.querySelector("#live-status");
const credentialInput = document.querySelector("#credential");
let currentState = null;
let countdownTimer = null;
let lastSignature = null;
let busy = false;
let retrying = false;
let mutationVersion = 0;
let loadNumber = 0;
let loading = false;

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(typeof payload.detail === "string" ? payload.detail : "The exercise service rejected the request.");
  }
  return payload;
}

function announce(message) {
  liveStatus.textContent = "";
  window.setTimeout(() => { liveStatus.textContent = message; }, 10);
}

function focusView(view) {
  const heading = view.querySelector("h1");
  if (heading) {
    heading.tabIndex = -1;
    heading.focus();
  }
}

function startCountdown(seconds) {
  window.clearInterval(countdownTimer);
  const element = document.querySelector("#mfa-seconds");
  let remaining = Math.max(0, Number(seconds) || 0);
  element.textContent = String(remaining);
  countdownTimer = window.setInterval(() => {
    remaining = Math.max(0, remaining - 1);
    element.textContent = String(remaining);
    if (remaining === 0) window.clearInterval(countdownTimer);
  }, 1000);
}

function renderSessions(sessions) {
  const container = document.querySelector("#session-list");
  container.replaceChildren();
  if (!sessions.length) {
    const empty = document.createElement("div");
    empty.className = "empty-session";
    empty.textContent = "No configured suspicious exercise sessions remain active.";
    container.append(empty);
    return;
  }
  for (const session of sessions) {
    const article = document.createElement("article");
    article.className = "session";
    const title = document.createElement("strong");
    title.textContent = session.label;
    const details = document.createElement("dl");
    for (const [label, value] of [
      ["Session ID", session.id],
      ["Location", session.location],
      ["Last seen", session.last_seen],
    ]) {
      const term = document.createElement("dt");
      term.textContent = label;
      const description = document.createElement("dd");
      description.textContent = value;
      details.append(term, description);
    }
    article.append(title, details);
    container.append(article);
  }
}

function render(state, {focus = true} = {}) {
  const signature = JSON.stringify([state.view, state.challenge?.id, state.message, state.exercise_state, state.scheduled_result?.outcome]);
  const changed = signature !== lastSignature;
  lastSignature = signature;
  currentState = state;
  if (state.challenge?.kind === "scheduled") retrying = false;
  window.clearInterval(countdownTimer);
  document.querySelector("#service-name").textContent = state.service_name;
  document.querySelector("#sign-in-title").textContent = state.heading;
  document.querySelector("#introduction").textContent = state.introduction;
  document.querySelector("#failure-message").textContent = state.message;
  document.querySelector("#locked-message").textContent = state.message;
  document.querySelector("#mfa-message").textContent = state.message;
  document.querySelector("#success-message").textContent = state.message;
  document.querySelector("#sessions-message").textContent = state.message;
  document.querySelector("#mfa-identity").textContent = state.display_name || "Synthetic user";

  const result = state.scheduled_result;
  const resultMessage = result ? `Scheduled request: ${result.outcome}. ${result.reason.replaceAll("_", " ")}.` : "Waiting for scheduled exercise requests.";
  const statusElement = document.querySelector("#scheduled-result");
  if (statusElement.textContent !== resultMessage) statusElement.textContent = resultMessage;
  if (!retrying || state.challenge?.kind === "scheduled") {
    for (const [name, element] of views) element.hidden = name !== state.view;
  }
  const active = views.get(state.view) || views.get("sign_in");
  if (state.view === "mfa" && state.challenge) {
    document.querySelector("#mfa-clock-note").textContent = state.challenge.kind === "scheduled" ? `Exercise clock: ${state.exercise_state}. Timeouts freeze while paused.` : "Local sign-in request.";
    if (state.challenge.kind === "scheduled") {
      document.querySelector("#mfa-seconds").textContent = String(state.challenge.expires_in_seconds);
    } else startCountdown(state.challenge.expires_in_seconds);
    const disabled = ["paused", "stopped", "completed"].includes(state.exercise_state);
    document.querySelector("#approve-mfa").disabled = disabled;
    document.querySelector("#deny-mfa").disabled = disabled;
  }
  if (state.view === "suspicious_session") renderSessions(state.sessions || []);
  if (changed) announce(state.message || `${state.service_name} is ready.`);
  if (focus) focusView(active);
}

async function loadState({focus = true} = {}) {
  if (loading) return;
  loading = true;
  const version = mutationVersion;
  const number = ++loadNumber;
  try {
    const state = await request("/api/sso/state");
    if (version === mutationVersion && number === loadNumber) render(state, {focus});
  } catch (error) {
    if (version !== mutationVersion || number !== loadNumber) return;
    announce(error.message);
    document.querySelector("#failure-message").textContent = error.message;
    for (const [name, element] of views) element.hidden = name !== "failure";
  } finally {
    loading = false;
  }
}

document.querySelector("#sign-in-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  busy = true;
  mutationVersion += 1;
  retrying = false;
  const form = new FormData(event.currentTarget);
  const body = JSON.stringify({
    username: String(form.get("username") || ""),
    credential: String(form.get("credential") || ""),
  });
  credentialInput.value = "";
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  try {
    render(await request("/api/sso/sign-in", {method: "POST", body}));
  } catch (error) {
    document.querySelector("#failure-message").textContent = error.message;
    for (const [name, element] of views) element.hidden = name !== "failure";
    announce(error.message);
    focusView(views.get("failure"));
  } finally {
    button.disabled = false;
    busy = false;
  }
});

for (const button of document.querySelectorAll("[data-return-sign-in]")) {
  button.addEventListener("click", () => {
    retrying = true;
    for (const [name, element] of views) element.hidden = name !== "sign_in";
    document.querySelector("#username").focus();
  });
}

async function decideMfa(decision) {
  if (!currentState?.challenge) return;
  busy = true;
  mutationVersion += 1;
  retrying = false;
  const scheduled = currentState.challenge.kind === "scheduled";
  document.querySelector("#approve-mfa").disabled = true;
  document.querySelector("#deny-mfa").disabled = true;
  try {
    render(await request(scheduled ? "/api/sso/scheduled-mfa" : "/api/sso/mfa", {
      method: "POST",
      headers: scheduled ? {Authorization: `Bearer ${document.querySelector("#mfa-access-token").value.trim()}`} : {},
      body: JSON.stringify({challenge_id: currentState.challenge.id, decision}),
    }));
  } catch (error) {
    announce(error.message);
    await loadState();
  } finally {
    busy = false;
    const disabled = ["paused", "stopped", "completed"].includes(currentState?.exercise_state);
    document.querySelector("#approve-mfa").disabled = disabled;
    document.querySelector("#deny-mfa").disabled = disabled;
  }
}

document.querySelector("#approve-mfa").addEventListener("click", () => decideMfa("approve"));
document.querySelector("#deny-mfa").addEventListener("click", () => decideMfa("deny"));
document.querySelector("#review-sessions").addEventListener("click", async () => {
  busy = true;
  mutationVersion += 1;
  try {
    render(await request("/api/sso/review-sessions", {method: "POST", body: "{}"}));
  } catch (error) {
    announce(error.message);
  } finally {
    busy = false;
  }
});

loadState();
window.setInterval(() => { if (!busy && !document.hidden) loadState({focus: false}); }, 1000);
