import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {test} from "node:test";
import {StaffOperations} from "../static/staff-operations.js";

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
const snapshot = (run = "run-a", phase = "running") => ({
  principal_role: "facilitator", controller: {run_id: run, state: phase, items: {}},
  clock: {run_id: run, status: "healthy"},
  readiness: {run_id: run, ready_to_prepare: true, ready_to_start: true},
  impact: {rollback_available: true}, scheduled_mfa: {pending: null}, msel: [],
});
function harness() {
  let credential = "staff-a";
  const replies = [], calls = [];
  const session = new StaffOperations({readToken: () => credential, call: async (path, options) => {
    calls.push({path, options});
    const reply = replies.shift();
    if (reply instanceof Error) throw reply;
    return await reply;
  }});
  const load = async (state = snapshot()) => { replies.push(state); await session.refresh(); };
  return {session, replies, calls, load, credential: (value) => { credential = value; }};
}

test("same-account reconnect cannot overlap a pending ordinary control", async () => {
  const h = harness(); await h.load(); const pending = deferred(); h.replies.push(pending.promise);
  const pause = h.session.command("pause");
  h.session.invalidate("credentials"); await h.load();
  const duplicate = await h.session.command("pause");
  assert.equal(h.calls.filter(({options}) => options.method === "POST").length, 1);
  assert.equal(duplicate, null);
  pending.resolve({}); assert.equal(await pause, null);
  assert.equal(h.session.busy, false);
  assert.equal(h.session.can("pause"), false);
  await h.load(); assert.equal(h.session.can("pause"), true);
});

test("a pending emergency stop blocks ordinary commands but not inspection", async () => {
  const h = harness(); await h.load(); const pending = deferred(); h.replies.push(pending.promise);
  const stop = h.session.command("stop", {reason: "Safety check"});
  await h.load();
  assert.equal(h.session.can("pause"), false);
  assert.equal(h.session.can("stop"), false);
  assert.equal(await h.session.command("pause"), null);
  pending.resolve({stopped: true}); await stop;
  assert.equal(h.session.can("pause"), false);
});

for (const change of ["credentials", "run"]) {
  test(`pending ordinary control stays locked across observed ${change} change`, async () => {
    const h = harness(); await h.load(); const pending = deferred(); h.replies.push(pending.promise);
    const pause = h.session.command("pause");
    if (change === "credentials") h.credential("staff-b");
    await h.load(snapshot(change === "run" ? "run-b" : "run-a"));
    assert.equal(h.session.busy, true);
    assert.equal(h.session.can("pause"), false);
    assert.equal(h.session.can("stop"), true);
    pending.resolve({private: "old receipt"}); assert.equal(await pause, null);
    assert.equal(h.session.busy, false); assert.equal(h.session.state, null);
    assert.equal(h.session.runId, change === "run" ? "run-b" : "run-a");
    await h.load(snapshot(h.session.runId)); assert.equal(h.session.can("pause"), true);
  });
}

test("reconnect does not release a pending stop slot, even for a newly inspected run", async () => {
  const h = harness(); await h.load(); const pending = deferred(); h.replies.push(pending.promise);
  const stop = h.session.command("stop", {reason: "Safety"});
  h.session.invalidate("credentials"); await h.load(snapshot("run-b"));
  assert.equal(h.session.stopBusy, true);
  assert.equal(await h.session.command("stop", {reason: "Second stop"}), null);
  assert.equal(h.session.can("pause"), false);
  pending.resolve({}); assert.equal(await stop, null);
  assert.equal(h.session.stopBusy, false); assert.equal(h.session.can("stop"), true);
  assert.equal(h.session.can("pause"), false);
});

for (const order of ["ordinary-first", "stop-first"]) {
  test(`priority stop supersedes ordinary receipt: ${order}`, async () => {
    const h = harness(); await h.load(); const ordinary = deferred(), emergency = deferred();
    h.replies.push(ordinary.promise); const pause = h.session.command("pause");
    assert.equal(h.session.can("stop"), true);
    h.replies.push(emergency.promise); const stop = h.session.command("stop", {reason: "Safety"});
    if (order === "ordinary-first") {
      ordinary.resolve({paused: true}); assert.equal(await pause, null);
      assert.equal(h.session.stopBusy, true); assert.equal(h.session.can("pause"), false);
      emergency.resolve({stopped: true}); assert.deepEqual(await stop, {stopped: true});
    } else {
      emergency.resolve({stopped: true}); assert.deepEqual(await stop, {stopped: true});
      assert.equal(h.session.busy, true); assert.equal(h.session.can("pause"), false);
      ordinary.resolve({paused: true}); assert.equal(await pause, null);
    }
    assert.equal(h.session.state, null); assert.equal(h.session.busy || h.session.stopBusy, false);
    assert.equal(h.calls.filter(({options}) => options.method === "POST").length, 2);
    assert.ok(h.calls.filter(({options}) => options.method === "POST")
      .every(({options}) => options.headers["X-Exercise-Run-ID"] === "run-a" && options.cache === "no-store"));
  });
}

