import assert from "node:assert/strict";
import {test} from "node:test";
import {SupportSession, OBJECTIVES, renderThreads, mountSupport} from "../static/support.js";

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function snapshot(overrides = {}) {
  return {run_id: "run-a", run_state: "running", principal_role: "soc_analyst", requests: [], ...overrides};
}
function question(overrides = {}) {
  return {request_id: "question-a", objective_id: "LO2", question: "Question", response: null,
    requested_at: "2026-10-04T10:00:00Z", elapsed_seconds: 0, ...overrides};
}
function harness(options = {}) {
  let credential = "learner";
  let nextKey = 0;
  const calls = [];
  const responses = [];
  let clearCount = 0;
  const session = new SupportSession({readToken: () => credential,
    call: async (path, init) => {
      calls.push({path, init});
      const result = responses.shift();
      if (result instanceof Error) throw result;
      return await result;
    }, makeKey: () => `key-${++nextKey}`, cleared: () => clearCount++, ...options});
  return {session, calls, responses, credential: (value) => { credential = value; }, clears: () => clearCount};
}
async function load(h, data = snapshot()) {
  h.responses.push(data);
  await h.session.refresh();
}
const fields = {objective_id: "LO2", message: "How do I cite evidence?"};

test("initial/disconnected view cannot submit or make a request", async () => {
  const h = harness();
  h.credential("");
  await h.session.refresh();
  assert.equal(await h.session.submit(fields), false);
  assert.equal(h.calls.length, 0);
});
test("request POST binds the current run and generated retry key", async () => {
  const h = harness();
  await load(h);
  h.responses.push({run_id: "run-a", replayed: false});
  assert.equal(await h.session.submit(fields), true);
  assert.equal(h.calls[1].path, "/api/participant/support");
  assert.deepEqual(JSON.parse(h.calls[1].init.body), {...fields, run_id: "run-a", idempotency_key: "key-1"});
  assert.equal(h.session.snapshot, null); // Cannot start another request using pre-write state.
});
test("ambiguous network error retries the frozen payload and key despite edits", async () => {
  const h = harness();
  await load(h);
  h.responses.push(new Error("network unavailable"));
  assert.equal(await h.session.submit(fields), false);
  assert.ok(h.session.operation);
  h.responses.push({run_id: "run-a", replayed: true});
  assert.equal(await h.session.submit({objective_id: "LO5", message: "different"}), true);
  assert.equal(h.calls[1].init.body, h.calls[2].init.body);
  assert.match(h.session.message, /no duplicate/);
});
test("server error keeps retry; definite rejection permits corrected payload", async () => {
  const h = harness();
  await load(h);
  h.responses.push(Object.assign(new Error("fault"), {status: 500}));
  await h.session.submit(fields);
  assert.ok(h.session.operation);
  h.responses.push(Object.assign(new Error("conflict"), {status: 409}));
  await h.session.submit({});
  assert.equal(h.session.operation, null);
});
test("double-click cannot issue a second write", async () => {
  const h = harness();
  await load(h);
  const pending = deferred();
  h.responses.push(pending.promise);
  const first = h.session.submit(fields);
  assert.equal(await h.session.submit(fields), false);
  assert.equal(h.calls.length, 2);
  pending.resolve({run_id: "run-a"});
  await first;
});
test("auth change discards old replies, private views, drafts and retry payload", async () => {
  const h = harness();
  await load(h);
  const pending = deferred();
  h.responses.push(pending.promise);
  const write = h.session.submit(fields);
  h.credential("another-actor");
  await load(h, snapshot({requests: [question({question: "Other actor"})]}));
  pending.resolve({run_id: "run-a"});
  assert.equal(await write, false);
  assert.equal(h.session.operation, null);
  assert.equal(h.session.snapshot.requests[0].question, "Other actor");
});
test("out-of-order reads cannot replace a newer private transcript", async () => {
  const h = harness();
  const old = deferred();
  h.responses.push(old.promise);
  const first = h.session.refresh();
  await load(h, snapshot({requests: [question({question: "New"})]}));
  old.resolve(snapshot({requests: [question({question: "Old"})]}));
  await first;
  assert.equal(h.session.snapshot.requests[0].question, "New");
});
test("a read issued before successful POST cannot re-enable stale controls", async () => {
  const h = harness();
  await load(h);
  const old = deferred();
  h.responses.push(old.promise);
  const read = h.session.refresh();
  h.responses.push({run_id: "run-a"});
  await h.session.submit(fields);
  old.resolve(snapshot());
  await read;
  assert.equal(h.session.snapshot, null);
});
test("run reset discards pending old-run operation and ignores its late receipt", async () => {
  const h = harness();
  await load(h);
  const pending = deferred();
  h.responses.push(pending.promise);
  const write = h.session.submit(fields);
  await load(h, snapshot({run_id: "run-b"}));
  pending.resolve({run_id: "run-a"});
  assert.equal(await write, false);
  assert.equal(h.session.contextRun, "run-b");
  assert.equal(h.session.operation, null);
  assert.equal(h.session.busy, false);
});
test("failed read removes transcript and write authority; auth denial also clears retry", async () => {
  const h = harness();
  await load(h, snapshot({requests: [question()]}));
  h.responses.push(new Error("offline"));
  await h.session.refresh();
  assert.equal(h.session.snapshot, null);
  assert.equal(h.session.canWrite(), false);
  await load(h);
  h.responses.push(new Error("ambiguous"));
  await h.session.submit(fields);
  h.responses.push(Object.assign(new Error("denied"), {status: 403}));
  await h.session.refresh();
  assert.equal(h.session.operation, null);
  assert.ok(h.clears() >= 3);
});
test("pending and ten-request limits block new learner questions", async () => {
  const h = harness();
  await load(h, snapshot({requests: [question()]}));
  assert.equal(h.session.canWrite(), false);
  await load(h, snapshot({requests: Array.from({length: 10}, (_, i) => question({request_id: `${i}`, response: {}}))}));
  assert.equal(h.session.canWrite(), false);
});
test("fresh requests are live/paused only; exact uncertain retry works after completion", async () => {
  const h = harness();
  await load(h, snapshot({run_state: "paused"}));
  assert.equal(h.session.canWrite(), true);
  h.responses.push(new Error("ambiguous"));
  await h.session.submit(fields);
  await load(h, snapshot({run_state: "completed"}));
  assert.equal(h.session.canWrite(), false);
  h.responses.push({run_id: "run-a", replayed: true});
  assert.equal(await h.session.submit({}), true);
});
test("technical operator cannot coach and stopped run permits platform explanation only", async () => {
  const h = harness({staff: true});
  await load(h, snapshot({principal_role: "technical_operator", requests: [question()]}));
  assert.equal(h.session.canWrite("hint"), false);
  assert.equal(h.session.canWrite("platform_issue"), true);
  await load(h, snapshot({principal_role: "facilitator", run_state: "stopped", requests: [question()]}));
  assert.equal(h.session.canWrite("clarification"), false);
  assert.equal(h.session.canWrite("platform_issue"), true);
  await load(h, snapshot({principal_role: "facilitator", run_state: "completed"}));
  assert.equal(h.session.canWrite("platform_issue"), false);
});
test("evaluator and observer surfaces are always read-only", async () => {
  for (const options of [{staff: true}, {staff: true, observer: true}]) {
    const h = harness(options);
    await load(h, snapshot({principal_role: options.observer ? "facilitator" : "evaluator"}));
    assert.equal(h.session.canWrite(), false);
    assert.equal(await h.session.submit(fields), false);
    assert.equal(h.calls.length, 1);
  }
});
test("staff writes exact question and explicitly selected scope; answered target blocked", async () => {
  const h = harness({staff: true});
  await load(h, snapshot({principal_role: "facilitator", requests: [question()]}));
  const reply = {request_id: "question-a", message: "Human explanation", kind: "clarification", objective_ids: ["LO2", "LO3"]};
  h.responses.push({run_id: "run-a"});
  assert.equal(await h.session.submit(reply), true);
  assert.equal(h.calls[1].path, "/api/facilitator/support/replies");
  assert.deepEqual(JSON.parse(h.calls[1].init.body).objective_ids, ["LO2", "LO3"]);
  await load(h, snapshot({principal_role: "facilitator", requests: [question({response: {text: "already answered"}})]}));
  assert.equal(await h.session.submit(reply), false);
});
test("unknown receipt is ambiguous, never treated as successful delivery", async () => {
  const h = harness();
  await load(h);
  h.responses.push({run_id: "wrong"});
  assert.equal(await h.session.submit(fields), false);
  assert.ok(h.session.operation);
});
test("reply objective array is copied before an uncertain retry", async () => {
  const h = harness({staff: true});
  await load(h, snapshot({principal_role: "facilitator", requests: [question()]}));
  const ids = ["LO2"];
  h.responses.push(new Error("ambiguous"));
  await h.session.submit({request_id: "question-a", objective_ids: ids, kind: "hint", message: "Human hint"});
  ids.push("LO5");
  assert.deepEqual(h.session.operation.objective_ids, ["LO2"]);
});

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ""; this.dataset = {}; this.value = ""; this.events = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, callback) { this.events[name] = callback; }
  add(option) { this.children.push(option); }
  get options() { return this.children; }
}
function allText(node) { return [node.textContent, ...node.children.map(allText)].join(" "); }
test("transcript renders hostile human text literally, with staff attribution only in staff mode", () => {
  globalThis.document = {createElement: (tag) => new Node(tag)};
  const container = new Node("div");
  const record = question({question: '<img src=x onerror="bad()">\nSecond line', requester_id: "private-actor", requester_role: "soc_analyst",
    response: {kind: "hint", text: "<script>bad()</script>", objective_ids: ["LO2"], responder_id: "private-staff", responder_role: "facilitator", responded_at: "now", event_id: "reply-id"}});
  renderThreads(container, snapshot({requests: [record]}), false);
  assert.match(allText(container), /<script>bad\(\)<\/script>/);
  assert.doesNotMatch(allText(container), /private-actor|private-staff|reply-id/);
  renderThreads(container, snapshot({requests: [record]}), true);
  assert.match(allText(container), /private-actor/);
  assert.match(allText(container), /reply-id/);
  assert.equal(OBJECTIVES.length, 5);
  delete globalThis.document;
});
test("observer mounting executes initial callbacks without a construction race", async () => {
  const nodes = Object.fromEntries(["#support-threads", "#support-summary", "#connect", "#support-refresh", "#refresh"].map((id) => [id, new Node("div")]));
  for (const node of Object.values(nodes)) node.addEventListener = () => {};
  globalThis.document = {querySelector: (id) => nodes[id] || null, createElement: (tag) => new Node(tag)};
  globalThis.sessionStorage = {getItem: () => ""};
  globalThis.window = {addEventListener: (event, callback) => { if (event === "pagehide") callback(); }};
  const session = mountSupport({staff: true, observer: true});
  assert.equal(session.snapshot, null);
  assert.match(nodes["#support-summary"].textContent, /Connect/);
  delete globalThis.document;
  delete globalThis.sessionStorage;
  delete globalThis.window;
});

