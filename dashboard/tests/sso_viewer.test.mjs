import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {test} from "node:test";

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
const state = (overrides = {}) => ({run_id: "run-a", exercise_state: "running", view: "sign_in",
  service_name: "Exercise Access", heading: "Synthetic sign-in", introduction: "Only exercise accounts",
  message: "Current exercise", display_name: "Synthetic user", challenge: null, sessions: [],
  scheduled_result: null, ...overrides});
const mfa = (overrides = {}) => state({view: "mfa", challenge: {id: "challenge-a", expires_in_seconds: 30}, ...overrides});
const response = (payload, status = 200) => ({ok: status < 400, status, json: async () => payload});
const tick = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve(); };

class Element {
  constructor() { this.children = []; this.events = {}; this.value = ""; this.disabled = false; this.hidden = false; this.textContent = ""; }
  addEventListener(name, callback) { this.events[name] = callback; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  querySelector(selector) { return this[selector] ||= new Element(); }
  focus() { this.focused = true; }
}
function mounted(initial = state()) {
  const nodes = new Map(), calls = [], queue = [response(initial)], intervals = [], timeouts = [], events = {};
  const returns = [new Element(), new Element()];
  const node = (selector) => { if (!nodes.has(selector)) nodes.set(selector, new Element()); return nodes.get(selector); };
  const context = vm.createContext({AbortController,
    FormData: class { get(name) { return node(`#${name}`).value; } },
    fetch: async (path, options) => {
      calls.push({path, options});
      const next = queue.shift();
      if (next instanceof Error) throw next;
      if (!next) throw new Error("No queued response");
      return await next;
    },
    document: {hidden: false, querySelector: node, querySelectorAll: () => returns, createElement: () => new Element()},
    window: {setInterval: (callback) => { intervals.push(callback); return intervals.length - 1; },
      clearInterval: () => {}, setTimeout: (callback) => { timeouts.push(callback); },
      addEventListener: (name, callback) => { events[name] = callback; }}});
  new vm.Script(readFileSync(new URL("../static/sso.js", import.meta.url), "utf8")).runInContext(context);
  return {node, calls, queue, intervals, timeouts, events, returns,
    post: (value, status = 200) => queue.push(response(value, status)),
    poll: async () => { intervals[0](); await tick(); },
    signIn: () => { node("#username").value = "sarah@simcorp.test"; node("#credential").value = "synthetic-phrase";
      return node("#sign-in-form").events.submit({preventDefault() {}, currentTarget: node("#sign-in-form")}); },
    token: async (value) => { node("#mfa-access-token").value = value; node("#mfa-access-token").events.input(); await tick(); },
    approve: () => node("#approve-mfa").events.click(), deny: () => node("#deny-mfa").events.click(),
    review: () => node("#review-sessions").events.click()};
}

test("initial actions stay disabled until a valid uncached current-run snapshot", async () => {
  const h = mounted();
  assert.equal(h.node("#sign-in-form").querySelector("button").disabled, true);
  await h.signIn(); assert.equal(h.calls.length, 1);
  await tick(); assert.equal(h.node("#sign-in-form").querySelector("button").disabled, false);
  assert.equal(h.calls[0].options.cache, "no-store");
});

test("double sign-in and other handlers cannot overlap a pending write", async () => {
  const h = mounted(); await tick(); const pending = deferred(); h.queue.push(pending.promise);
  const first = h.signIn();
  assert.equal(h.node("#credential").value, "");
  await h.signIn(); await h.approve(); await h.review();
  h.returns[0].events.click(); await h.poll();
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].options.headers["X-Exercise-Run-ID"], "run-a");
  assert.equal(h.calls[1].options.cache, "no-store");
  pending.resolve(response(mfa())); await first;
  assert.equal(h.node("#approve-mfa").disabled, false);
});

