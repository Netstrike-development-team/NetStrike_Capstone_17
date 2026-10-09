import assert from "node:assert/strict";
import {test} from "node:test";
import {SupportSession} from "../static/support.js";

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
const question = (request_id) => ({request_id, objective_id: "LO2", question: "Synthetic question", response: null});
const snapshot = () => ({run_id: "run-a", run_state: "running", principal_role: "facilitator",
  requests: [question("question-a"), question("question-b")]});
const fields = (request_id = "question-a") => ({request_id, kind: "clarification", objective_ids: ["LO2"], message: "Human reply"});
function harness({staff = true, observer = false} = {}) {
  let credential = "staff-a", key = 0;
  const replies = [], calls = [];
  const session = new SupportSession({staff, observer, readToken: () => credential, makeKey: () => `key-${++key}`,
    call: async (path, options) => {
      calls.push({path, options}); const reply = replies.shift(); if (reply instanceof Error) throw reply; return await reply;
    }});
  const load = async (state = snapshot()) => { replies.push(state); await session.refresh(); };
  return {session, replies, calls, load, credential: (value) => { credential = value; }};
}

test("same-token reconnect does not allow a second permanent staff reply while the first is pending", async () => {
  const h = harness(); await h.load(); const pending = deferred(); h.replies.push(pending.promise);
  const first = h.session.submit(fields()); h.session.reset(); await h.load();
  h.replies.push({run_id: "run-a"}); const second = await h.session.submit(fields("question-b"));
  assert.equal(h.calls.filter(({options}) => options.method === "POST").length, 1);
  assert.equal(second, false);
  pending.resolve({run_id: "run-a"}); assert.equal(await first, false);
});

test("a rejected support reply cannot leave pre-write queue authority enabled", async () => {
  const h = harness(); await h.load();
  h.replies.push(Object.assign(new Error("Question already answered"), {status: 409}));
  assert.equal(await h.session.submit(fields()), false);
  assert.equal(h.session.snapshot, null);
  assert.equal(h.session.canWrite(), false);
  assert.equal(await h.session.submit(fields("question-b")), false);
  assert.equal(h.calls.filter(({options}) => options.method === "POST").length, 1);
});

for (const change of ["reconnect", "credentials", "run"]) {
  for (const outcome of ["success", "failure"]) {
    test(`pending ${outcome} retains the actual request lock across ${change}`, async () => {
      const h = harness(); await h.load(); const pending = deferred(); h.replies.push(pending.promise);
      const write = h.session.submit(fields());
      if (change === "reconnect") h.session.reset();
      if (change === "credentials") h.credential("staff-b");
      const fresh = {...snapshot(), run_id: change === "run" ? "run-b" : "run-a"};
      await h.load(fresh);
      assert.equal(h.session.busy, true); assert.equal(h.session.canWrite(), false);
      assert.equal(h.session.operation, null);
      assert.equal(await h.session.submit(fields("question-b")), false);
      if (outcome === "success") pending.resolve({run_id: "run-a"});
      else pending.reject(new Error("Private old-account error"));
      assert.equal(await write, false); assert.equal(h.session.busy, false);
      assert.equal(h.session.snapshot, null); assert.equal(h.session.operation, null);
      assert.doesNotMatch(h.session.message, /Private old-account|Message recorded|Delivery uncertain/);
      await h.load(fresh); assert.equal(h.session.canWrite(), true);
    });
  }
}

for (const stage of ["before-send", "while-pending"]) {
  for (const outcome of ["success", "rejection", "uncertainty"]) {
    test(`${stage} read cannot restore authority after ${outcome}`, async () => {
      const h = harness(); await h.load(); const old = deferred(), pending = deferred();
      let read;
      if (stage === "before-send") { h.replies.push(old.promise); read = h.session.refresh(); }
      h.replies.push(pending.promise); const write = h.session.submit(fields());
      assert.equal(h.session.snapshot, null);
      if (stage === "while-pending") { h.replies.push(old.promise); read = h.session.refresh(); }
      if (outcome === "success") pending.resolve({run_id: "run-a"});
      else pending.reject(Object.assign(new Error("Unconfirmed"), {status: outcome === "rejection" ? 409 : 503}));
      await write; old.resolve(snapshot()); await read;
      assert.equal(h.session.snapshot, null); assert.equal(h.session.canWrite(), false);
      assert.equal(Boolean(h.session.operation), outcome === "uncertainty");
      assert.equal(await h.session.submit(fields()), false);
      assert.equal(h.calls.filter(({options}) => options.method === "POST").length, 1);
    });
  }
}

