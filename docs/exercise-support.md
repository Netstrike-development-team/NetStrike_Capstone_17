# Human support workflow — API foundation

The charter permits learners to request hints and requires attributable human
evaluation of supported performance. These APIs provide that missing recording
path. They do not fetch an answer key, write learning objectives, automatically
coach, assign grades or choose a scenario branch.

**This increment is API/backend work plus an offline demo.** The current browser
consoles have no support form yet. A follow-up can connect them to this contract
after Anna reviews wording and the learner workflow. No new hosted website,
external service, license, live VM or Splunk configuration was created.

## Roles and routes

| Route | Authorized role / projection |
| --- | --- |
| `GET /api/participant/support` | Any configured participant role; only that actor's current-run threads. |
| `POST /api/participant/support` | Participant; create a bounded question during running/paused play. |
| `GET /api/facilitator/support` | Facilitator, technical operator or evaluator; full current-run queue. |
| `POST /api/facilitator/support/replies` | Facilitator authors any reply kind; technical operator can report platform issues only. |

Evaluator is read-only and cannot coach. Simulated-user and identity-capture
credentials cannot access the workflow. Bearer tokens resolve the actor/role
server-side; JSON actor/role fields are forbidden. Reads are inert and
`Cache-Control: no-store`. Unauthenticated reads/writes return 401, disallowed
roles 403, invalid fields 422 and stale/conflicting/lifecycle operations 409.

## Request and reply bodies

Read the current `run_id` from the participant state or support view, then submit:

```json
{
  "run_id": "current-exercise-run",
  "idempotency_key": "locally-generated-unique-question-key",
  "objective_id": "LO2",
  "message": "How should we distinguish observed facts from inference?"
}
```

The receipt contains `request_id`, `event_id`, `run_id`, `status` and `replayed`.
Staff use the exact request ID from the queue, not a guessed participant identity:

```json
{
  "run_id": "current-exercise-run",
  "request_id": "request-event-uuid-from-the-queue",
  "idempotency_key": "locally-generated-unique-reply-key",
  "kind": "clarification",
  "message": "Example human-authored explanation, not approved facilitator content.",
  "objective_ids": ["LO2"]
}
```

`kind` is `hint`, `clarification` or `platform_issue`. Staff select the actual
affected objectives (unique LO1–LO5), which may differ from the learner's requested
objective. This label is a human assertion for evaluator review, not proof of
independence or automatic `performed_with_support`/`not_observed` classification.
Requests alone do not prove help was given. Absence of recorded requests does not
prove there was no off-platform assistance; staff must still record/review it.

Questions/replies are plain human text, at most 1,024 characters, not empty or
whitespace-only, and without unsupported control characters. Mutating bodies are
stream-bounded to 20 KiB before parsing, including chunked bodies. Invalid-body
errors never echo the submitted prose. Run/request/retry fields are bounded to
128 characters. HTML is not interpreted; Markdown exports escape human prose.
Future browser forms must use text rendering, never raw `innerHTML` for messages.

## Bounds, retries and lifecycle

- One pending request per participant; after an answer, another question may be
  created. Limits: 10 questions per actor and 50 questions for one exercise run.
  These bound the support queue, not the whole incident ledger or Splunk volume.
- Retry keys are scoped to actor, run and operation. Retrying the same normalized
  payload returns the existing event without duplication; reusing a key for a
  different question/reply/objective scope fails. A request gets one immutable
  reply; concurrent replies have one winner. No deletion or silent editing.
- Fresh requests and coaching replies require running/paused play. Questions
  during pause do not move exercise time. A stopped run may receive a platform-issue
  explanation for an existing pending question, so a technical interruption can
  be recorded honestly. Completed runs cannot receive new replies. Exact retries
  of existing records remain read-like and do not create late assistance.
- Every mutation names the current run explicitly and holds the same run lock as
  reset/timed delivery. An old browser/API retry cannot write into a new run.
  A reset waits for an in-flight reply, archives it, then begins an empty queue.
- Communication does not invoke safe-action adapters or grading. Staff can explain
  a clock fault while the stopped runtime remains latched; a reply never resumes it.

If a support audit write fails, no successful answer receipt is fabricated and
play is safety-stopped by an internal `system/exercise-support` operator. Every
safety latch is attempted. An ambiguous write that committed before an error may
be discovered by a same-key retry; there is no unsafe sequence rewind. Middle-of-
ledger gaps now explicitly block review archive/reset, not just missing tail
events. Preserve the database/evidence for diagnosis rather than deleting records
or claiming a partial archive is complete.

## Evidence and review

Canonical `exercise.support.requested` and `exercise.support.responded` events
use source `exercise-support`, facilitator visibility and shared run sequencing.
Replies correlate with the original request. The ledger retains requester and
responder attribution, exercise time, run state, kind, objective scope and text.
The participant API releases only that actor's question and intentional reply;
it does not expose other learners, retry keys, staff actor IDs, grading text or
controller data. Global participant state/evidence feeds do not release support
messages. Treat source database, staff exports and the spool as private evidence;
no real personal data, credentials or tokens belong in questions/replies. Free
text is intentional evidence, not an automatic secret-scrubbing service.

Staff JSON AAR adds `support_requests` and `support_note`; Markdown includes a
Human assistance section. Portable validation rejects forged role/source/scope,
orphan or duplicate replies, invalid lifecycle/time and retry-key violations even
if someone recomputes a bundle checksum. This is structural validation, not a
cryptographic signature. Existing objective observations and human judgments are
unchanged; evaluators can cite support event IDs using the existing review API.
Archives retain the transcript after application reset, and existing staff-only
spool publication preserves it. VM rollback still requires external export first.

## Offline demonstration and tests

```bash
python -m dashboard.support_demo
python -m dashboard.support_demo --execute
python -m pytest dashboard/tests/test_support.py dashboard/tests/test_archives.py -q
```

Default preview creates no runtime, evidence or files. Explicit execution creates
a memory-only mock run, records a synthetic learner question and human-authored
clarification, shows the requester view, archives a deliberately partial stopped
run, resets and rejects a stale-run question. It prints synthetic JSON, starts no
server, contacts no network and manufactures no evaluator judgments. It is not
browser usability testing, a complete exercise, Splunk proof or range acceptance.

Aya owns the protocol/API/tests and later browser integration. Anna owns approved
hint/clarification content, participant wording and evaluator calibration (#99/#100).
Patrick owns deployment, staff-only Splunk handling and live rehearsal (#102/#103/#104).
