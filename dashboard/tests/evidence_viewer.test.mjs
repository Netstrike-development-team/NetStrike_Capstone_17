import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {test} from "node:test";

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
const signal = (sequence = 1, event_id = `event-${sequence}`, overrides = {}) => ({
  event_id, sequence, timestamp: "2026-10-08T12:00:00Z", category: "response",
  source: "synthetic-source", event_type: "action.execution.completed",
  message: "Synthetic response receipt", outcome: "success", actor_id: "learner-a",
  target_id: "synthetic-session", target_type: "session", dry_run: false, facts: {}, ...overrides,
});
const page = (signals = [signal()], overrides = {}) => ({run_id: "run-a", state: "running",
  elapsed_seconds: 30, signals, next_sequence: signals.at(-1)?.sequence ?? 0,
  has_more: false, ...overrides});

class Element {
  constructor(tag = "div") { this.tag = tag; this.children = []; this.events = {}; this.dataset = {}; this.value = ""; this.disabled = false; }
  addEventListener(name, callback) { this.events[name] = callback; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this[name] = value; }
}
function mounted() {
  let credential = "";
  const nodes = new Map(), responses = [], calls = [], timers = [];
  const node = (id) => {
    if (!nodes.has(id)) nodes.set(id, new Element());
    return nodes.get(id);
  };
  node("#category").value = "all";
  const context = vm.createContext({AbortController, token: () => credential,
    api: async (path, options) => {
      calls.push({path, options, credential});
      const response = responses.shift();
      if (response instanceof Error) throw response;
      return await response;
    },
    connect: (input, callback) => { credential = input.value.trim(); input.value = ""; return callback(); },
    clearNotice: (element) => { element.textContent = ""; },
    notify: (element, value) => { element.textContent = value; },
    formatElapsed: (value) => `${value}s`, setStatus: (element, value) => { element.textContent = value; },
    setInterval: (callback) => { timers.push(callback); },
    document: {querySelector: node, createElement: (tag) => new Element(tag)}});
  const source = readFileSync(new URL("../static/evidence.js", import.meta.url), "utf8")
    .replace(/^import .*;\n/gm, "");
  new vm.Script(source).runInContext(context);
  return {node, calls, responses, timers, credential: (value) => { credential = value; },
    refresh: () => node("#refresh").events.click(),
    connect: (value) => { node("#token-input").value = value; return node("#connect").events.click(); }};
}
async function load(h, value = page()) { h.responses.push(value); return h.refresh(); }
const references = (h) => h.node("#signals").children.map((card) => card.dataset.eventId).filter(Boolean);

test("switching credentials clears existing receipts immediately despite an old pending request", async () => {
  const h = mounted(); h.credential("learner-a"); await load(h);
  const old = deferred(), fresh = deferred(); h.responses.push(old.promise);
  const request = h.refresh(); h.responses.push(fresh.promise);
  const connect = h.connect("learner-b");
  assert.equal(h.calls[1].options.signal.aborted, true);
  assert.equal(references(h).length, 0);
  assert.notEqual(h.node("#run-id").textContent, "run-a");
  old.resolve(page([signal(2, "old-private-receipt")])); await request;
  assert.equal(references(h).length, 0);
  assert.equal(h.node("#refresh").disabled, true);
  fresh.resolve(page([signal(1, "new-receipt", {actor_id: "learner-b"})])); await connect;
  assert.deepEqual(references(h), ["new-receipt"]);
});

test("disconnected polling makes no request and clears metadata after token removal", async () => {
  const h = mounted(); await h.refresh(); assert.equal(h.calls.length, 0);
  h.credential("learner-a"); await load(h); h.credential(""); await h.timers[0]();
  assert.equal(h.calls.length, 1); assert.equal(references(h).length, 0);
  assert.equal(h.node("#run-state").textContent, "disconnected");
  assert.equal(h.node("#elapsed").textContent, "00:00:00");
  assert.equal(h.node("#signal-count").textContent, 0);
});