test("priority stop suppresses an older ordinary command's late failure", async () => {
  const h = harness(); await h.load(); const old = deferred(); h.replies.push(old.promise);
  const pause = h.session.command("pause"); h.replies.push({stopped: true});
  await h.session.command("stop", {reason: "Safety"});
  old.reject(new Error("Private old failure")); assert.equal(await pause, null);
  assert.equal(h.session.busy, false); assert.equal(h.session.state, null);
});

for (const stage of ["before-send", "while-pending"]) {
  for (const outcome of ["success", "failure"]) {
    test(`${stage} GET ${outcome} cannot authorize controls after settlement`, async () => {
      const h = harness(); await h.load(); const old = deferred(), pending = deferred();
      let read;
      if (stage === "before-send") { h.replies.push(old.promise); read = h.session.refresh(); }
      h.replies.push(pending.promise); const pause = h.session.command("pause");
      assert.equal(h.session.state, null); assert.equal(h.session.can("stop"), true);
      if (stage === "while-pending") { h.replies.push(old.promise); read = h.session.refresh(); }
      pending.resolve({}); await pause; await h.load(snapshot("run-a", "paused"));
      if (outcome === "success") old.resolve(snapshot());
      else old.reject(Object.assign(new Error("obsolete auth failure"), {status: 403}));
      await read; assert.equal(h.session.state.controller.state, "paused");
      assert.equal(h.session.can("resume"), true); assert.equal(h.session.can("pause"), false);
    });
  }
}

test("a pre-send GET cannot repopulate controls or private diagnostics while a command is pending", async () => {
  const h = harness(); await h.load(); const old = deferred(), pending = deferred();
  h.replies.push(old.promise); const read = h.session.refresh();
  h.replies.push(pending.promise); const pause = h.session.command("pause");
  old.resolve(snapshot()); await read; assert.equal(h.session.state, null);
  pending.resolve({}); await pause;
});

test("uncertain ordinary command releases its slot but requires new inspection, without replay", async () => {
  const h = harness(); await h.load(); h.replies.push(new Error("lost acknowledgement"));
  await assert.rejects(h.session.command("pause"), /not confirmed.*inspect/);
  assert.equal(h.session.busy, false); assert.equal(h.session.state, null);
  assert.equal(h.session.can("stop"), true);
  assert.equal(await h.session.command("pause"), null);
  assert.equal(h.calls.filter(({options}) => options.method === "POST").length, 1);
});

test("revoked authorization clears stop scope but does not strand request locks", async () => {
  const h = harness(); await h.load(); const pending = deferred(); h.replies.push(pending.promise);
  const pause = h.session.command("pause");
  h.replies.push(Object.assign(new Error("revoked"), {status: 403})); await h.session.refresh();
  assert.equal(h.session.busy, true); assert.equal(h.session.can("stop"), false);
  pending.reject(new Error("obsolete failure")); assert.equal(await pause, null);
  assert.equal(h.session.busy, false); assert.equal(h.session.runId, null);
});

test("a token change observed only at receipt clears old run data and releases the real lock", async () => {
  const h = harness(); await h.load(); const pending = deferred(); h.replies.push(pending.promise);
  const pause = h.session.command("pause"); h.credential("staff-b"); pending.resolve({});
  assert.equal(await pause, null); assert.equal(h.session.state, null);
  assert.equal(h.session.runId, null); assert.equal(h.session.busy, false);
});

