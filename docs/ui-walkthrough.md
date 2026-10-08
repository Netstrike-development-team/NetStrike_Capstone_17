# Local evidence UI and reproducible client walkthrough

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