function mounted(staff) {
  const nodes = Object.fromEntries(["#support-form", "#support-threads", "#support-summary", "#support-title",
    "#support-send", "#connect", "#support-refresh", "#refresh"].map((id) => [id, new Node("div")]));
  globalThis.Option = class extends Node {
    constructor(label, value) { super("option"); this.textContent = label; this.value = value; }
  };
  const form = nodes["#support-form"];
  const names = staff ? ["request_id", "kind", "message"] : ["objective_id", "message"];
  form.elements = Object.fromEntries(names.map((name) => [name, new Node(name === "message" ? "textarea" : "select")]));
  const defaults = staff ? {request_id: "", kind: "clarification", message: ""} : {objective_id: "", message: ""};
  const checkboxes = staff ? OBJECTIVES.map(([value]) => Object.assign(new Node("input"), {value, checked: false})) : [];
  if (staff) for (const value of ["clarification", "hint", "platform_issue"]) form.elements.kind.add(new Option(value, value));
  form.reset = () => {
    for (const [key, value] of Object.entries(defaults)) form.elements[key].value = value;
    for (const input of checkboxes) input.checked = false;
  };
  form.reportValidity = () => true;
  form.querySelectorAll = (selector) => selector.includes(":checked") ? checkboxes.filter((input) => input.checked)
    : [...Object.values(form.elements), ...checkboxes];
  form.reset();
  globalThis.document = {querySelector: (id) => nodes[id] || null, createElement: (tag) => new Node(tag)};
  let teardown;
  globalThis.window = {addEventListener: (name, callback) => { if (name === "pagehide") teardown = callback; }};
  const responses = [snapshot(staff ? {principal_role: "facilitator", requests: [question({requester_id: "learner", requester_role: "soc_analyst"})]} : {})];
  const calls = [];
  const session = mountSupport({staff, sessionOptions: {readToken: () => "actor", makeKey: () => "mounted-key",
    call: async (path, init) => { calls.push({path, init}); const value = responses.shift(); if (value instanceof Error) throw value; return await value; }}});
  return {nodes, form, session, responses, calls, checkboxes,
    cleanup: () => { teardown(); delete globalThis.document; delete globalThis.window; delete globalThis.Option; }};
}
const flush = () => new Promise((resolve) => setImmediate(resolve));
test("mounted participant preserves draft on polling, renders pending and posts real form fields", async () => {
  const m = mounted(false);
  try {
    await flush();
    assert.equal(m.form.elements.objective_id.options.length, 5);
    m.form.elements.objective_id.value = "LO2";
    m.form.elements.message.value = "My question";
    m.responses.push(snapshot());
    await m.session.refresh();
    assert.equal(m.form.elements.message.value, "My question");
    m.responses.push({run_id: "run-a"}, snapshot({requests: [question({question: "My question"})]}));
    await m.form.events.submit({preventDefault() {}});
    assert.equal(JSON.parse(m.calls[2].init.body).message, "My question");
    assert.equal(m.form.elements.message.value, "");
    assert.equal(m.nodes["#support-send"].disabled, true);
    assert.match(m.nodes["#support-title"].textContent, /1 awaiting reply/);
  } finally { m.cleanup(); }
});
test("mounted staff preserves selection/draft, requires scope and clears a coaching draft when stopped", async () => {
  const m = mounted(true);
  try {
    await flush();
    m.form.elements.request_id.value = "question-a";
    m.form.elements.message.value = "Coaching draft";
    m.form.events.change();
    assert.equal(m.nodes["#support-send"].disabled, false);
    m.responses.push(snapshot({principal_role: "facilitator", requests: [question({requester_id: "learner", requester_role: "soc_analyst"})]}));
    await m.session.refresh();
    assert.equal(m.form.elements.request_id.value, "question-a");
    assert.equal(m.form.elements.message.value, "Coaching draft");
    await m.form.events.submit({preventDefault() {}});
    assert.equal(m.calls.length, 2); // No selected scope, no POST.
    m.responses.push(snapshot({principal_role: "facilitator", run_state: "stopped", requests: [question({requester_id: "learner", requester_role: "soc_analyst"})]}));
    await m.session.refresh();
    assert.equal(m.form.elements.message.value, "");
    assert.equal(m.form.elements.kind.value, "platform_issue");
    assert.equal(m.form.elements.kind.options[0].disabled, true);
    m.form.elements.message.value = "Tool interruption";
    m.checkboxes[1].checked = true;
    m.responses.push({run_id: "run-a"}, snapshot({principal_role: "facilitator", run_state: "stopped", requests: []}));
    await m.form.events.submit({preventDefault() {}});
    assert.equal(JSON.parse(m.calls[3].init.body).kind, "platform_issue");
    assert.deepEqual(JSON.parse(m.calls[3].init.body).objective_ids, ["LO2"]);
  } finally { m.cleanup(); }
});
test("mounted staff drops obsolete reply draft after another staff member answers", async () => {
  const m = mounted(true);
  try {
    await flush();
    m.form.elements.request_id.value = "question-a";
    m.form.elements.message.value = "Obsolete draft";
    m.responses.push(snapshot({principal_role: "facilitator", requests: []}));
    await m.session.refresh();
    assert.equal(m.form.elements.message.value, "");
    assert.equal(m.nodes["#support-send"].disabled, true);
  } finally { m.cleanup(); }
});
test("mounted participant retry bypasses disabled fields and uses the exact first payload", async () => {
  const m = mounted(false);
  try {
    await flush();
    m.form.elements.objective_id.value = "LO2";
    m.form.elements.message.value = "Original question";
    m.responses.push(new Error("network lost"));
    await m.form.events.submit({preventDefault() {}});
    assert.equal(m.form.elements.message.disabled, true);
    assert.equal(m.nodes["#support-send"].textContent, "Retry same message");
    m.form.elements.message.value = "Changed";
    m.responses.push({run_id: "run-a", replayed: true}, snapshot({requests: [question()]}));
    await m.form.events.submit({preventDefault() {}});
    assert.equal(m.calls[1].init.body, m.calls[2].init.body);
    assert.match(m.nodes["#support-summary"].textContent, /no duplicate/);
  } finally { m.cleanup(); }
});
test("a stopped-run rejected coaching retry cannot silently become a platform reply", async () => {
  const m = mounted(true);
  const stopped = snapshot({principal_role: "facilitator", run_state: "stopped", requests: [question({requester_id: "learner", requester_role: "soc_analyst"})]});
  try {
    await flush();
    m.form.elements.request_id.value = "question-a";
    m.form.elements.message.value = "Coaching draft";
    m.checkboxes[1].checked = true;
    m.responses.push(Object.assign(new Error("audit failure"), {status: 503}));
    await m.form.events.submit({preventDefault() {}});
    m.responses.push(stopped);
    await m.session.refresh();
    assert.equal(m.form.elements.kind.value, "clarification");
    assert.equal(m.form.elements.message.value, "Coaching draft");
    m.responses.push(Object.assign(new Error("not committed; coaching stopped"), {status: 409}), stopped);
    await m.form.events.submit({preventDefault() {}});
    assert.equal(JSON.parse(m.calls[3].init.body).kind, "clarification");
    assert.equal(m.form.elements.kind.value, "platform_issue");
    assert.equal(m.form.elements.message.value, "");
    assert.equal(m.session.operation, null);
  } finally { m.cleanup(); }
});
