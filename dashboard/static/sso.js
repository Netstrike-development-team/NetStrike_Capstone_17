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
let activeRead = null;
let disposed = false;
let announcementNumber = 0;
const accessToken = document.querySelector("#mfa-access-token");
let observedToken = accessToken.value.trim();

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    cache: "no-store",
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(typeof payload.detail === "string" ? payload.detail : "The exercise service rejected the request.");
  }
  return payload;
}

function announce(message) {
  const version = mutationVersion;
  const number = ++announcementNumber;
  liveStatus.textContent = "";
  window.setTimeout(() => {
    if (!disposed && version === mutationVersion && number === announcementNumber) liveStatus.textContent = message;
  }, 10);
}

function updateControls() {
  const active = !disposed && !busy && currentState && ["ready", "running"].includes(currentState.exercise_state);
  document.querySelector("#sign-in-form").querySelector("button").disabled = !active;
  document.querySelector("#review-sessions").disabled = !active || currentState?.view !== "success";
  const mfa = active && currentState.view === "mfa" && currentState.challenge &&
    (currentState.challenge.kind !== "scheduled" || Boolean(observedToken));
  document.querySelector("#approve-mfa").disabled = !mfa;
  document.querySelector("#deny-mfa").disabled = !mfa;
  for (const button of document.querySelectorAll("[data-return-sign-in]")) button.disabled = !active;
}

function invalidate() {
  mutationVersion += 1;
  activeRead?.controller.abort();
  activeRead = null;
  currentState = null;
  retrying = false;
  lastSignature = null;
  window.clearInterval(countdownTimer);
  credentialInput.value = "";
  document.querySelector("#session-list").replaceChildren();
  document.querySelector("#scheduled-result").textContent = "Current exercise state needs inspection.";
  document.querySelector("#mfa-seconds").textContent = "—";
  liveStatus.textContent = "";
  announcementNumber += 1;
  updateControls();
}

function synchronizeToken() {
  const value = accessToken.value.trim();
  if (observedToken !== value) {
    observedToken = value;
    invalidate();
    showFailure("Exercise access changed. Inspecting the current state before another action.");
  }
}

function showFailure(message) {
  document.querySelector("#failure-message").textContent = message;
  for (const [name, element] of views) element.hidden = name !== "failure";
  announce(message);
}

function validateState(state) {
  if (!state || typeof state.run_id !== "string" || !state.run_id.trim() ||
      state.run_id !== state.run_id.trim() || state.run_id.length > 128 || /[\x00-\x1f]/.test(state.run_id) ||
      !views.has(state.view) || !["ready", "running", "paused", "stopped", "completed"].includes(state.exercise_state) ||
      (state.view === "mfa" && (!state.challenge || typeof state.challenge.id !== "string" || !state.challenge.id))) {
    throw new Error("Current exercise state is unavailable. Inspect it before acting.");
  }
}

function focusView(view) {
  const heading = view.querySelector("h1");
  if (heading) {
    heading.tabIndex = -1;
    heading.focus();
  }
}