class Element {
  constructor() { this.children = []; this.events = {}; this.dataset = {}; this.value = ""; this.textContent = ""; }
  addEventListener(name, callback) { this.events[name] = callback; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  set innerHTML(value) { this.children = Array.from({length: 5}, () => new Element()); }
  querySelector(selector) { this.nodes ??= new Map(); if (!this.nodes.has(selector)) this.nodes.set(selector, new Element()); return this.nodes.get(selector); }
}
function mounted() {
  let credential = "";
  const nodes = new Map(), replies = [], calls = [], handlers = new Map(), confirmations = [];
  const buttons = ["prepare", "start", "pause", "resume"].map((command) => {
    const button = new Element(); button.dataset.command = command; return button;
  });
  const select = (id) => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  let session;
  class InjectedOperations extends StaffOperations {
    constructor(options) {
      super({...options, readToken: () => credential, call: async (path, options) => {
        calls.push({path, options}); const reply = replies.shift(); if (reply instanceof Error) throw reply; return await reply;
      }}); session = this;
    }
  }
  const context = vm.createContext({StaffOperations: InjectedOperations, mountSupport() {}, renderOperations() {}, saveText() {},
    token: () => credential, connect(input, callback) { credential = input.value.trim(); input.value = ""; return callback(); },
    clearNotice: (element) => { element.textContent = ""; }, formatElapsed: () => "00:00:00",
    setStatus: (element, value) => { element.textContent = value; }, notify: (element, value) => { element.textContent = value; },
    setInterval: () => 1, clearInterval() {}, window: {confirm: (message) => { confirmations.push(message); return true; },
      addEventListener: (name, callback) => { handlers.set(name, callback); }},
    document: {querySelector: select, querySelectorAll: () => buttons, createElement: () => new Element()}});
  new vm.Script(readFileSync(new URL("../static/facilitator.js", import.meta.url), "utf8")
    .replace(/^import .*;\n/gm, "")).runInContext(context);
  const load = async (run = "run-a", phase = "running", overrides = {}) => {
    replies.push({...snapshot(run, phase), events: [], submissions: [], dp2_preview: {checks: {}},
      cloud: {enabled: false}, profile_initialization: {profile_count: 1, catalog_sha256: "a".repeat(64),
        bindings: {identity: {display_name: "Synthetic"}, helpdesk: {display_name: "Synthetic"}}},
      scheduled_mfa: {pending: null, history: []}, ...overrides});
    await select("#refresh").events.click();
  };
  return {session, select, buttons, replies, calls, handlers, confirmations, load, credential: (value) => { credential = value; }};
}
const turn = () => new Promise((resolve) => setImmediate(resolve));

test("actual facilitator binding keeps ordinary controls disabled across reconnect until post-settlement inspection", async () => {
  const m = mounted(); m.credential("staff-a"); await m.load();
  const pending = deferred(); m.replies.push(pending.promise);
  const pause = m.buttons[2].events.click();
  assert.ok(m.buttons.every((button) => button.disabled));
  assert.equal(m.select("#stop").disabled, false);
  assert.match(m.select("#control-status").textContent, /awaiting confirmation/);
  m.select("#token-input").value = "staff-a";
  m.select("#connect").events.click(); await turn(); await m.load();
  await m.buttons[2].events.click();
  assert.equal(m.calls.filter(({options}) => options.method === "POST").length, 1);
  pending.resolve({}); await pause;
  assert.ok(m.buttons.every((button) => button.disabled));
  assert.doesNotMatch(m.select("#notice").textContent, /completed and recorded/);
  await m.load(); assert.equal(m.buttons[2].disabled, false);
});

test("actual stop binding prevents ordinary overlap and suppresses the older command notice", async () => {
  const m = mounted(); m.credential("staff-a"); await m.load();
  const ordinary = deferred(), stop = deferred(); m.replies.push(ordinary.promise);
  const pause = m.buttons[2].events.click(); m.select("#stop-reason").value = "Safety";
  m.replies.push(stop.promise); const stopping = m.select("#stop").events.click();
  assert.equal(m.select("#stop").disabled, true);
  assert.match(m.select("#control-status").textContent, /Emergency stop awaiting/);
  await m.load(); assert.ok(m.buttons.every((button) => button.disabled));
  ordinary.reject(new Error("old error")); await pause;
  assert.equal(m.select("#notice").textContent, "");
  stop.resolve({stopped: true}); await stopping;
  assert.equal(m.calls.filter(({options}) => options.method === "POST").length, 2);
});

test("actual stale control failure cannot show after same-token reconnect", async () => {
  const m = mounted(); m.credential("staff-a"); await m.load(); const pending = deferred(); m.replies.push(pending.promise);
  const pause = m.buttons[2].events.click(); m.select("#token-input").value = "staff-a";
  m.select("#connect").events.click(); await turn(); await m.load();
  const reads = m.calls.length; pending.reject(new Error("old failure")); await pause;
  assert.equal(m.select("#notice").textContent, ""); assert.equal(m.calls.length, reads);
});

test("actual observed run change clears a prior command success notice and drafts", async () => {
  const m = mounted(); m.credential("staff-a"); await m.load();
  m.select("#notice").textContent = "Control action completed and recorded.";
  m.select("#stop-reason").value = "old reason"; m.select("#new-run-id").value = "old draft";
  await m.load("run-b");
  assert.equal(m.select("#notice").textContent, "");
  assert.equal(m.select("#stop-reason").value, ""); assert.equal(m.select("#new-run-id").value, "");
});

test("actual rendering failure after observed run change removes ordinary control authority", async () => {
  const m = mounted(); m.credential("staff-a"); await m.load();
  await m.load("run-b", "running", {events: [null]});
  assert.equal(m.session.state, null); assert.equal(m.session.can("pause"), false);
  assert.ok(m.buttons.every((button) => button.disabled));
  assert.equal(m.select("#run-id").textContent, "—");
  assert.equal(m.session.can("stop"), true);
});

test("actual pagehide clears private views but retains the pending request lock", async () => {
  const m = mounted(); m.credential("staff-a"); await m.load(); const pending = deferred(); m.replies.push(pending.promise);
  const pause = m.buttons[2].events.click(); m.handlers.get("pagehide")();
  assert.equal(m.session.busy, true); assert.equal(m.session.runId, null);
  assert.ok(m.buttons.every((button) => button.disabled));
  pending.resolve({}); await pause; assert.equal(m.session.busy, false);
  assert.equal(m.select("#run-id").textContent, "—");
});

test("all facilitator run controls and current-run exports start disabled in HTML", () => {
  const html = readFileSync(new URL("../static/facilitator.html", import.meta.url), "utf8");
  const buttons = html.match(/<button\b[^>]*(?:data-command=|id="(?:resolve-dp[234]|rollback-impact|download-(?:jsonl|csv)|stop|reset|advance|mfa-(?:approve|deny))")[^>]*>/g);
  assert.equal(buttons.length, 15); assert.ok(buttons.every((button) => /\sdisabled(?:\s|>)/.test(button)));
});

test("actual facilitator bindings pin all existing command routes and cannot duplicate a pending request", async () => {
  const cases = [
    ...["prepare", "start", "pause", "resume"].map((action, index) =>
      ({action, phase: index < 2 ? "ready" : index === 2 ? "running" : "paused", button: index})),
    {action: "advance", id: "#advance"}, {action: "reset", id: "#reset", phase: "stopped"},
    {action: "impact/rollback", id: "#rollback-impact", overrides: {impact: {enabled: false, rollback_available: true}}},
    ...[2, 3, 4].map((number) => ({action: `checkpoints/dp${number}`, id: `#resolve-dp${number}`,
      overrides: {controller: {run_id: "run-a", state: "running", items: {[`DP${number}`]: {status: "ready"}}}}})),
    ...["approve", "deny"].map((decision) => ({action: "mfa/decision", id: `#mfa-${decision}`,
      overrides: {scheduled_mfa: {pending: {id: "challenge-a", msel_id: "MSEL-01", expires_in_seconds: 10}, history: []}}})),
    ...["deliver", "skip"].map((action) => ({action, id: "#msel-body", delegated: true,
      overrides: {msel: [{item_id: "MSEL-01", title: "Synthetic", kind: "inject", delivery: "manual", trigger: "timed", phase: "identity", status: "pending", trigger_seconds: 0}]}})),
  ];
  for (const item of cases) {
    const m = mounted(); m.credential("staff-a"); await m.load("run-a", item.phase || "running", item.overrides);
    const pending = deferred(); m.replies.push(pending.promise);
    const button = item.button === undefined ? m.select(item.id) : m.buttons[item.button];
    const event = item.delegated ? {target: {closest: () => ({dataset: {command: item.action, item: "MSEL-01"}})}} : undefined;
    const sending = button.events.click(event); await button.events.click(event);
    const posts = m.calls.filter(({options}) => options.method === "POST");
    assert.equal(posts.length, 1, item.action);
    assert.equal(posts[0].path, `/api/facilitator/${item.action}`);
    assert.equal(posts[0].options.headers["X-Exercise-Run-ID"], "run-a");
    assert.equal(posts[0].options.cache, "no-store");
    pending.resolve({}); await sending;
  }
});

test("actual stop requires a reason and current context but never a confirmation dialog", async () => {
  const m = mounted(); m.credential("staff-a"); await m.load();
  await m.select("#stop").events.click();
  assert.equal(m.calls.filter(({options}) => options.method === "POST").length, 0);
  m.select("#stop-reason").value = "Platform unavailable"; m.replies.push({stopped: true});
  await m.select("#stop").events.click();
  const call = m.calls.find(({options}) => options.method === "POST");
  assert.equal(call.options.headers["X-Exercise-Run-ID"], "run-a");
  assert.equal(JSON.parse(call.options.body).reason, "Platform unavailable");
  assert.equal(m.confirmations.length, 0);
});
