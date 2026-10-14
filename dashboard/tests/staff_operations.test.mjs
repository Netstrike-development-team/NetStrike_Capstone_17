import assert from "node:assert/strict";
import {test} from "node:test";
import {api} from "../static/common.js";
import {StaffOperations, permitted, renderOperations} from "../static/staff-operations.js";
import {ReviewArchives, renderArchivePage, renderSavedReview, mountArchives} from "../static/review-archives.js";

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
const fault = (status) => Object.assign(new Error("private failure"), {status});
function state(phase = "ready", overrides = {}) {
  return {principal_role: "facilitator", controller: {run_id: "run-a", state: phase, items: {DP2: {status: "ready"}}},
    clock: {run_id: "run-a", status: "healthy", heartbeat_age_seconds: 0, stale_after_seconds: 30, successful_ticks: 1},
    readiness: {run_id: "run-a", ready_to_prepare: true, ready_to_start: true, checks: [{check_id: "baseline", passed: true, code: "matched"}]},
    impact: {rollback_available: true}, scheduled_mfa: {pending: {}},
    msel: [{item_id: "MSEL-01", status: "pending", trigger: "timed", phase: "identity"}], ...overrides};
}
const bundle = (run_state = "stopped") => ({run_id: "run-a", run_state, content_sha256: "a".repeat(64), events: [], submissions: []});
const record = (archive_id = "saved-a") => ({archive_id, run_id: "old-run", run_state: "stopped", captured_at: "now",
  capture_reason: "explicit_capture", reviewed_objectives: 1, review_status: "provisional", event_count: 10,
  last_sequence: 10, submission_count: 1, captured_by: {actor_id: "staff-a", role: "evaluator"}});
const page = () => ({archives: [record()], has_more: true, next_sequence: 10});
function harness(Model = StaffOperations, extra = {}) {
  let credential = "staff-a";
  const responses = [], calls = [];
  const session = new Model({readToken: () => credential, call: async (path, init) => {
    calls.push({path, init}); const result = responses.shift(); if (result instanceof Error) throw result; return await result;
  }, ...extra});
  return {session, responses, calls, credential: (value) => { credential = value; }};
}
async function load(h, snapshot = state()) { h.responses.push(snapshot); await h.session.refresh(); }
async function list(h, snapshot = page()) { h.responses.push(snapshot); await h.session.list(); }
async function preview(h, snapshot = bundle()) { h.responses.push(snapshot); await h.session.preview(); }

