import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {test} from "node:test";
import {EvaluatorReview, revision} from "../static/evaluator-review.js";

const HASH = "a".repeat(64);
const judgment = (number = 1) => ({revision: number, rating: "not_observed", rationale: "Recorded explanation",
  platform_reason: "Missing source", evidence_ids: [], evaluator_id: "staff", timestamp: "now"});
const report = (overrides = {}) => ({run_id: "run-a", run_state: "stopped", bundle_sha256: HASH,
  status: "provisional", reviewed_objectives: 0, submissions: [], timeline: [],
  objectives: ["LO1", "LO2"].map((objective_id) => ({objective_id, title: objective_id,
    observation: {status: "not_observed", explanation: "Synthetic unavailable source"},
    criteria: [], human_review: [], judgment: null, history: []})), ...overrides});
const receipt = (overrides = {}) => ({run_id: "run-a", revision: 1, status: "recorded", event_id: "event-a", ...overrides});
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
function harness() {
  let credential = "reviewer-a";
  const calls = [], responses = [], clears = [];
  const session = new EvaluatorReview({readToken: () => credential, cleared: (reason) => clears.push(reason),
    call: async (path, options) => { calls.push({path, options}); const value = responses.shift();
      if (value instanceof Error) throw value; return await value; }});
  return {session, calls, responses, clears, credential: (value) => { credential = value; }};
}
async function load(h, snapshot = report()) { h.responses.push(snapshot); return h.session.refresh(); }
const submit = (h, fields = {rating: "not_observed", rationale: "Human draft"}) => h.session.submit("LO1", fields);

test("unloaded/unknown/nonterminal objectives cannot be rated; exports require an inspected report", async () => {
  const h = harness(); assert.equal(await submit(h), null); assert.equal(await h.session.download("bundle"), null);
  await load(h, report({run_state: "running"})); assert.equal(h.session.canSave("LO1"), false);
  assert.equal(h.session.canExport(), true); await load(h);
  assert.equal(h.session.canSave("unknown"), false); assert.equal(h.session.canSave("LO1"), true);
  assert.equal(revision(h.session.report, "LO1"), 0);
});
test("save freezes draft, inspected run, objective and expected revision; requires inspection after receipt", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const fields = {rationale: "Original", evidence_ids: ["source"], run_id: "forged", objective_id: "LO2", expected_revision: 99};
  const saving = submit(h, fields); fields.rationale = "Changed"; fields.evidence_ids.push("other");
  const payload = JSON.parse(h.calls[1].options.body);
  assert.equal(payload.rationale, "Original"); assert.deepEqual(payload.evidence_ids, ["source"]);
  assert.equal(payload.run_id, "run-a"); assert.equal(payload.objective_id, "LO1"); assert.equal(payload.expected_revision, 0);
  pending.resolve(receipt()); assert.deepEqual(await saving, receipt());
  assert.equal(h.session.canSave("LO1"), false); assert.equal(h.session.canExport(), false);
});
test("double-click cannot submit twice; inspection during a pending save cannot restore write authority", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const saving = submit(h); assert.equal(await submit(h), null);
  await load(h); assert.equal(h.session.canSave("LO1"), false);
  assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1);
  pending.resolve(receipt()); await saving; assert.equal(h.session.inspectRequired, true);
});
test("lost or invalid acknowledgment never becomes an automatic retry or a confirmed judgment", async () => {
  for (const result of [new Error("lost response"), {}, receipt({run_id: "other"}), receipt({revision: 2}), receipt({status: "unknown"})]) {
    const h = harness(); await load(h); h.responses.push(result);
    await assert.rejects(submit(h), /not confirmed/); assert.equal(await submit(h), null);
    assert.equal(h.session.busy, false); assert.equal(h.session.inspectRequired, true);
    assert.equal(h.calls.length, 2);
  }
});
test("pre-save reads and pre-acknowledgment reads cannot overwrite the confirmed workflow", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const old = h.session.refresh(); h.responses.push(receipt()); await submit(h);
  pending.resolve(report()); assert.equal(await old, null);
  await load(h); const write = deferred(); h.responses.push(write.promise); const saving = submit(h);
  const reading = deferred(); h.responses.push(reading.promise); const beforeAck = h.session.refresh();
  write.resolve(receipt()); await saving; reading.resolve(report()); assert.equal(await beforeAck, null);
  assert.equal(h.session.canSave("LO1"), false);
});
test("newer report reads win; failed refresh removes authority without discarding same-credential draft context", async () => {
  const h = harness(); await load(h); const old = deferred(); h.responses.push(old.promise);
  const reading = h.session.refresh(); await load(h, report({bundle_sha256: "b".repeat(64)}));
  old.resolve(report()); assert.equal(await reading, null); assert.equal(h.session.report.bundle_sha256, "b".repeat(64));
  const clears = h.clears.length; h.responses.push(new Error("offline")); await assert.rejects(h.session.refresh(), /offline/);
  assert.equal(h.session.canSave("LO1"), false); assert.equal(h.clears.length, clears);
});
test("credential change and observed reset discard pending old review receipts and errors", async () => {
  for (const change of ["credentials", "run", "late-error"]) {
    const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
    const saving = submit(h);
    if (change === "credentials") h.credential("reviewer-b");
    await load(h, report({run_id: change === "credentials" ? "run-a" : "run-b"}));
    if (change === "late-error") pending.reject(new Error("old private failure")); else pending.resolve(receipt());
    assert.equal(await saving, null); assert.equal(h.session.busy, false);
  }
});
test("exports pin run and exact bundle snapshot and preserve raw text, including floats", async () => {
  const h = harness(); await load(h);
  for (const kind of ["bundle", "aar"]) {
    const raw = kind === "bundle" ? '{"elapsed":0.0,"scientific":1e-07}' : "# Human review\n";
    h.responses.push(raw); const download = await h.session.download(kind);
    assert.equal(download.payload, raw); assert.match(download.filename, /^run-a-aaaaaaaaaaaa-/);
    const options = h.calls.at(-1).options;
    assert.equal(options.rawText, true); assert.equal(options.headers["X-Exercise-Run-ID"], "run-a");
    assert.equal(options.headers["X-Review-Bundle-SHA256"], HASH);
  }
  assert.equal(await h.session.download("events"), null);
});
test("stale-snapshot download denial asks for inspection; a refreshed older in-flight download is dropped", async () => {
  const h = harness(); await load(h); h.responses.push(Object.assign(new Error("changed"), {status: 409}));
  await assert.rejects(h.session.download("bundle"), /No file was saved/); assert.equal(h.session.canExport(), false);
  await load(h); const pending = deferred(); h.responses.push(pending.promise); const downloading = h.session.download("bundle");
  await load(h, report({bundle_sha256: "b".repeat(64)})); pending.resolve("old review");
  assert.equal(await downloading, null); assert.equal(h.session.canExport(), true);
});
test("late export error cannot invalidate a newer report snapshot", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const downloading = h.session.download("aar"); await load(h, report({bundle_sha256: "b".repeat(64)}));
  pending.reject(Object.assign(new Error("old conflict"), {status: 409}));
  assert.equal(await downloading, null); assert.equal(h.session.canExport(), true);
});
test("auth denial clears private review context and an old-credential download cannot produce a file", async () => {
  const h = harness(); await load(h); const pending = deferred(); h.responses.push(pending.promise);
  const downloading = h.session.download("bundle"); h.credential("reviewer-b"); await load(h);
  pending.resolve("old private content"); assert.equal(await downloading, null);
  h.responses.push(Object.assign(new Error("denied"), {status: 403})); await assert.rejects(h.session.refresh(), /denied/);
  assert.equal(h.session.report, null); assert.equal(h.session.runId, null);
});