for (const failed of [false, true]) {
  test(`observed token ABA discards late ${failed ? "failure" : "success"} without clearing new evidence`, async () => {
    const h = mounted(); h.credential("learner-a"); await load(h);
    const old = deferred(), middle = deferred(); h.responses.push(old.promise);
    const first = h.refresh(); h.responses.push(middle.promise);
    const second = h.connect("learner-b");
    h.responses.push(page([signal(1, "fresh-a")])); await h.connect("learner-a");
    assert.deepEqual(references(h), ["fresh-a"]);
    middle.reject(new Error("private learner-b failure")); await second;
    if (failed) old.reject(new Error("private old learner-a failure"));
    else old.resolve(page([signal(2, "stale-a")]));
    await first;
    assert.deepEqual(references(h), ["fresh-a"]);
    assert.equal(h.node("#notice").textContent, "");
    assert.equal(h.node("#refresh").disabled, false);
  });
}

test("explicit same-token reconnect invalidates pending callbacks and resets the cursor", async () => {
  const h = mounted(); h.credential("learner-a"); await load(h);
  const old = deferred(); h.responses.push(old.promise); const request = h.refresh();
  h.responses.push(page([signal(1, "reconnected")])); await h.connect("learner-a");
  assert.match(h.calls.at(-1).path, /after_sequence=0/);
  old.resolve(page([signal(2, "old-copy")])); await request;
  assert.deepEqual(references(h), ["reconnected"]);
});

test("an externally observed token switch drops old failure and starts fresh without busy lockout", async () => {
  const h = mounted(); h.credential("learner-a"); await load(h);
  const old = deferred(); h.responses.push(old.promise); const request = h.refresh();
  h.credential("learner-b"); old.reject(new Error("private old failure")); await request;
  assert.equal(references(h).length, 0); assert.equal(h.node("#notice").textContent, "");
  h.responses.push(page([signal(1, "new-view")])); await h.timers[0]();
  assert.match(h.calls.at(-1).path, /after_sequence=0/);
  assert.deepEqual(references(h), ["new-view"]);
});

test("polling follows current-run cursors, disables concurrent reads and bypasses browser caching", async () => {
  const h = mounted(); h.credential("learner-a");
  h.responses.push(page([signal(1), signal(3)], {has_more: true}), page([signal(5)]));
  await h.refresh(); assert.match(h.calls[1].path, /after_sequence=3/);
  assert.deepEqual(references(h), ["event-5", "event-3", "event-1"]);
  assert.equal(h.calls[0].options.cache, "no-store");
  const pending = deferred(); h.responses.push(pending.promise); const request = h.refresh();
  await h.refresh(); await h.timers[0](); assert.equal(h.calls.length, 3);
  pending.resolve(page([], {next_sequence: 5, state: "paused", elapsed_seconds: 90})); await request;
  assert.equal(h.node("#run-state").textContent, "paused");
  assert.equal(h.node("#elapsed").textContent, "90s");
  assert.deepEqual(references(h), ["event-5", "event-3", "event-1"]);
});

test("reset during pagination discards the wrong-run cursor and refetches new run from zero", async () => {
  const h = mounted(); h.credential("learner-a"); await load(h);
  h.node("#search").value = "old-private-search"; h.node("#category").value = "response";
  h.responses.push(page([signal(2, "old-new-signal")], {has_more: true}),
    page([], {run_id: "run-b", next_sequence: 2}),
    page([signal(1, "fresh-run")], {run_id: "run-b"}));
  await h.refresh(); assert.match(h.calls.at(-1).path, /after_sequence=0/);
  assert.deepEqual(references(h), ["fresh-run"]);
  assert.equal(h.node("#run-id").textContent, "run-b");
  assert.equal(h.node("#search").value, ""); assert.equal(h.node("#category").value, "all");
});

test("bounded catch-up retains 500 newest signals and discloses unfinished pagination", async () => {
  const h = mounted(); h.credential("learner-a");
  for (let batch = 0; batch < 10; batch += 1) {
    h.responses.push(page(Array.from({length: 100}, (_, n) => signal(batch * 100 + n + 1)), {has_more: true}));
  }
  await h.refresh(); assert.equal(h.calls.length, 10);
  assert.equal(references(h).length, 500);
  assert.equal(references(h)[0], "event-1000"); assert.equal(references(h).at(-1), "event-501");
  assert.match(h.node("#signal-summary").textContent, /More evidence pages remain/);
  h.responses.push(page([signal(1001)])); await h.refresh();
  assert.match(h.calls.at(-1).path, /after_sequence=1000/);
  assert.doesNotMatch(h.node("#signal-summary").textContent, /More evidence pages remain/);
  assert.equal(references(h)[0], "event-1001"); assert.equal(references(h).length, 500);
});

