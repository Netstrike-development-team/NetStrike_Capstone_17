import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {test} from "node:test";
import {ParticipantSession} from "../static/participant-session.js";

const state = (run_id = "run-a") => ({run_id, state: "running", elapsed_seconds: 0, injects: [], cloud_enabled: true, impact_enabled: true});
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
function harness() {
  let credential = "learner-a";
  const calls = [], responses = [], clears = [];
  const session = new ParticipantSession({readToken: () => credential, cleared: (reason) => clears.push(reason),
    call: async (path, options) => { calls.push({path, options}); const value = responses.shift();
      if (value instanceof Error) throw value; return await value; }});
  return {session, calls, responses, clears, credential: (value) => { credential = value; }};
}
async function load(h, run = "run-a") { h.responses.push(state(run)); return h.session.refresh(); }
const post = (h) => h.session.write("/api/participant/actions", {body: '{"target_id":"synthetic"}'});

test("no write before a successful current-credential state read", async () => {
  const h = harness();
  await assert.rejects(post(h), /Refresh/);
  h.credential(""); assert.equal(await h.session.refresh(), null);
  assert.equal(h.calls.length, 0);
});
test("mutations pin inspected run and do not alter the submitted body", async () => {
  const h = harness(); await load(h); h.responses.push({successful: true}); await post(h);
  assert.equal(h.calls[1].options.headers["X-Exercise-Run-ID"], "run-a");
  assert.equal(h.calls[1].options.method, "POST");
  assert.equal(h.calls[1].options.body, '{"target_id":"synthetic"}');
});
test("newer reads win and successful writes discard pre-write reads", async () => {
  const h = harness(); await load(h); const old = deferred(); h.responses.push(old.promise);
  const read = h.session.refresh(); await load(h, "run-b"); old.resolve(state());
  assert.equal(await read, null); assert.equal(h.session.runId, "run-b");
  const pending = deferred(); h.responses.push(pending.promise); const prewrite = h.session.refresh();
  h.responses.push({successful: true}); await post(h); pending.resolve(state("run-b"));
  assert.equal(await prewrite, null);
});
test("observed reset clears drafts and drops pending old-run receipts", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const write = post(h); await load(h, "run-b"); pending.resolve({successful: true});
  assert.equal(await write, null); assert.ok(h.clears.includes("run"));
  assert.equal(h.session.runId, "run-b");
});
test("an evidence read from a previous run is discarded after observed reset", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const read = h.session.read("/api/participant/cloud"); await load(h, "run-b");
  pending.resolve({run_id: "run-a", private: "old facts"});
  assert.equal(await read, null); assert.equal(h.session.runId, "run-b");
});
test("credential switch discards late writes, reads and failures", async () => {
  for (const operation of ["write", "read", "error"]) {
    const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
    const request = operation === "write" ? post(h) : h.session.read("/api/participant/cloud");
    h.credential("learner-b"); await load(h);
    if (operation === "error") pending.reject(new Error("old private error"));
    else pending.resolve({run_id: "run-a", successful: true});
    assert.equal(await request, null);
  }
});
test("failed refresh removes write authority but transient faults preserve drafts", async () => {
  const h = harness(); await load(h); const clears = h.clears.length;
  h.responses.push(new Error("offline")); await assert.rejects(h.session.refresh(), /offline/);
  await assert.rejects(post(h), /Refresh/); assert.equal(h.clears.length, clears);
  await load(h); h.responses.push(Object.assign(new Error("denied"), {status: 401}));
  await assert.rejects(h.session.refresh(), /denied/); assert.equal(h.session.runId, null);
});
test("uncertain write is not retried and requires refresh before further actions", async () => {
  const h = harness(); await load(h); h.responses.push(new Error("lost response"));
  await assert.rejects(post(h), /not confirmed/); await assert.rejects(post(h), /Refresh/);
  assert.equal(h.calls.length, 2);
});
test("stale-run denial cannot silently become a new-run action", async () => {
  const h = harness(); await load(h);
  h.responses.push(Object.assign(new Error("run changed"), {status: 409}));
  await assert.rejects(post(h), /Refresh/); await assert.rejects(post(h), /Refresh/);
  await load(h, "run-b"); assert.ok(h.clears.includes("run"));
  assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1);
});
test("mismatched evidence response invalidates authority rather than rendering new-run facts", async () => {
  const h = harness(); await load(h); h.responses.push({run_id: "run-b"});
  await assert.rejects(h.session.read("/api/participant/cloud"), /Exercise changed/);
  assert.equal(h.session.runId, null); await assert.rejects(post(h), /Refresh/);
});