test("MFA decision pins the inspected challenge and run; opposite choice cannot overlap", async () => {
  const h = mounted(mfa()); await tick(); const pending = deferred(); h.queue.push(pending.promise);
  const first = h.approve(); await h.deny(); await h.signIn();
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].path, "/api/sso/mfa");
  assert.equal(h.calls[1].options.headers["X-Exercise-Run-ID"], "run-a");
  assert.deepEqual(JSON.parse(h.calls[1].options.body), {challenge_id: "challenge-a", decision: "approve"});
  pending.resolve(response(state({view: "success"}))); await first;
  assert.equal(h.node("#approve-mfa").disabled, true);
  assert.equal(h.node("#review-sessions").disabled, false);
});

test("session review is single-pending and run-scoped", async () => {
  const h = mounted(state({view: "success"})); await tick(); const pending = deferred(); h.queue.push(pending.promise);
  const first = h.review(); await h.review(); assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].options.headers["X-Exercise-Run-ID"], "run-a");
  pending.resolve(response(state({view: "suspicious_session", sessions: [{id: "sess-a", label: "Synthetic", location: "Lab", last_seen: "Now"}]})));
  await first; assert.equal(h.node("#session-list").children.length, 1);
});

for (const status of [401, 403, 409, null]) {
  test(`uncertain/rejected write (${status}) removes authority until inspection and never repeats POST`, async () => {
    const h = mounted(mfa()); await tick();
    h.queue.push(status ? response({detail: "Rejected exercise request"}, status) : new Error("Transport unavailable"));
    const fresh = deferred(); h.queue.push(fresh.promise); const first = h.approve(); await tick();
    assert.equal(h.node("#approve-mfa").disabled, true);
    assert.equal(h.node("#deny-mfa").disabled, true);
    await h.deny(); assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1);
    fresh.resolve(response(mfa({exercise_state: "paused"}))); await first;
    assert.equal(h.node("#approve-mfa").disabled, true);
  });
}

test("read failure clears challenge, sessions and write authority instead of keeping old MFA active", async () => {
  const h = mounted(mfa()); await tick(); h.queue.push(new Error("State unavailable")); await h.poll();
  assert.equal(h.node("#approve-mfa").disabled, true); assert.equal(h.node("#deny-mfa").disabled, true);
  assert.equal(h.node("#mfa-seconds").textContent, "—"); await h.approve(); assert.equal(h.calls.length, 2);
  h.post(state()); await h.poll(); assert.equal(h.node("#sign-in-form").querySelector("button").disabled, false);
});

test("poll that started before a mutation cannot overwrite its receipt or unlock pending controls", async () => {
  const h = mounted(); await tick(); const old = deferred(), write = deferred(); h.queue.push(old.promise);
  const polling = h.poll(); h.queue.push(write.promise); const mutation = h.signIn();
  assert.equal(h.calls[1].options.signal.aborted, true);
  old.resolve(response(state({view: "success", message: "Obsolete success"}))); await polling;
  assert.equal(h.node("#sign-in-form").querySelector("button").disabled, true);
  write.resolve(response(mfa())); await mutation;
  assert.equal(h.node("#view-mfa").hidden, false);
});

for (const failed of [false, true]) {
  test(`observed scheduled-token ABA drops late ${failed ? "failure" : "success"}, retaining pending-write lock`, async () => {
    const scheduled = mfa({challenge: {id: "scheduled-a", kind: "scheduled", expires_in_seconds: 30}});
    const h = mounted(scheduled); await tick();
    assert.equal(h.node("#approve-mfa").disabled, true);
    h.post(scheduled); await h.token("token-a");
    const old = deferred(); h.queue.push(old.promise); const first = h.approve();
    await h.token("token-b"); await h.token("token-a"); await h.approve();
    assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1);
    assert.equal(h.calls.at(-1).options.headers.Authorization, "Bearer token-a");
    h.post(state({run_id: "run-b", message: "Fresh run"}));
    if (failed) old.reject(new Error("Private old failure"));
    else old.resolve(response(state({view: "success", message: "Old receipt"})));
    await first;
    assert.equal(h.node("#view-success").hidden, true);
    assert.equal(h.node("#introduction").textContent, "Only exercise accounts");
    assert.notEqual(h.node("#failure-message").textContent, "Private old failure");
    assert.equal(h.calls.at(-1).path, "/api/sso/state");
  });
}

