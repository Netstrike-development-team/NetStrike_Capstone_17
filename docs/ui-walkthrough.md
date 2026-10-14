# Local evidence UI and reproducible client walkthrough

## Synthetic sign-in and MFA run safety (#161)

`/sso` now requires an inspected, valid current-run snapshot before enabling
sign-in, MFA or session-review actions. Each browser write pins that `run_id`;
only one write can be pending. The four SSO mutation APIs use the existing
atomic `X-Exercise-Run-ID` guard: stale headers return 409 before any action or
audit write; malformed/duplicate headers return 422. Headerless legacy clients
still work but do not gain stale-run protection. Origin restrictions, reserved
synthetic identities, body limits and scheduled-MFA bearer roles remain required;
the run header grants no authority. Session-review responses include the same
run/clock metadata as sign-in and MFA responses, under the shared run lock.

Reads and responses bypass caching. Current read failures remove the inspected
challenge and write authority. A failed/uncertain write is never automatically
repeated; a fresh GET inspects its actual result before another manual action.
Observed token changes invalidate prior callbacks, even token A→B→A; an in-flight
write keeps the pending lock until it settles. Old reads, wrong-run write receipts
and delayed announcements cannot restore stale controls. Pause/stop/completion
disable writes. Navigation clears transient authority/token; a restored page
requires inspection again. An observed run change clears old sessions, retry
view and scheduled-token input. An unobserved reset cannot instantly update a
browser, so the server guard remains essential. Aborting a browser read does not
cancel or undo a server mutation. Headerless clients and unobserved transient
token changes are outside these browser guarantees.