class Element {
  constructor(tag = "div") { this.tag = tag; this.children = []; this.events = {}; this.dataset = {}; this.value = ""; this.resets = 0; this.disabled = false; }
  addEventListener(name, callback) { this.events[name] = callback; }
  append(...children) { this.children.push(...children); }
  add(child) { this.append(child); }
  replaceChildren(...children) { this.children = children; }
  reset() { this.resets += 1; this.value = ""; }
  reportValidity() { return true; }
  querySelectorAll() { return this.children.flatMap((child) => [...(child.dataset.field ? [child] : []), ...child.querySelectorAll()]); }
}
function mounted() {
  let credential = "";
  const nodes = new Map(), calls = [], responses = [];
  const targets = [new Element("input"), new Element("input")];
  const controls = Array.from({length: 6}, () => new Element("button"));
  const select = (id) => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  let session;
  class InjectedSession extends ParticipantSession {
    constructor(options) { super({...options, readToken: () => credential, call: async (path, options) => {
      calls.push({path, options}); const result = responses.shift(); if (result instanceof Error) throw result; return await result;
    }}); session = this; }
  }
  const fields = {principal_id: "principal", confirmed_count: "5", conclusion: "mock_access_only", evidence_ids: "event-a",
    fixture_id: "fixture", confirmed_scope: "Synthetic", confirmed_cloud_records: "5", business_impact: "Decoys",
    actions_taken: "Restored", remaining_risk: "Unknown", recommendations: "Review access\nReview helpdesk",
    identity: "sarah", classification: "account compromise"};
  const context = vm.createContext({ParticipantSession: InjectedSession, mountSupport() {},
    token: () => credential, connect(input, callback) { credential = input.value.trim(); input.value = ""; return callback(); },
    clearNotice(element) { element.textContent = ""; }, formatElapsed: () => "00:00:00",
    setStatus: (element, value) => { element.textContent = value; },
    notify: (element, value) => { element.textContent = value; }, idempotency: () => "key",
    setInterval() {}, Option: class extends Element {},
    FormData: class { get(key) { return fields[key] || ""; } getAll() { return ["synthetic"]; } },
    document: {querySelector: select, querySelectorAll: (selector) => selector === "#actions input" ? targets : selector.includes("button[type=submit]") ? controls : [], createElement: (tag) => new Element(tag)}});
  const source = readFileSync(new URL("../static/participant.js", import.meta.url), "utf8").replace(/^import .*;\n/gm, "");
  new vm.Script(source).runInContext(context);
  return {nodes, targets, controls, calls, responses, session, credential: (value) => { credential = value; }, select};
}
test("actual participant bindings send a run header for every learner mutation", async () => {
  const m = mounted(); m.credential("learner-a"); m.responses.push(state()); await m.select("#refresh").events.click();
  const cases = [
    ["#dp1-form", "submit", "checkpoints/dp1"], ["#intrusion-timeline", "submit", "timeline"],
    ["#cloud-form", "submit", "cloud/assessment"], ["#recovery-brief", "submit", "recovery/brief"],
    ["#actions", "click", "actions"], ["#recovery-actions", "click", "recovery/action"],
  ];
  for (const [id, event, path] of cases) {
    const button = new Element("button");
    button.dataset = {action: "identity.session.revoke", type: "session", recovery: "recovery.fixture.restore"};
    button.parentElement = {querySelector: () => ({value: "session"})};
    m.responses.push({successful: true, passed: true, submission_id: 1}, state());
    await m.select(id).events[event]({preventDefault() {}, currentTarget: m.select(id), target: {closest: () => button}});
    const call = m.calls.filter((item) => item.options.method === "POST").at(-1);
    assert.equal(call.path, `/api/participant/${path}`);
    assert.equal(call.options.headers["X-Exercise-Run-ID"], "run-a");
  }
});
test("actual participant bindings clear DP1, response targets, evidence and all run drafts on reset", async () => {
  const m = mounted(); m.credential("learner-a"); m.responses.push(state()); await m.select("#refresh").events.click();
  const ids = ["#dp1-form", "#intrusion-timeline", "#recovery-actions", "#recovery-brief", "#cloud-form"];
  const counts = ids.map((id) => m.select(id).resets);
  m.targets.forEach((input) => { input.value = "old-run-target"; });
  m.select("#cloud-state").append(new Element());
  m.responses.push(state("run-b")); await m.select("#refresh").events.click();
  ids.forEach((id, index) => assert.equal(m.select(id).resets, counts[index] + 1));
  assert.ok(m.targets.every((input) => input.value === ""));
  assert.equal(m.select("#cloud-state").children.length, 0);
  assert.equal(m.select("#run-id").textContent, "run-b");
});
test("actual same-run polling preserves learner drafts and targets", async () => {
  const m = mounted(); m.credential("learner-a"); m.responses.push(state()); await m.select("#refresh").events.click();
  const resets = m.select("#dp1-form").resets;
  m.select("#dp1-form").value = "Assessment draft";
  m.targets[0].value = "current-evidence-target";
  m.responses.push(state()); await m.select("#refresh").events.click();
  assert.equal(m.select("#dp1-form").resets, resets);
  assert.equal(m.select("#dp1-form").value, "Assessment draft");
  assert.equal(m.targets[0].value, "current-evidence-target");
});