test("role/lifecycle/readiness controls do not offer invalid ordinary operations", () => {
  assert.equal(permitted(null, "start"), false);
  assert.equal(permitted(state("ready", {principal_role: "evaluator"}), "stop"), false);
  assert.equal(permitted(state("ready", {readiness: {ready_to_prepare: false, ready_to_start: false}}), "start"), false);
  assert.equal(permitted(state(), "prepare"), true);
  assert.equal(permitted(state("running"), "prepare"), false);
  assert.equal(permitted(state("running"), "pause"), true);
  assert.equal(permitted(state("paused"), "resume"), true);
  assert.equal(permitted(state("stopped"), "reset"), true);
  assert.equal(permitted(state("completed"), "stop"), false);
  assert.equal(permitted(state("running"), "checkpoints/dp2"), true);
  assert.equal(permitted(state("running"), "checkpoints/dp3"), false);
  assert.equal(permitted(state("running", {principal_role: "technical_operator"}), "mfa/decision"), false);
  assert.equal(permitted(state("running"), "mfa/decision"), true);
  assert.equal(permitted(state(), "deliver", {item_id: "MSEL-01"}), true);
  assert.equal(permitted(state("stopped"), "skip", {item_id: "MSEL-01"}), false);
  assert.equal(permitted(state("running", {msel: [{item_id: "DP3", status: "ready", trigger: "checkpoint", phase: "cloud"}]}), "deliver", {item_id: "DP3"}), false);
});
test("fault, stale and detached clocks block ordinary play, not stop/reset/rollback", () => {
  for (const status of ["faulted", "stale", "detached", "invalid_clock"]) {
    assert.equal(permitted(state("running", {clock: {status}}), "pause"), false);
    assert.equal(permitted(state("running", {clock: {status}}), "stop"), true);
    assert.equal(permitted(state("stopped", {clock: {status}}), "reset"), true);
    assert.equal(permitted(state("stopped", {clock: {status}}), "impact/rollback"), true);
  }
});
test("disconnected staff do not request or issue controls", async () => {
  const h = harness(); h.credential(""); await h.session.refresh();
  assert.equal(await h.session.command("stop", {reason: "safety"}), null);
  assert.equal(h.calls.length, 0);
});
test("command pins inspected run and invalidates pre-write controls", async () => {
  const h = harness(); await load(h); h.responses.push({controller: {run_id: "run-a"}});
  await h.session.command("start");
  assert.equal(h.calls[1].init.headers["X-Exercise-Run-ID"], "run-a");
  assert.equal(h.session.can("start"), false);
});
test("emergency stop remains usable during a pending ordinary operation", async () => {
  const h = harness(); await load(h, state("running")); const pending = deferred();
  h.responses.push(pending.promise); const pause = h.session.command("pause");
  assert.equal(h.session.can("pause"), false); assert.equal(h.session.can("stop"), true);
  h.responses.push({stopped: true}); await h.session.command("stop", {reason: "safety"});
  assert.equal(JSON.parse(h.calls[2].init.body).reason, "safety");
  pending.resolve({}); await pause;
});
test("failed read clears private data but retains known run scope for emergency stop", async () => {
  const h = harness(); await load(h); h.responses.push(new Error("offline")); await h.session.refresh();
  assert.equal(h.session.state, null); assert.equal(h.session.can("start"), false);
  assert.equal(h.session.can("stop"), true); assert.equal(h.session.runId, "run-a");
  h.responses.push(fault(403)); await h.session.refresh();
  assert.equal(h.session.can("stop"), false); assert.equal(h.session.runId, null);
});
test("uncertain control is not automatically repeated or reported successful", async () => {
  const h = harness(); await load(h); h.responses.push(new Error("connection lost"));
  await assert.rejects(h.session.command("start"), /not confirmed/);
  assert.equal(await h.session.command("start"), null); assert.equal(h.calls.length, 2);
});
test("newer state read wins, and a command acknowledgment discards pre-write reads", async () => {
  const h = harness(); await load(h); const old = deferred(); h.responses.push(old.promise);
  const read = h.session.refresh(); await load(h, state("running")); old.resolve(state()); await read;
  assert.equal(h.session.state.controller.state, "running");
  const another = deferred(); h.responses.push(another.promise); const before = h.session.refresh();
  h.responses.push({}); await h.session.command("pause"); another.resolve(state("running")); await before;
  assert.equal(h.session.state, null);
});
test("credential switch discards pending control and old private snapshot", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const command = h.session.command("start"); h.credential("staff-b");
  await load(h, state("running", {principal_role: "technical_operator"}));
  pending.resolve({private: true}); assert.equal(await command, null);
  assert.equal(h.session.role, "technical_operator"); assert.equal(h.session.busy, false);
});
test("observed reset discards old pending command and adopts only coherent new run", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const command = h.session.command("start");
  const fresh = state(); fresh.controller.run_id = fresh.clock.run_id = fresh.readiness.run_id = "run-b";
  await load(h, fresh); pending.resolve({}); assert.equal(await command, null);
  assert.equal(h.session.runId, "run-b");
  fresh.clock.run_id = "wrong"; await load(h, fresh); assert.equal(h.session.state, null);
});
test("event download preserves raw text and pins the run", async () => {
  const h = harness(); await load(h); const raw = '{"sequence":1}\n{"sequence":2}\n'; h.responses.push(raw);
  assert.deepEqual(await h.session.exportEvents("jsonl"), {runId: "run-a", payload: raw});
  assert.equal(h.calls[1].init.rawText, true); assert.equal(h.calls[1].init.headers["X-Exercise-Run-ID"], "run-a");
  assert.equal(await h.session.exportEvents("html"), null);
});
test("stale event download is dropped after credentials change", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const download = h.session.exportEvents("csv"); h.credential("new"); pending.resolve("private");
  assert.equal(await download, null);
});
test("common API raw mode does not parse JSONL or rewrite portable floats", async () => {
  globalThis.sessionStorage = {getItem: () => "token"};
  const raw = '{"value":1.0}\n{"value":2.0}\n';
  globalThis.fetch = async () => ({ok: true, headers: new Headers({"content-type": "application/x-ndjson"}),
    text: async () => raw, json: async () => { throw new Error("must not parse"); }});
  try { assert.equal(await api("/exports", {rawText: true}), raw); }
  finally { delete globalThis.fetch; delete globalThis.sessionStorage; }
});
test("only terminal preview enables exact run/hash capture", async () => {
  const h = harness(ReviewArchives); await preview(h, bundle("running")); assert.equal(h.session.candidate, null);
  assert.equal(await h.session.capture(), null); await preview(h);
  h.responses.push({status: "captured", metadata: record()}); await h.session.capture();
  assert.deepEqual(JSON.parse(h.calls[2].init.body), {run_id: "run-a", expected_bundle_sha256: "a".repeat(64)});
  assert.equal(h.session.candidate, null); assert.equal(h.session.busy, false);
});
test("double-click capture cannot duplicate the write", async () => {
  const h = harness(ReviewArchives); await preview(h); const pending = deferred(); h.responses.push(pending.promise);
  const write = h.session.capture(); assert.equal(await h.session.capture(), null); assert.equal(h.calls.length, 2);
  pending.resolve({metadata: record()}); await write;
});
test("uncertain capture keeps the exact retry hash and blocks silent replacement", async () => {
  const h = harness(ReviewArchives); await preview(h); h.responses.push(fault(409)); await h.session.capture();
  assert.equal(h.session.uncertain, true); await h.session.preview(); assert.equal(h.calls.length, 2);
  await list(h); h.responses.push({status: "already_captured", metadata: record()}); await h.session.capture();
  assert.equal(h.calls[1].init.body, h.calls[3].init.body); assert.match(h.session.message, /existing capture confirmed/);
});
test("replacing uncertain capture requires explicit replacement and a fresh preview", async () => {
  const h = harness(ReviewArchives); await preview(h); h.responses.push(new Error("network")); await h.session.capture();
  h.responses.push({...bundle(), content_sha256: "b".repeat(64)}); await h.session.preview({replaceUncertain: true});
  assert.equal(h.session.uncertain, false); assert.equal(h.session.candidate.expected_bundle_sha256, "b".repeat(64));
});
test("auth rejection clears archive list, candidate and historical report", async () => {
  const h = harness(ReviewArchives); await list(h); await preview(h); h.session.report = {private: true};
  h.responses.push(fault(403)); await h.session.capture();
  assert.equal(h.session.page, null); assert.equal(h.session.candidate, null); assert.equal(h.session.report, null);
});
test("stale archive list and capture responses cannot cross credentials", async () => {
  const h = harness(ReviewArchives); const pending = deferred(); h.responses.push(pending.promise);
  const read = h.session.list(); h.credential("staff-b"); await list(h, {archives: [], has_more: false});
  pending.resolve(page()); await read; assert.equal(h.session.page.archives.length, 0);
  await preview(h); const write = deferred(); h.responses.push(write.promise); const capture = h.session.capture();
  h.credential("staff-c"); h.session.sync(); write.resolve({metadata: record()});
  assert.equal(await capture, null); assert.equal(h.session.candidate, null);
});
test("pagination replaces historical report; failed page read invalidates pending report", async () => {
  const h = harness(ReviewArchives); await list(h); const pending = deferred(); h.responses.push(pending.promise);
  const read = h.session.show("saved-a"); h.responses.push(new Error("unavailable")); await h.session.list(10);
  pending.resolve({run_id: "private-old"}); await read;
  assert.equal(h.session.page, null); assert.equal(h.session.report, null);
  assert.match(h.session.message, /not treat this as an empty history/);
  assert.match(h.calls[2].path, /after_sequence=10&limit=10/);
});
test("historical reads use only listed IDs and never write current ratings", async () => {
  const h = harness(ReviewArchives); await list(h); await h.session.show("not-listed");
  h.responses.push({run_id: "old-run", objectives: []}); await h.session.show("saved-a");
  assert.equal(h.session.report.report.run_id, "old-run");
  assert.equal(h.calls.length, 2); assert.ok(h.calls.every(({init}) => !init.method));
});
test("archive bundle downloads retain exact bytes and bind credentials", async () => {
  const raw = '{"value":1.0,"content_sha256":"digest"}\n';
  const h = harness(ReviewArchives, {readText: async (path, credential) => {
    assert.equal(credential, "staff-a"); assert.match(path, /saved-a\/bundle.json$/); return raw;
  }}); await list(h);
  assert.equal((await h.session.download("saved-a", "bundle.json")).payload, raw);
  assert.equal(await h.session.download("saved-a", "unknown"), null);
});
test("pending archive downloads are discarded on auth change; revoked access clears list", async () => {
  const pending = deferred(); const h = harness(ReviewArchives, {readText: async () => pending.promise}); await list(h);
  const download = h.session.download("saved-a", "aar.md"); h.credential("staff-b"); pending.resolve("private");
  assert.equal(await download, null); await list(h);
  h.session.readText = async () => { throw fault(403); };
  await assert.rejects(h.session.download("saved-a", "aar.md"), /No file/); assert.equal(h.session.page, null);
});