class Element {
  constructor(tag = "div") { this.tag = tag; this.children = []; this.events = {}; this.value = ""; this.disabled = false; this.resets = 0; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; if (this.tag === "select") this.value = children[0]?.value || ""; }
  add(child) { this.children.push(child); }
  addEventListener(name, callback) { this.events[name] = callback; }
}
function mounted() {
  let credential = "";
  const nodes = new Map(), calls = [], responses = [], downloads = [];
  const node = (id) => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  const form = node("#judgment");
  const names = ["objective_id", "rating", "rationale", "evidence_ids", "override_reason", "platform_reason", "description", "owner", "priority", "target_date"];
  form.elements = Object.fromEntries(names.map((name) => [name, new Element(["objective_id", "rating", "priority"].includes(name) ? "select" : "input")]));
  form.querySelectorAll = () => Object.values(form.elements);
  form.reset = () => { form.resets += 1; Object.values(form.elements).forEach((field) => { field.value = ""; }); form.elements.priority.value = "medium"; };
  let session;
  class InjectedReview extends EvaluatorReview {
    constructor(options) { super({...options, readToken: () => credential, call: async (path, options) => {
      calls.push({path, options}); const value = responses.shift(); if (value instanceof Error) throw value; return await value;
    }}); session = this; }
  }
  const context = vm.createContext({EvaluatorReview: InjectedReview, revision, mountSupport() {}, mountArchives() {},
    clearNotice: (element) => { element.textContent = ""; }, connect() {},
    notify: (element, message) => { element.textContent = message; },
    saveText: (...args) => downloads.push(args),
    Option: class extends Element { constructor(label, value) { super("option"); this.textContent = label; this.value = value; } },
    FormData: class { get(name) { return form.elements[name].value; } },
    document: {querySelector: node, createElement: (tag) => new Element(tag)}});
  const source = readFileSync(new URL("../static/evaluator.js", import.meta.url), "utf8").replace(/^import .*;\n/gm, "");
  new vm.Script(source).runInContext(context);
  return {session, form, node, calls, responses, downloads, credential: (value) => { credential = value; }};
}
async function refresh(m, snapshot = report()) { m.responses.push(snapshot); await m.node("#refresh").events.click(); }
function select(m, objectiveId = "LO1") { m.form.elements.objective_id.value = objectiveId; m.form.elements.objective_id.events.change(); }