test("actual cloud-assessment double submit sends only one pending learner mutation", async () => {
  const m = mounted(); m.credential("learner-a"); m.responses.push(state());
  await m.select("#refresh").events.click();
  const pending = deferred(); m.responses.push(pending.promise, state());
  const event = {preventDefault() {}, currentTarget: m.select("#cloud-form")};
  const first = m.select("#cloud-form").events.submit(event);
  try {
    await m.select("#cloud-form").events.submit(event);
    assert.equal(m.calls.filter((call) => call.options.method === "POST").length, 1);
  } finally {
    pending.resolve({submission_id: 1});
    await first;
  }
});

test("one pending write spans every mutation endpoint and blocks early inspection authority", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const first = post(h);
  assert.equal(h.session.canWrite(), false);
  for (const path of ["checkpoints/dp1", "timeline", "cloud/assessment", "recovery/brief", "actions", "recovery/action"]) {
    await assert.rejects(h.session.write(`/api/participant/${path}`, {body: "{}"}), /pending/);
  }
  await load(h); assert.equal(h.session.canWrite(), false);
  await assert.rejects(post(h), /pending/);
  pending.resolve({successful: true}); await first;
  assert.equal(h.session.canWrite(), false);
  await assert.rejects(post(h), /Refresh/);
  await load(h); assert.equal(h.session.canWrite(), true);
  assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1);
});

for (const outcome of ["success", "failure"]) {
  test(`observed account ABA preserves the pending lock and drops old ${outcome}`, async () => {
    const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
    const first = post(h);
    h.credential("learner-b"); await load(h); h.credential("learner-a"); await load(h);
    await assert.rejects(post(h), /pending/);
    if (outcome === "failure") pending.reject(new Error("Private old failure"));
    else pending.resolve({successful: true});
    assert.equal(await first, null);
    assert.equal(h.session.canWrite(), false);
    await load(h); h.responses.push({successful: true}); await post(h);
    assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 2);
  });
}

test("observed new run cannot issue an action until an older pending write settles", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const first = post(h); await load(h, "run-b"); await assert.rejects(post(h), /pending/);
  pending.resolve({successful: true}); assert.equal(await first, null);
  await assert.rejects(post(h), /Refresh/);
  await load(h, "run-b"); h.responses.push({successful: true}); await post(h);
  assert.equal(h.calls.at(-1).options.headers["X-Exercise-Run-ID"], "run-b");
});

for (const operation of ["state", "cloud", "recovery", "directory", "feedback"]) {
  for (const failed of [false, true]) {
    test(`pre-write ${operation} ${failed ? "error" : "snapshot"} is obsolete at mutation start, not only after its receipt`, async () => {
      const h = harness(); await load(h); const read = deferred(), write = deferred(); h.responses.push(read.promise);
      const inspected = operation === "state" ? h.session.refresh() : h.session.read(`/api/participant/${operation}`, {runScoped: operation !== "directory"});
      h.responses.push(write.promise); const pending = post(h);
      if (failed) read.reject(new Error("Obsolete private read"));
      else read.resolve(operation === "state" ? state() : {run_id: "run-a", facts: "Before write"});
      assert.equal(await inspected, null); assert.equal(h.session.canWrite(), false);
      write.resolve({successful: true}); await pending;
    });
  }
}

test("state read begun during a write cannot restore authority after that write settles", async () => {
  const h = harness(); await load(h); const write = deferred(), read = deferred(); h.responses.push(write.promise);
  const pending = post(h); h.responses.push(read.promise); const snapshot = h.session.refresh();
  write.resolve({successful: true}); await pending; read.resolve(state());
  assert.equal(await snapshot, null); assert.equal(h.session.canWrite(), false);
});

for (const failed of [false, true]) {
  test(`newest same-endpoint evidence wins over late ${failed ? "failure" : "success"}`, async () => {
    const h = harness(); await load(h); const old = deferred(); h.responses.push(old.promise);
    const stale = h.session.read("/api/participant/cloud");
    const newest = {run_id: "run-a", facts: "Current"}; h.responses.push(newest);
    assert.equal(await h.session.read("/api/participant/cloud"), newest);
    if (failed) old.reject(new Error("Obsolete evidence error"));
    else old.resolve({run_id: "run-a", facts: "Old"});
    assert.equal(await stale, null); assert.equal(h.session.canWrite(), true);
  });
}

