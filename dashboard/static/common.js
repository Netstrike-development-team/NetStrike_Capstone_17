"use strict";

const TOKEN_KEY = "netstrike.portal.token";

export function token() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

export function connect(input, onConnected) {
  const value = input.value.trim();
  if (!value) throw new Error("Enter the exercise access token.");
  sessionStorage.setItem(TOKEN_KEY, value);
  input.value = "";
  onConnected();
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (token()) headers.set("Authorization", `Bearer ${token()}`);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {...options, headers});
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = payload && typeof payload === "object" ? payload.detail : payload;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

export function notify(element, message, type = "success") {
  element.textContent = message;
  element.className = `notice show ${type}`;
}

export function clearNotice(element) {
  element.textContent = "";
  element.className = "notice";
}

export function formatElapsed(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = seconds % 60;
  return [hours, minutes, remaining].map((part) => String(part).padStart(2, "0")).join(":");
}

export function setStatus(element, state) {
  element.textContent = state;
  element.className = `pill ${state}`;
}

export function idempotency(prefix) {
  const suffix = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  return `${prefix}-${suffix}`.slice(0, 128);
}