test("a run change at the page budget boundary clears the view and continues at zero next refresh", async () => {
  const h = mounted(); h.credential("learner-a");
  for (let i = 1; i < 10; i += 1) h.responses.push(page([signal(i)], {has_more: true}));
  h.responses.push(page([], {run_id: "run-b", next_sequence: 9})); await h.refresh();
  assert.equal(references(h).length, 0); assert.match(h.node("#signal-summary").textContent, /More evidence pages remain/);
  h.responses.push(page([signal(1, "new-run")], {run_id: "run-b"})); await h.refresh();
  assert.match(h.calls.at(-1).path, /after_sequence=0/);
  assert.deepEqual(references(h), ["new-run"]);
});

for (const status of [undefined, 401, 403]) {
  test(`current ${status || "transport"} failure clears receipts, cursor and run metadata`, async () => {
    const h = mounted(); h.credential("learner-a"); await load(h);
    h.responses.push(Object.assign(new Error("Current evidence unavailable"), {status})); await h.refresh();
    assert.equal(references(h).length, 0); assert.equal(h.node("#latest-sequence").textContent, "—");
    assert.equal(h.node("#run-state").textContent, "disconnected");
    assert.equal(h.node("#elapsed").textContent, "00:00:00");
    assert.notEqual(h.node("#run-id").textContent, "run-a");
    assert.match(h.node("#notice").textContent, /unavailable/);
    await load(h); assert.match(h.calls.at(-1).path, /after_sequence=0/);
  });
}

for (const bad of [null, {}, page([], {run_id: ""}), page([], {next_sequence: -1}),
  page([], {next_sequence: 1}), page([], {has_more: true}), page([], {has_more: "yes"}),
  page([signal(2), signal(1)]), page([signal(1), signal(1)]),
  page([signal(1, "")]), page([signal(1.5)]), page(Array.from({length: 101}, (_, n) => signal(n + 1)))]) {
  test(`malformed page is refused without rendering evidence (${JSON.stringify(bad).slice(0, 70)})`, async () => {
    const h = mounted(); h.credential("learner-a"); h.responses.push(bad); await h.refresh();
    assert.equal(references(h).length, 0); assert.equal(h.node("#run-state").textContent, "disconnected");
    assert.match(h.node("#notice").textContent, /unavailable/);
    assert.equal(h.node("#refresh").disabled, false);
  });
}

for (const bad of [page([], {state: null}), page([], {elapsed_seconds: -1}),
  page([], {elapsed_seconds: Infinity}), page([], {elapsed_seconds: "30"})]) {
  test("invalid run/clock metadata is not shown as a healthy evidence snapshot", async () => {
    const h = mounted(); h.credential("learner-a"); h.responses.push(bad); await h.refresh();
    assert.equal(h.node("#run-state").textContent, "disconnected");
    assert.equal(h.node("#elapsed").textContent, "00:00:00");
    assert.match(h.node("#notice").textContent, /unavailable/);
  });
}

test("filter interaction observes external credential changes before rendering old receipts", async () => {
  const h = mounted(); h.credential("learner-a"); await load(h);
  h.credential("learner-b"); h.node("#search").value = "Synthetic";
  h.node("#search").events.input();
  assert.equal(references(h).length, 0); assert.equal(h.node("#search").value, "");
  assert.equal(h.node("#run-state").textContent, "disconnected");
});

test("filters preserve same-run selections and render hostile evidence as literal text only", async () => {
  const h = mounted(); h.credential("learner-a");
  const hostile = '<img src=x onerror="steal()">';
  await load(h, page([signal(1, "literal", {message: hostile, facts: {host: hostile}}),
    signal(2, "identity-event", {category: "identity"})]));
  const card = h.node("#signals").children[1];
  assert.equal(card.children[1].textContent, hostile);
  h.node("#category").value = "response"; h.node("#search").value = "steal";
  h.node("#search").events.input(); assert.deepEqual(references(h), ["literal"]);
  h.responses.push(page([], {next_sequence: 2})); await h.refresh();
  assert.equal(h.node("#search").value, "steal"); assert.equal(h.node("#category").value, "response");
  assert.deepEqual(references(h), ["literal"]);
  assert.ok(h.calls.every(({path}) => path.startsWith("/api/participant/evidence?")));
});