for (const bad of [null, {}, state(""), state(" spaced "), {...state(), state: "unknown"},
  {...state(), elapsed_seconds: -1}, {...state(), elapsed_seconds: Infinity}, {...state(), injects: null},
  {...state(), cloud_enabled: "yes"}, {...state(), impact_enabled: null}]) {
  test("malformed run metadata cannot grant learner write authority", async () => {
    const h = harness(); h.responses.push(bad); await assert.rejects(h.session.refresh(), /unavailable/);
    assert.equal(h.session.canWrite(), false); await assert.rejects(post(h), /Refresh/);
    assert.equal(h.calls.length, 1);
  });
}

test("optional mismatched receipt run is rejected without becoming a confirmed action", async () => {
  const h = harness(); await load(h); h.responses.push({run_id: "run-b", successful: true});
  assert.equal(await post(h), null);
  assert.equal(h.session.canWrite(), false); assert.ok(h.clears.includes("run"));
});

test("actual participant actions disable during submission and post-write inspection while preserving same-run drafts", async () => {
  const m = mounted(); assert.ok(m.controls.every((button) => button.disabled));
  m.credential("learner-a"); m.responses.push(state()); await m.select("#refresh").events.click();
  assert.ok(m.controls.every((button) => !button.disabled));
  m.select("#cloud-form").value = "Evidence-supported draft";
  const resets = m.select("#cloud-form").resets;
  const write = deferred(), read = deferred(); m.responses.push(write.promise, read.promise);
  const first = m.select("#cloud-form").events.submit({preventDefault() {}, currentTarget: m.select("#cloud-form")});
  assert.ok(m.controls.every((button) => button.disabled));
  write.resolve({submission_id: 1});
  for (let i = 0; i < 12; i += 1) await Promise.resolve();
  assert.ok(m.controls.every((button) => button.disabled));
  read.resolve(state()); await first;
  assert.ok(m.controls.every((button) => !button.disabled));
  assert.equal(m.select("#cloud-form").resets, resets);
  assert.equal(m.select("#cloud-form").value, "Evidence-supported draft");
});

test("actual uncertain submission inspects only, retains drafts and cannot silently repeat a POST", async () => {
  const m = mounted(); m.credential("learner-a"); m.responses.push(state()); await m.select("#refresh").events.click();
  m.select("#cloud-form").value = "Keep this claim for review";
  m.responses.push(new Error("Unconfirmed transport"), new Error("State unavailable"));
  await m.select("#cloud-form").events.submit({preventDefault() {}, currentTarget: m.select("#cloud-form")});
  assert.equal(m.calls.filter((call) => call.options.method === "POST").length, 1);
  assert.ok(m.controls.every((button) => button.disabled));
  assert.equal(m.select("#cloud-form").value, "Keep this claim for review");
  assert.match(m.select("#notice").textContent, /not confirmed/);
});

test("all learner mutation buttons start disabled in the HTML before JavaScript inspection", () => {
  const html = readFileSync(new URL("../static/participant.html", import.meta.url), "utf8");
  const buttons = html.match(/<button\b[^>]*(?:type="submit"|data-action=|data-recovery=)[^>]*>/g);
  assert.equal(buttons.length, 17);
  assert.ok(buttons.every((button) => /\sdisabled(?:\s|>)/.test(button)));
});

test("current-state render failure does not leave visually enabled mutation controls", async () => {
  const m = mounted(); m.credential("learner-a"); m.responses.push({...state(), injects: [null]});
  await m.select("#refresh").events.click();
  assert.ok(m.controls.every((button) => button.disabled));
  assert.equal(m.session.canWrite(), false);
});

test("post-write inspection cannot deliver an old account's failed submission notice into a new view", async () => {
  const m = mounted(); m.credential("learner-a"); m.responses.push(state()); await m.select("#refresh").events.click();
  const oldRead = deferred(); m.responses.push(new Error("Private learner-a failure"), oldRead.promise);
  const submission = m.select("#cloud-form").events.submit({preventDefault() {}, currentTarget: m.select("#cloud-form")});
  for (let i = 0; i < 12; i += 1) await Promise.resolve();
  m.credential("learner-b"); m.responses.push(state()); await m.select("#refresh").events.click();
  oldRead.resolve(state()); await submission;
  assert.doesNotMatch(m.select("#notice").textContent || "", /Private learner-a/);
});