test("actual evaluator refresh preserves complete same-revision draft and clears it on a selected-objective revision change", async () => {
  const m = mounted(); m.credential("reviewer-a"); await refresh(m); select(m);
  m.form.elements.rationale.value = "Unfinished human explanation";
  m.form.elements.description.value = "Follow-up action"; m.form.elements.priority.value = "high";
  await refresh(m, report({bundle_sha256: "b".repeat(64)}));
  assert.equal(m.form.elements.rationale.value, "Unfinished human explanation");
  assert.equal(m.form.elements.description.value, "Follow-up action"); assert.equal(m.form.elements.priority.value, "high");
  assert.equal(m.form.elements.objective_id.value, "LO1");
  const updated = report({bundle_sha256: "c".repeat(64)}); updated.objectives[0].judgment = judgment();
  await refresh(m, updated);
  assert.equal(m.form.elements.rationale.value, "Recorded explanation");
  assert.equal(m.form.elements.description.value, ""); assert.match(m.node("#notice").textContent, /revision changed/);
});
test("actual reset and reconnect clear old private draft/evidence instead of preserving same objective IDs", async () => {
  const m = mounted(); m.credential("reviewer-a"); await refresh(m); select(m); m.form.elements.rationale.value = "Old run draft";
  await refresh(m, report({run_id: "run-b"})); assert.equal(m.form.elements.rationale.value, "");
  assert.equal(m.form.elements.objective_id.value, ""); assert.match(m.node("#notice").textContent, /Run changed/);
  select(m); m.form.elements.rationale.value = "Private reviewer A draft"; m.credential("reviewer-b");
  await refresh(m, report({run_id: "run-b"})); assert.equal(m.form.elements.rationale.value, "");
  assert.equal(m.node("#notice").textContent, "");
});
test("actual save binding freezes objective/run/revision, disables uncertain resubmission, and inspects recorded revision", async () => {
  const m = mounted(); m.credential("reviewer-a"); await refresh(m); select(m);
  m.form.elements.rating.value = "not_observed"; m.form.elements.rationale.value = "My explanation";
  m.form.elements.platform_reason.value = "Missing source";
  m.responses.push(new Error("lost acknowledgment")); await m.form.events.submit({preventDefault() {}});
  const payload = JSON.parse(m.calls.at(-1).options.body);
  assert.equal(payload.run_id, "run-a"); assert.equal(payload.expected_revision, 0); assert.equal(payload.rationale, "My explanation");
  assert.equal(m.node("#save").disabled, true); assert.match(m.node("#notice").textContent, /not confirmed/);
  assert.equal(m.form.elements.rationale.value, "My explanation");
  const saved = report({bundle_sha256: "b".repeat(64)}); saved.objectives[0].judgment = judgment();
  await refresh(m, saved); assert.equal(m.form.elements.rationale.value, "Recorded explanation");
  assert.equal(m.node("#save").disabled, false);
});
test("actual successful save refreshes once and real export binding saves raw pinned text only", async () => {
  const m = mounted(); m.credential("reviewer-a"); await refresh(m); select(m);
  const saved = report({bundle_sha256: "b".repeat(64)}); saved.objectives[0].judgment = judgment();
  m.responses.push(receipt(), saved); await m.form.events.submit({preventDefault() {}});
  assert.equal(m.calls.filter((call) => call.options.method === "POST").length, 1);
  assert.equal(m.node("#save").disabled, true); // No objective selected after confirmed save.
  m.responses.push('{"elapsed":0.0}'); await m.node("#bundle").events.click();
  assert.equal(m.downloads[0][0], '{"elapsed":0.0}'); assert.match(m.downloads[0][1], /^run-a-bbbbbbbbbbbb-/);
  assert.equal(m.calls.at(-1).options.headers["X-Review-Bundle-SHA256"], "b".repeat(64));
});
test("actual stale export cannot create a file, and transient refresh failure retains draft but disables writes", async () => {
  const m = mounted(); m.credential("reviewer-a"); await refresh(m); select(m);
  m.form.elements.rationale.value = "Retained draft";
  m.responses.push(Object.assign(new Error("snapshot changed"), {status: 409})); await m.node("#aar").events.click();
  assert.equal(m.downloads.length, 0); assert.equal(m.node("#aar").disabled, true);
  m.responses.push(new Error("offline")); await m.node("#refresh").events.click();
  assert.equal(m.form.elements.rationale.value, "Retained draft"); assert.equal(m.node("#save").disabled, true);
  assert.match(m.node("#review-summary").textContent, /unavailable/);
});