function startCountdown(seconds) {
  const version = mutationVersion;
  window.clearInterval(countdownTimer);
  const element = document.querySelector("#mfa-seconds");
  let remaining = Math.max(0, Number(seconds) || 0);
  element.textContent = String(remaining);
  countdownTimer = window.setInterval(() => {
    if (disposed || version !== mutationVersion) return;
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
  validateState(state);
  if (currentState && currentState.run_id !== state.run_id) {
    invalidate();
    accessToken.value = "";
    observedToken = "";
  }
  const signature = JSON.stringify([state.run_id, state.view, state.challenge?.id, state.message, state.exercise_state, state.scheduled_result?.outcome]);
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
  }
  if (state.view === "suspicious_session") renderSessions(state.sessions || []);
  if (changed) announce(state.message || `${state.service_name} is ready.`);
  if (focus) focusView(active);
  updateControls();
}

async function loadState({focus = true} = {}) {
  synchronizeToken();
  if (disposed || busy || activeRead) return;
  const owner = {version: mutationVersion, controller: new AbortController()};
  activeRead = owner;
  try {
    const state = await request("/api/sso/state", {signal: owner.controller.signal});
    synchronizeToken();
    if (!disposed && owner.version === mutationVersion && activeRead === owner) render(state, {focus});
  } catch (error) {
    synchronizeToken();
    if (disposed || owner.version !== mutationVersion || activeRead !== owner) return;
    invalidate();
    showFailure(error.message);
  } finally {
    if (activeRead === owner) activeRead = null;
  }
}

async function mutate(path, body, {scheduled = false} = {}) {
  synchronizeToken();
  if (disposed || busy || !currentState || !["ready", "running"].includes(currentState.exercise_state)) return;
  if (scheduled && !observedToken) return;
  const run = currentState.run_id;
  const credential = observedToken;
  busy = true;
  invalidate();
  const version = mutationVersion;
  try {
    const state = await request(path, {method: "POST", body: JSON.stringify(body),
      headers: {"X-Exercise-Run-ID": run, ...(scheduled ? {Authorization: `Bearer ${credential}`} : {})}});
    synchronizeToken();
    if (disposed || version !== mutationVersion) return;
    validateState(state);
    if (state.run_id !== run) throw new Error("The exercise run changed. Inspect the new state; this action will not be repeated.");
    render(state);
  } catch (error) {
    synchronizeToken();
    if (disposed || version !== mutationVersion) return;
    invalidate();
    showFailure(`${error.message} Inspect the current state before trying again; the action was not automatically repeated.`);
  } finally {
    busy = false;
    updateControls();
    // Reads can recover authority; never retry a POST whose outcome is uncertain.
    if (!disposed && !currentState) await loadState({focus: false});
  }
}

document.querySelector("#sign-in-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  synchronizeToken();
  if (busy || !currentState) return;
  const form = new FormData(event.currentTarget);
  const body = {
    username: String(form.get("username") || ""),
    credential: String(form.get("credential") || ""),
  };
  credentialInput.value = "";
  await mutate("/api/sso/sign-in", body);
});

for (const button of document.querySelectorAll("[data-return-sign-in]")) {
  button.addEventListener("click", () => {
    synchronizeToken();
    if (disposed || busy || !currentState || !["ready", "running"].includes(currentState.exercise_state)) return;
    retrying = true;
    for (const [name, element] of views) element.hidden = name !== "sign_in";
    document.querySelector("#username").focus();
  });
}

async function decideMfa(decision) {
  synchronizeToken();
  if (busy || currentState?.view !== "mfa" || !currentState.challenge) return;
  const scheduled = currentState.challenge.kind === "scheduled";
  await mutate(scheduled ? "/api/sso/scheduled-mfa" : "/api/sso/mfa",
    {challenge_id: currentState.challenge.id, decision}, {scheduled});
}

document.querySelector("#approve-mfa").addEventListener("click", () => decideMfa("approve"));
document.querySelector("#deny-mfa").addEventListener("click", () => decideMfa("deny"));
document.querySelector("#review-sessions").addEventListener("click", async () => {
  synchronizeToken();
  if (currentState?.view === "success") await mutate("/api/sso/review-sessions", {});
});

accessToken.addEventListener("input", () => { synchronizeToken(); return loadState({focus: false}); });
window.addEventListener("pagehide", () => {
  disposed = true;
  accessToken.value = "";
  observedToken = "";
  invalidate();
  window.clearInterval(pollTimer);
});
window.addEventListener("pageshow", () => {
  if (!disposed) return;
  disposed = false;
  pollTimer = window.setInterval(() => { if (!document.hidden) loadState({focus: false}); }, 1000);
  loadState({focus: false});
});
updateControls();
loadState();
let pollTimer = window.setInterval(() => { if (!document.hidden) loadState({focus: false}); }, 1000);