test("wrong-run write response is not rendered and only a fresh GET can restore authority", async () => {
  const h = mounted(); await tick(); h.post(state({run_id: "run-b", view: "success", message: "Wrong-run receipt"}));
  const fresh = deferred(); h.queue.push(fresh.promise); const first = h.signIn(); await tick();
  assert.equal(h.node("#view-success").hidden, true);
  assert.equal(h.node("#sign-in-form").querySelector("button").disabled, true);
  fresh.resolve(response(state({run_id: "run-b"}))); await first;
  h.post(mfa({run_id: "run-b"})); await h.signIn();
  assert.equal(h.calls.at(-1).options.headers["X-Exercise-Run-ID"], "run-b");
});

test("observed reset clears prior session receipts, token, retry view and countdown", async () => {
  const h = mounted(state({view: "failure"})); await tick(); h.returns[0].events.click();
  h.node("#mfa-access-token").value = "token-a"; h.post(state({view: "failure"})); await h.poll();
  h.post(state({run_id: "run-b", view: "locked"})); await h.poll();
  assert.equal(h.node("#view-locked").hidden, false);
  assert.equal(h.node("#mfa-access-token").value, "");
  assert.equal(h.node("#session-list").children.length, 0);
});

for (const bad of [null, {}, state({run_id: ""}), state({run_id: " bad "}),
  state({run_id: "x".repeat(129)}), state({exercise_state: "unknown"}), mfa({challenge: null})]) {
  test("malformed current-state response fails closed", async () => {
    const h = mounted(bad); await tick();
    assert.equal(h.node("#sign-in-form").querySelector("button").disabled, true);
    assert.equal(h.node("#approve-mfa").disabled, true);
    await h.signIn(); assert.equal(h.calls.length, 1);
  });
}

for (const lifecycle of ["paused", "stopped", "completed"]) {
  test(`${lifecycle} snapshots disable all mutation handlers`, async () => {
    const h = mounted(mfa({exercise_state: lifecycle})); await tick();
    h.returns[0].events.click(); await h.approve(); await h.signIn(); await h.review();
    assert.equal(h.calls.length, 1); assert.equal(h.node("#approve-mfa").disabled, true);
  });
}

test("pagehide prevents late writes, reads and delayed announcements from restoring controls", async () => {
  const h = mounted(); await tick(); const pending = deferred(); h.queue.push(pending.promise);
  const first = h.signIn(); h.events.pagehide(); pending.resolve(response(mfa())); await first;
  for (const callback of h.timeouts) callback(); await h.poll(); await h.signIn();
  assert.equal(h.calls.length, 2); assert.equal(h.node("#live-status").textContent, "");
  assert.equal(h.node("#approve-mfa").disabled, true);
});

test("back/forward page restoration requires a fresh snapshot without repeating an old action", async () => {
  const h = mounted(mfa()); await tick(); h.events.pagehide();
  const fresh = deferred(); h.queue.push(fresh.promise); h.events.pageshow();
  assert.equal(h.node("#approve-mfa").disabled, true);
  fresh.resolve(response(state({run_id: "run-b"}))); await tick();
  assert.equal(h.node("#sign-in-form").querySelector("button").disabled, false);
  assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 0);
});

test("superseded live announcements cannot overwrite the latest same-run message", async () => {
  const h = mounted(); await tick(); h.post(state({message: "New same-run state"})); await h.poll();
  for (const callback of [...h.timeouts].reverse()) callback();
  assert.equal(h.node("#live-status").textContent, "New same-run state");
});