API and mounted actual `sso.js` regressions cover these boundaries. SSO
implementation/HTML/JS/CSS are included in exact rehearsal source fingerprints.
These checks are not real-browser, representative-learner or live-range
acceptance. Anna (#99) and Patrick (#104) should test rapid Approve/Deny,
delayed responses, token changes, failed reads, an old tab across reset and
back/forward restoration on the final deployment. This remains a contained,
vendor-neutral mock—not a real IdP, MFA gateway or EDR.

The participant console now links to `/evidence`: an authenticated, read-only
view of **actual local synthetic events**, not a Splunk dashboard. It addresses
the difference between situation messages and attack telemetry: the two initial
MSEL messages do not increase merely because session replay emits access events.

## Evidence boundary

`GET /api/participant/evidence?after_sequence=0&limit=100` returns current-run
facts in ingestion-sequence order, with an opaque event ID and occurrence time.
History can predate play; receipt order is not a claim about chronology. Pages
are bounded to 100 signals; the browser retains at most 500 recent signals.

- Participant-visible identity/helpdesk, endpoint/directory, cloud and
  impact/recovery signals are projected into reviewed scalar facts.
- Only the authenticated participant's own completed/denied/replayed action
  receipts may be projected from the staff audit. Other actors' receipts, engine
  actions, grading/override/control events, raw nested data, server paths,
  objectives and secret fields are never returned by this endpoint.
- Role and actor ID come from the server token, not request query/body fields.
- Explicit Connect/reconnect clears evidence, filters, cursor and run/clock
  metadata immediately, even with an earlier request pending. Observed credential
  changes during polling/filter interactions do the same; a same-token reconnect
  starts a fresh request generation. Obsolete reads are cancelled where possible
  and late success/failure/finally callbacks cannot overwrite or unlock a new view.
- An observed reset during pagination clears the prior run and fetches the new
  run from sequence zero. Current auth, transport or malformed-page failures clear
  evidence and connected metadata instead of showing old facts as a healthy view.
- Each refresh fetches at most ten 100-signal pages, retaining the latest 500
  signals. If more pages remain, the summary explicitly says so; subsequent manual
  refresh or polling continues from the cursor. This is not a complete ledger or
  a source-freshness/ingestion-health certificate.
- Same-run healthy polling preserves filters, and evidence is rendered with
  `textContent`, never interpreted as HTML. Requests bypass browser caching.
- Read operations append no events and cannot alter simulation state.
- Existing situation-message and facilitator/export APIs are unchanged.

This development viewer is not an EDR, a SIEM, new alert detection, a replacement
for Patrick's Splunk work or live-range acceptance. Response receipts prove an
action result, not that the whole incident has been contained. Future evaluator
scoring/report quality remains #84.

### Browser refresh regression checks (#159)

The mounted actual `evidence.js` tests reproduce the former Connect/busy-guard
defect: changing tokens during a pending refresh left old participant receipts
visible. They cover immediate clearing, ignored late responses and observed
token A→B→A changes, same-token reconnect, disconnect, run reset within/at the
pagination budget, current auth/transport failures, malformed pages, filter
preservation and the 500-signal limit. Viewer HTML/JS now participate in exact
local-rehearsal source fingerprints.

These are DOM-double regressions, not a completed real-browser or representative
learner rehearsal. Anna/Patrick should include a slow evidence request while
switching accounts, an old tab across reset, and an unavailable endpoint in actual
usability/deployment checks. No new guarantee of immediate observation of an
unannounced server reset or a token change outside page interactions/polling is
made. A transient A→B→A storage change that the page never observes is outside
this guarantee. The API's server-owned role/actor projection remains unchanged;
client cancellation is not server authorization or secure deletion from memory.

## Recording the real application

Preview only (no file creation or server/browser startup):

```bash
python scripts/record_ui_walkthrough.py
```

Recording tooling is optional and separate from the project runtime. In a local
tooling venv, install `playwright` and `imageio-ffmpeg`, use installed Google
Chrome, and install the recording encoder with `python -m playwright install ffmpeg`.
On macOS, offline narration uses the installed Samantha `say` voice; elsewhere
pass `--no-narration`. No subscription or cloud media service is needed.

```bash
# A NEW output folder is required. Existing artifacts are never overwritten.
python scripts/record_ui_walkthrough.py --execute --output /absolute/new/video-folder
# Short silent end-to-end browser smoke check:
python scripts/record_ui_walkthrough.py --execute --fast --output /absolute/new/qa-folder
```

The recorder creates a fresh loopback-only portal, random task-owned role tokens,
temporary SQLite and an explicitly provisioned disposable root. It drives actual
browser forms and real server control APIs—no intercepted/mocked API responses.
The clock is paused while inspecting screens and advanced for demonstration;
both narration and chapter captions disclose this compression.

The intentionally adverse demonstration denies the first new MFA request but
leaves previously compromised identity/endpoint access open. It then shows
mock-cloud scope, later key revocation, marker-only impact, default-preview
recovery, explicit restore/hash validation and an evidence-backed brief. Denial
of a new prompt is not misrepresented as undoing earlier compromise; key
revocation does not erase already observed mock access. Mock access/claims never
establish real external transfer.

The finished video is H.264/AAC (with narration), 1600×900, with a reserved caption
strip **outside** the actual browser viewport. The deliverable folder also keeps
the raw browser video, narration text/audio, chapter subtitles, reference frames,
manifest and schema-validated canonical JSONL from the recorded run.

Completion verifies final play/recovery, export correlation, a fresh clean
application reset and populated mobile evidence layout. Task-owned browser/server
processes are stopped automatically even on failure. Temporary decoys/database
are removed; the exported run evidence and media remain in the new output folder.
Application reset is distinct from Cyber Range VM snapshot restoration.

Reference for the recording-only integration:
[Playwright video lifecycle](https://playwright.dev/python/docs/videos) and
[installed Chrome channel](https://playwright.dev/python/docs/browsers#google-chrome--microsoft-edge).

## Strict real-browser smoke gate (#169)

The `browser-smoke` job in `Local full-play rehearsal` now runs the **existing
18-step journey** in actual managed Chromium against a fresh loopback application.
It complements, rather than replaces, the Node DOM-double regressions and the
24-case service rehearsal. Browser forms, script loading, actual HTTP, evidence
filtering, mock-cloud actions, default-preview recovery, five-file restore/hash
validation, the final brief, JSONL download, populated 390px mobile evidence and
application reset are exercised without intercepted/mocked API replies. Reset
explicitly accepts only the known confirmation for this task's disposable run;
the application's safety confirmation is not removed. Direct facilitator APIs
advance/pause the clock for a compressed demonstration, not a real 130-minute run.

Run it locally in a development tooling venv, from the repository root:

```bash
python -m pip install -r dashboard/requirements.txt -r scripts/requirements-browser-smoke.txt
python -m playwright install chromium
# On Linux, install browser system dependencies with --with-deps instead.
python scripts/record_ui_walkthrough.py --execute --smoke-only --output /absolute/new/browser-smoke-folder
```

Without `--execute`, even `--smoke-only` stays preview-only. Existing output
directories are rejected. Smoke mode implies fast/silent operation, uses the
pinned Playwright package's managed browser instead of installed Chrome, and
does not import `imageio-ffmpeg`, run narration/encoding or create video. The
Playwright browser installer may also fetch its bundled media helper; no media
processing is performed. Regular video and `--fast` video commands above retain
installed Chrome and their recording dependencies.

CI uses Ubuntu 24.04 / Python 3.11, read-only repository permissions, a ten-minute
bound, no ignored failures and 14-day `browser-smoke-<checkout SHA>` artifacts.
Developer tooling downloads happen on the CI/development host, **not** in the
air-gapped scenario VMs; application/runtime dependencies and Patrick's offline
bundle are unchanged. Installation follows the
[official Playwright CI instructions](https://playwright.dev/python/docs/ci).

Artifacts contain chapter screenshots, mobile evidence screenshot, schema-checked
canonical `events.jsonl`, server diagnostics and a successful `manifest.json`.
The receipt includes the checked-out Git revision/dirty state, the full existing
rehearsal source inventory (plus browser tooling/test inputs), Python/Playwright/
browser versions and artifact hashes. Source is checked before and after play;
a changed source fails. Hosted PR checkout may be a synthetic merge commit, not
the feature head: use the actual recorded revision. A hash records consistency,
not authenticity or independent acceptance. Failure keeps available diagnostics
and `failure.json`, never a success manifest. There is no token, SQLite, browser
profile, network trace, video or narration export in smoke mode. Task-owned browser,
server, database and decoys are cleaned up on ordinary success/failure. Forced
runner termination is outside Python's cleanup guarantee.

Page errors, local HTTP errors and failed local requests fail the check. Chromium's
`net::ERR_ABORTED` is excluded because navigation and the application's deliberate
obsolete-read cancellation can cause it; journey assertions must still complete.
Screenshots are diagnostic, **not** pixel-diff/layout-completeness certification.
This single adverse path does not cover every branch, delayed-response race or
browser engine. Private support/evaluator/archive interactions are covered by
the separate staff journey below, not the scenario walkthrough. Neither certifies
representative usability, accessibility, authored hints/rubric, realistic timing,
Splunk ingestion/RBAC, Windows/AD, load, VM snapshot restoration or client acceptance.
Anna's #99 and Patrick's #104 remain open; main promotion gates are unchanged.

## Help, evaluator and archive browser journey (#171)

The same strict `browser-smoke` job also executes a separate **14-step staff
journey**, reusing the loopback/managed-Chromium harness with its own fresh database,
tokens and decoys. Same development dependencies as above; no media tooling:

```bash
python scripts/staff_browser_smoke.py  # inert preview; needs no site packages
python scripts/staff_browser_smoke.py --execute --output /absolute/new/staff-smoke-folder
```

It checks actual Start/Pause/Stop buttons and run headers, two participants' private
questions, facilitator clarification, literal HTML-like reply text, platform-only
operator response after stop and read-only evaluator assistance. Then it tests a
synthetic `not_observed` judgment/correction, completed same-revision draft refresh,
run/snapshot-pinned current bundle/AAR downloads, capture/show/archive downloads,
reset, empty current review/help and byte-identical historical files after reset.
Historical review never populates the current judgment form.

All replies/review prose identify **synthetic automation fixtures**, not approved
coaching or actual learner evaluation/calibration. Play deliberately stops early;
only one objective has two `not_observed` revisions. The report stays provisional
with no numeric grade; five baseline decoys stay unchanged. This journey does not
claim full-play completion, decoy restoration or mobile validation.

Bundles are validated, role/actor/correlation checked and their reports rebuilt
offline; downloaded Markdown must match. Canonical archived JSONL is checked
against its bundle and schema/run/IDs/sequence. Its frozen ledger **predates the
capture audit and reset**, not all later administrative activity. Bundle/AAR/JSONL
downloads for the same archive ID must stay byte-identical after reset.

The combined 14-day CI artifact now contains `browser-smoke-evidence/` and
`staff-browser-smoke-evidence/`, each with its own manifest/screenshots/events.
Staff output also includes current/archive/after-reset downloads. Receipts name
`journey_id`, only that journey's completed assertions, exact source/tooling identity
and all exported artifact hashes. Both scripts/tests are source-fingerprinted.
Either step failing fails the job. Existing timeout/cleanup rules remain; no new
CI job, paid service or application VM runtime dependency. Start confirmation here
acknowledges a disposable developer fixture, not external range admission.

Focused API/DOM tests still cover other races/failure paths. This is not every
branch, browser engine, multi-tab conflict, accessibility or representative
usability proof. Anna #99/#100 retains content/guides/calibration and non-author
testing; Patrick #104 retains deployed role/privacy, Splunk/Windows/load, realistic
timing and clean-snapshot rehearsals. No client acceptance or main promotion.
