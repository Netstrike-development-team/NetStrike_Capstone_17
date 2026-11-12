# Compare learner audit evidence with a supplied raw export (#187)

Aya owns this offline utility; Patrick owns the independent receiver export and
real Splunk/role/VM acceptance. No new dependency, licence, credentials or network
connection is needed. The module is included in the bundled `dashboard` source.

Use **`dashboard.learner_check`** for `netstrike:learner:audit:v1` data from the
separate learner spool. Keep using **`dashboard.telemetry_check`** for the complete
private canonical ledger. The two contracts are intentionally not interchangeable.
Neither tool grants participant access or changes Splunk/forwarder configuration.

## 1. Preserve the expected local baseline

Choose the exact exercise/run, source/bundle revision and a stable evidence
boundary. Stop the synthetic run or otherwise record a fixed cutoff, finish
publication and wait for forwarding to drain. Both staff and learner publisher
previews must show no newly selected/pending batches/events. Retain original
immutable source batches and their manifests; do not edit them to force a match.

Save the selected run's **published learner projection** as a separate
`expected-learner.jsonl`. It must contain all intended learner rows for the
recorded boundary, not canonical staff events or a baseline recreated from Splunk.
For example, in approved staff staging, this standard-library preparation snippet
selects one run without rewriting fields. Choose a **new** destination whose
parent already exists; replace the sample run ID before execution:

```python
import json
from pathlib import Path

exercise_id = "operation-silent-spider"
run_id = "THE-RECORDED-RUN-ID"
spool = Path("/var/lib/netstrike/learner-event-spool")
destination = Path("/approved/staff/new-expected-learner.jsonl")
with destination.open("x", encoding="utf-8") as output:
    for batch in sorted(spool.glob("batch-*/events.jsonl")):
        for line in batch.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["exercise_id"] == exercise_id and event["run_id"] == run_id:
                output.write(line + "\n")
```

Run this only after the existing publisher's integrity preview succeeds, against
staff-managed staging; it is preparation, not part of the read-only comparator.
An empty, duplicated or invalid prepared baseline is refused by the comparator.
The tool cannot prove a syntactically valid supplied baseline was complete or
authentic; retain its publisher/boundary provenance separately.

## 2. Obtain an independent Splunk export

Patrick runs an event search with the assigned exercise/run and absolute time
window covering the complete baseline. Use the participant role as part of the
separate actual access test; record the role, query, search job, time window,
source revision and forwarding state. Example base query:

```spl
index=netstrike sourcetype="netstrike:learner:audit:v1"
exercise_id="operation-silent-spider" run_id="THE-RECORDED-RUN-ID"
```

Do not add `stats`, `head`, `dedup`, transformed `_raw`, event-ID allowlists or
other commands that conceal loss, changed data, duplicates or unexpected rows.
In Splunk Web, use **Export → Raw Events**, export the complete results and save
as `observed-learner.jsonl`. Do not use a result-count cap or preview. Splunk's
[10.0 export instructions](https://help.splunk.com/en/splunk-enterprise/search/search-manual/10.0/export-search-results/export-data-using-splunk-web)
document Raw Events for event searches, optional result limits and possible
search reruns; preserve the actual export/search receipt if rerun occurs.

CSV, JSON result envelopes containing `_raw`, extracted-field tables, Windows
XML and canonical staff-ledger rows are not accepted. Do not strip private or
unexpected data from a bad export and rerun the checker to manufacture a pass.
Keep both original files independently; a copied local baseline is not receiver
evidence even if it has a different filename.

## 3. Compare offline

From the matching reviewed source and installed Python environment:

```sh
python -m dashboard.learner_check \
  --expected /approved/staff/new-expected-learner.jsonl \
  --observed /approved/staff/observed-learner.jsonl \
  --exercise-id operation-silent-spider \
  --run-id THE-RECORDED-RUN-ID
```

The tool reads only supplied files and the existing learner schema/allowlist. It
does not open SQLite, construct a portal, publish/repair data, start a server,
contact Splunk, install anything or create a report file. Save stdout/stderr and
exit status through approved staff evidence handling if a receipt is needed.

- **0 / match:** unique IDs and complete learner objects agree, independent of
  row order, JSON key order, whitespace and CRLF/LF. Unlike the canonical ledger,
  this filtered feed has no contiguous sequence requirement.
- **1 / mismatch:** valid scoped inputs disagree. Counts report missing/changed
  expected IDs, repeated receiver IDs and unexpected receiver rows. Categories
  overlap: a changed duplicate is both changed and duplicated; repeated unexpected
  rows count as unexpected as well as duplicates. Empty observed data reports all
  baseline events missing, never a vacuous pass.
- **2 / invalid input:** empty/duplicate baseline, wrong exercise/run, incompatible
  schema or unreviewed service/operation/facts, private/extra fields, incomplete
  actor/target pairs, malformed/wrapped JSON or unsafe/changed/oversized files.
  Wrong scope is refused, not silently filtered out.

The strict projection validator is shared with the publisher. Values are not
coerced or repaired: booleans, integers, strings and timestamps must retain their
contract types/content. This is not a general-purpose free-text secret detector.
All records are synthetic reviewed SimCorp audits, not vendor/Windows/EDR logs.

## Bounds and interpretation

Each file is at most 32 MiB, each event line at most 256 KiB, and each input at
most 10,000 events. UTF-8 raw JSONL is required; no BOM, blank lines, non-finite
numbers or duplicate JSON keys. Symlink leaves, hardlinks, devices, directories,
FIFOs, same-file comparisons and input changes during reading are refused. Parent
directories are trusted caller-selected staging; the tool does not enforce ACLs
or defend against a hostile administrator/concurrent parent replacement.

Receipts contain only fixed codes/counts/file SHA256 digests and scope/contract
labels—not raw events, event IDs, actor data, private paths or supplied run IDs.
Record the selected exercise/run separately with the receipt. Hashes identify
the supplied bytes, not signed authenticity or independent search provenance.

`live_splunk_verified`, `participant_access_verified` and
`external_readiness_verified` always remain **false**, even on a file match.
This utility does not verify parsed `_time`/fields, freshness/delivery latency,
index permissions, absence of private data outside the selected query, retention,
licence/disk volume, exactly-once transport or VM/UF snapshot behavior. Patrick's
#79/#104/#86 remain separate. Preserve failures; investigate the search boundary,
backlog, replay/checkpoints, line breaking, truncation or input format without
editing evidence to hide the problem.

`indexed_event_boundaries_verified` also remains **false**. Counts here refer to
JSONL records in the supplied files, not independently queried indexed event
counts. Raw export can flatten a multi-line indexed event: two JSON lines might
match the expected bytes even if Splunk indexed them as one event. Patrick must
independently compare the scoped Splunk event count with the baseline and inspect
event boundaries and extracted fields; do not use this receipt to certify them.

## Developer verification

Tests cover valid/malformed/private/wrong-scope inputs, all transport faults,
read-only behavior and the 24 real local rehearsal projections. The actual
offline bundle smoke runs the tool for both initial and reset runs with explicitly
labelled **synthetic local receiver fixtures**, plus injected missing/duplicate/
changed/wrong-run cases. Its comparison receipt is developer proof only, not an
export from Splunk. No live Splunk or new offensive action is performed.