test("late pre-settlement auth failure cannot erase a fresh post-settlement queue", async () => {
  const h = harness(); await h.load(); const old = deferred(), pending = deferred();
  h.replies.push(pending.promise); const write = h.session.submit(fields());
  h.replies.push(old.promise); const read = h.session.refresh();
  pending.resolve({run_id: "run-a"}); await write;
  const fresh = {...snapshot(), requests: [question("question-b")]}; await h.load(fresh);
  old.reject(Object.assign(new Error("obsolete rejection"), {status: 403})); await read;
  assert.equal(h.session.snapshot, fresh); assert.equal(h.session.canWrite(), true);
});

test("inspection during send never labels the still-pending delivery as an uncertain retry", async () => {
  const h = harness(); await h.load(); const pending = deferred(); h.replies.push(pending.promise);
  const write = h.session.submit(fields()); await h.load();
  assert.match(h.session.message, /Sending and recording/);
  assert.equal(h.session.busy, true); assert.equal(h.session.canWrite(), false);
  pending.resolve({run_id: "run-a"}); await write;
});

test("uncertain terminal replay preserves exact body, kind, objective scope and key", async () => {
  const h = harness(); await h.load(); h.replies.push(Object.assign(new Error("audit uncertainty"), {status: 503}));
  await h.session.submit(fields()); const original = h.calls[1].options.body;
  assert.equal(h.session.snapshot, null);
  await h.load({...snapshot(), run_state: "completed", requests: []});
  assert.equal(h.session.canWrite(), false);
  h.replies.push({run_id: "run-a", replayed: true});
  assert.equal(await h.session.submit({request_id: "question-b", kind: "platform_issue", objective_ids: ["LO5"], message: "Changed"}), true);
  const posts = h.calls.filter(({options}) => options.method === "POST");
  assert.equal(posts.length, 2); assert.equal(posts[1].options.body, original);
  assert.match(h.session.message, /no duplicate/); assert.equal(h.session.operation, null);
});

test("uncertain payload survives unavailable inspection without permitting a retry until a fresh queue arrives", async () => {
  const h = harness(); await h.load(); h.replies.push(new Error("Network")); await h.session.submit(fields());
  const frozen = h.session.operation; h.replies.push(new Error("Unavailable")); await h.session.refresh();
  assert.equal(h.session.operation, frozen); assert.equal(h.session.snapshot, null);
  assert.equal(await h.session.submit(fields()), false);
  await h.load(); h.replies.push({run_id: "run-a", replayed: true});
  assert.equal(await h.session.submit({}), true);
  const posts = h.calls.filter(({options}) => options.method === "POST");
  assert.equal(posts[0].options.body, posts[1].options.body);
});

test("new credential observed only at an old receipt clears private retry context and releases the lock", async () => {
  const h = harness(); await h.load(); const pending = deferred(); h.replies.push(pending.promise);
  const write = h.session.submit(fields()); h.credential("staff-b"); pending.resolve({run_id: "run-a"});
  assert.equal(await write, false); assert.equal(h.session.busy, false);
  assert.equal(h.session.contextRun, null); assert.equal(h.session.snapshot, null); assert.equal(h.session.operation, null);
});

test("authorization failure clears retry/private context, never leaving the real pending slot stranded", async () => {
  const h = harness(); await h.load(); const pending = deferred(); h.replies.push(pending.promise);
  const write = h.session.submit(fields());
  h.replies.push(Object.assign(new Error("revoked"), {status: 403})); await h.session.refresh();
  assert.equal(h.session.busy, true); assert.equal(h.session.operation, null);
  pending.reject(new Error("obsolete transport error")); assert.equal(await write, false);
  assert.equal(h.session.busy, false); assert.equal(h.session.snapshot, null);
});

test("learner pending slot also survives reconnect without creating a second question", async () => {
  const h = harness({staff: false}); const fresh = {...snapshot(), principal_role: "soc_analyst", requests: []};
  await h.load(fresh); const pending = deferred(); h.replies.push(pending.promise);
  const fields = {objective_id: "LO2", message: "Synthetic question"}; const write = h.session.submit(fields);
  h.session.reset(); await h.load(fresh);
  assert.equal(await h.session.submit(fields), false);
  assert.equal(h.calls.filter(({options}) => options.method === "POST").length, 1);
  pending.resolve({run_id: "run-a"}); assert.equal(await write, false);
  await h.load(fresh); assert.equal(h.session.canWrite(), true);
});

test("malformed support scope cannot become write authority", async () => {
  for (const run_id of [null, "", " run-a", "run-a\n", "a".repeat(129)]) {
    const h = harness(); await h.load({...snapshot(), run_id});
    assert.equal(h.session.snapshot, null); assert.equal(h.session.canWrite(), false);
    assert.equal(await h.session.submit(fields()), false);
  }
});