class Element {
  constructor(tag) { this.tag = tag; this.textContent = ""; this.children = []; this.dataset = {}; this.events = {}; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  addEventListener(name, callback) { this.events[name] = callback; }
}
const contents = (node) => [node.textContent, ...node.children.map(contents)].join(" ");
function dom(selectors) {
  const nodes = Object.fromEntries(selectors.map((selector) => [selector, new Element("div")]));
  globalThis.document = {querySelector: (selector) => nodes[selector], createElement: (tag) => new Element(tag)};
  return nodes;
}
test("readiness panel keeps external limits explicit and avoids false in-play baseline blockers", () => {
  const nodes = dom(["#local-readiness", "#clock-health"]);
  try {
    renderOperations(state()); assert.match(contents(nodes["#local-readiness"]), /not verified here/);
    renderOperations(state("running")); assert.match(contents(nodes["#local-readiness"]), /not applicable/);
    renderOperations(null); assert.match(contents(nodes["#clock-health"]), /Do not assume/);
    renderOperations(state("stopped", {clock: {status: "faulted", fault_code: "driver_failed", cleanup_complete: false, fault_audit_persisted: false}}));
    assert.match(contents(nodes["#clock-health"]), /cleanup not confirmed.*audit not confirmed/);
  } finally { delete globalThis.document; }
});
test("archive and rationale prose are literal, read-only and clearly cutoff-scoped", () => {
  dom([]); const container = new Element("div");
  try {
    const saved = record(); saved.run_id = '<script>bad()</script>'; renderArchivePage(container, {...page(), archives: [saved]});
    assert.match(contents(container), /<script>bad\(\)<\/script>/); assert.match(contents(container), /Not a VM backup/);
    renderSavedReview(container, {identifier: "saved-a", report: {run_id: "old-run", reviewed_objectives: 1, status: "provisional", objectives: [
      {objective_id: "LO1", title: "Triage", judgment: {rating: "not_observed", rationale: '<img onerror="bad()">'}}]}});
    assert.match(contents(container), /does not load or edit the current judgment form/); assert.match(contents(container), /<img onerror/);
    assert.ok(container.children.every((node) => !["form", "input", "textarea"].includes(node.tag)));
  } finally { delete globalThis.document; }
});
test("archive mount initializes safely and wires preview, capture, pagination and teardown", async () => {
  const nodes = dom(["#archive-summary", "#archive-list", "#saved-review", "#archive-capture", "#archive-next", "#archive-prepare", "#archive-refresh", "#connect"]);
  let teardown; globalThis.window = {confirm: () => false, addEventListener: (name, callback) => { if (name === "pagehide") teardown = callback; }};
  const h = harness(ReviewArchives); h.responses.push(page());
  try {
    const session = mountArchives({sessionOptions: {call: h.session.call, readToken: h.session.readToken}});
    await new Promise((resolve) => setImmediate(resolve)); assert.equal(nodes["#archive-capture"].disabled, true);
    h.responses.push(bundle()); nodes["#archive-prepare"].events.click(); await new Promise((resolve) => setImmediate(resolve));
    assert.equal(nodes["#archive-capture"].disabled, false);
    h.responses.push({metadata: record()}, page()); await nodes["#archive-capture"].events.click();
    assert.match(nodes["#archive-summary"].textContent, /Saved run/);
    h.responses.push({archives: [], has_more: false}); nodes["#archive-next"].events.click(); await new Promise((resolve) => setImmediate(resolve));
    assert.match(h.calls.at(-1).path, /after_sequence=10/);
    teardown(); assert.equal(session.page, null); assert.equal(session.candidate, null);
  } finally { delete globalThis.document; delete globalThis.window; }
});
